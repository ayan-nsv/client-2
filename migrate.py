"""Run migrations for the products this deployment actually has installed.

Replaces a blanket ``alembic upgrade head``, which no longer works anyway: the
per-product branches mean there are several heads and ``head`` is ambiguous.

Order matters, and so does the bootstrap problem it creates:

1. ``core@head`` runs first. Its chain descends from the shared history, so this also
   creates the schemas, every pre-split table, and ``core.installed_products`` itself.
   Core is not optional — it owns companies, users, and the registry.
2. Only then can ``core.installed_products`` be read to find out which products are
   enabled. On a brand-new database the table is created moments earlier by step 1,
   and seeded by that migration, so it is never empty by the time it is read.
3. Each enabled product's branch is upgraded on its own. A product that is disabled,
   or absent from the table, is skipped — its schema stays empty and its tables are
   never created.

Usage::

    python migrate.py              # upgrade core + every enabled product
    python migrate.py --all        # upgrade every branch, ignoring installed_products
    python migrate.py --product market_planner   # upgrade one branch
    python migrate.py --dry-run    # print what would run

Creating a new revision for a product needs both flags — the branch and the scope.
``-x`` is a global Alembic option, so it goes before the subcommand::

    alembic -x product=market_planner revision --autogenerate \\
        -m "add x" --head market_planner@head

``--head`` decides which branch the revision lands on; ``-x product=`` scopes
autogenerate to that product's schema. Omit the second and the new revision will
also carry any other product's pending schema changes.
"""

from __future__ import annotations

import argparse
import os
import sys

from alembic import command
from alembic.config import Config

from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

CORE = "core"


def _config() -> Config:
    # ALEMBIC_CONFIG matches what wait-for-db.sh already uses to locate the file.
    from migrations.version_paths import apply_shipped_version_locations

    cfg = Config(os.getenv("ALEMBIC_CONFIG") or "alembic.ini")
    # Subset trees omit unpaid product version dirs; only scan what is on disk.
    apply_shipped_version_locations(cfg)
    return cfg


def _all_branch_labels(cfg: Config) -> list[str]:
    """Every branch label defined in the version directories."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    labels = set()
    for revision in script.walk_revisions():
        labels.update(revision.branch_labels or ())
    return sorted(labels)


def _enabled_products() -> list[str] | None:
    """Product names recorded in core.installed_products, or None on a first install.

    None means "nothing has been installed here yet", which is the signal to fall
    back to the install manifest. Both an unreadable table and an *empty* one mean
    that: core's initial revision creates the table but deliberately does not seed it
    (only the installer knows what it installed), so on a brand-new database the
    table exists and is empty by the time this runs.
    """
    try:
        from core.repository.product_repo import InstalledProductRepository
        from shared.database.postgres.database_config import get_session_local

        db = get_session_local()()
        try:
            names = sorted(InstalledProductRepository(db).get_enabled_names())
        finally:
            db.close()
    except Exception as exc:
        logger.info("core.installed_products not readable yet (%s).", exc)
        return None

    return names or None


def _install_manifest(known: list[str]) -> list[str]:
    """Products to install on a database that has no installed_products yet.

    From ``INSTALL_PRODUCTS`` (comma-separated). When unset, installs whatever this
    tree ships: Alembic branches present on disk that also have product code
    (``product_catalog.shipped_product_names``). Read *only* on the first run: once
    the table exists it is the single source of truth, and adding a product later
    goes through ``--install``.
    """
    raw = (os.getenv("INSTALL_PRODUCTS") or "").strip()
    if not raw:
        from product_catalog import shipped_product_names

        shipped = shipped_product_names()
        # Prefer on-disk code ∩ migration branches. core is always first.
        selected = [CORE] + [p for p in known if p != CORE and p in shipped]
        return selected

    wanted = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [p for p in wanted if p not in known]
    if unknown:
        raise SystemExit(
            f"INSTALL_PRODUCTS names unknown product(s): {', '.join(unknown)}. "
            f"Known: {', '.join(known)}"
        )
    if CORE not in wanted:
        # core owns users, companies and the registry itself; nothing runs without it.
        wanted.insert(0, CORE)
    return wanted


def _record_installed(products: list[str]) -> None:
    """Write the installed_products rows for the products just migrated.

    This used to be seeded by a migration, which could only ever hardcode all four.
    The installer knows what it actually installed, so it records it — a product that
    was never migrated gets no row, and therefore never loads.
    """
    from core.repository.product_repo import InstalledProductRepository
    from product_catalog import get_descriptor
    from shared.database.postgres.database_config import get_session_local

    db = get_session_local()()
    try:
        repo = InstalledProductRepository(db)
        for name in products:
            descriptor = get_descriptor(name)
            if descriptor is None:
                continue
            existing = repo.get_by_name(name)
            if existing is None:
                repo.create(
                    product_name=descriptor.name,
                    installed_version=descriptor.version,
                    schema_name=descriptor.schema,
                    enabled=True,
                )
                logger.info("Recorded %s %s as installed", name, descriptor.version)
            elif existing.installed_version != descriptor.version:
                repo.update_version(existing, descriptor.version, descriptor.schema)
        db.commit()
    finally:
        db.close()


def _core_registry_table_exists() -> bool:
    """True only when core.installed_products is actually in the database.

    ``alembic upgrade core@head`` is a no-op when alembic_version already lists the
    core head. That happens after ``alembic stamp`` used to unblock autogenerate:
    the revision is marked applied, the schema is not created, and the next product
    fails on a FK to ``core.companies``.
    """
    try:
        from sqlalchemy import inspect

        from shared.database.postgres.database_config import get_engine

        return "installed_products" in inspect(get_engine()).get_table_names(
            schema="core"
        )
    except Exception:
        return False


def _require_core_applied() -> bool:
    if _core_registry_table_exists():
        return True
    logger.error(
        "core@head is stamped in alembic_version but core.installed_products "
        "does not exist. The version table was updated with `alembic stamp` "
        "without running the SQL. On this empty database run "
        "`alembic stamp base`, then restart so the revisions actually apply. "
        "Do not stamp a database that already has these tables."
    )
    return False


def _upgrade(cfg: Config, label: str, dry_run: bool) -> None:
    target = f"{label}@head"
    if dry_run:
        print(f"  would run: alembic upgrade {target}")
        return
    logger.info("Upgrading %s", target)
    command.upgrade(cfg, target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true",
                        help="Upgrade every branch, ignoring installed_products.")
    parser.add_argument("--product", help="Upgrade only this product's branch.")
    parser.add_argument("--install",
                        help="Install product(s) not yet on this deployment, "
                             "comma-separated. Creates their schema, runs their "
                             "migrations and records them as installed.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the upgrades instead of running them.")
    args = parser.parse_args(argv)

    cfg = _config()
    known = _all_branch_labels(cfg)
    if not known:
        logger.error("No branch labels found. Check version_locations in alembic.ini.")
        return 1

    if args.product:
        if args.product not in known:
            logger.error("Unknown product %r. Known: %s", args.product, ", ".join(known))
            return 1
        _upgrade(cfg, args.product, args.dry_run)
        if args.product == CORE and not args.dry_run and not _require_core_applied():
            return 1
        return 0

    if args.install:
        wanted = [p.strip() for p in args.install.split(",") if p.strip()]
        unknown = [p for p in wanted if p not in known]
        if unknown:
            logger.error("Unknown product(s): %s. Known: %s",
                         ", ".join(unknown), ", ".join(known))
            return 1
        # core must exist before any product's tables can reference it.
        _upgrade(cfg, CORE, args.dry_run)
        if not args.dry_run and not _require_core_applied():
            return 1
        for label in wanted:
            _upgrade(cfg, label, args.dry_run)
        if not args.dry_run:
            _record_installed([CORE] + wanted)
        return 0

    # Core first, always: it creates installed_products, which the next step reads.
    _upgrade(cfg, CORE, args.dry_run)
    if not args.dry_run and not _require_core_applied():
        return 1

    optional = [label for label in known if label != CORE]

    if args.all:
        selected = optional
    else:
        enabled = _enabled_products()
        if enabled is None:
            # First run: nothing recorded yet, so the manifest decides.
            manifest = _install_manifest(known)
            selected = [label for label in optional if label in manifest]
            logger.info("First install. INSTALL_PRODUCTS -> %s", ", ".join(manifest))
        else:
            selected = [label for label in optional if label in enabled]
        skipped = [label for label in optional if label not in selected]
        if skipped:
            logger.info("Not installing/upgrading: %s", ", ".join(skipped))

    for label in selected:
        _upgrade(cfg, label, args.dry_run)

    if not args.dry_run:
        _record_installed([CORE] + selected)

    return 0


if __name__ == "__main__":
    sys.exit(main())
