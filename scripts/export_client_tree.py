#!/usr/bin/env python3
"""Export a client source tree that contains only paid products.

Example::

    python scripts/export_client_tree.py \\
        --products market_planner \\
        --out /tmp/client_market_planner

The output directory is enough to build and deploy::

    cd /tmp/client_market_planner
    docker compose build
    docker compose --profile market_planner up -d

Always includes ``core``, ``shared``, root composition files, and matching migration
branches. Unpaid product packages and their migration dirs are omitted entirely —
the build machine never sees that code.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from filter_shipped_products import PRODUCT_PATHS  # type: ignore  # same directory

ROOT_FILES = (
    "Dockerfile",
    "alembic.ini",
    "celery_app.py",
    "docker-compose.yml",
    "entrypoint.sh",
    "main.py",
    "migrate.py",
    "product_catalog.py",
    "requirements.txt",
    "wait-for-db.sh",
    "env_example",
)

ROOT_DIRS = (
    "core",
    "shared",
    "scripts",
    "static",
    "nginx",
)

# Shared Alembic history (not product-specific).
ALWAYS_MIGRATION_PATHS = (
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/version_paths.py",
    "migrations/versions",  # shared history files live directly here if any
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".mypy_cache",
            "*.egg-info",
            ".DS_Store",
        ),
    )


def export_tree(products: list[str], out: Path) -> None:
    root = _repo_root()
    wanted = {"core", *products}
    unknown = set(products) - set(PRODUCT_PATHS)
    if unknown:
        raise SystemExit(
            f"Unknown product(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(PRODUCT_PATHS))}"
        )

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ROOT_FILES:
        src = root / name
        if src.is_file():
            _copy_file(src, out / name)

    for name in ROOT_DIRS:
        src = root / name
        if src.is_dir():
            _copy_tree(src, out / name)

    # migrations package skeleton + core branch + selected product branches
    (out / "migrations").mkdir(parents=True, exist_ok=True)
    (out / "migrations" / "versions").mkdir(parents=True, exist_ok=True)

    for rel in (
        "migrations/env.py",
        "migrations/script.py.mako",
        "migrations/version_paths.py",
    ):
        src = root / rel
        if src.is_file():
            _copy_file(src, out / rel)

    # Any loose files under migrations/versions (shared history)
    versions = root / "migrations" / "versions"
    if versions.is_dir():
        for item in versions.iterdir():
            if item.is_file():
                _copy_file(item, out / "migrations" / "versions" / item.name)

    _copy_tree(root / "migrations" / "versions" / "core", out / "migrations" / "versions" / "core")

    (out / "products").mkdir(parents=True, exist_ok=True)
    for name in products:
        for rel in PRODUCT_PATHS[name]:
            src = root / rel
            if not src.exists():
                raise SystemExit(f"Missing required path for {name}: {rel}")
            dest = out / rel
            if src.is_dir():
                _copy_tree(src, dest)
            else:
                _copy_file(src, dest)

    # Rewrite alembic.ini / leave runtime discovery — also stamp INSTALL hint.
    readme = out / "CLIENT_TREE.txt"
    readme.write_text(
        "\n".join(
            [
                "Client source tree (subset).",
                f"Products: {', '.join(sorted(wanted))}",
                "",
                "Build & deploy:",
                "  docker compose build",
                f"  docker compose --profile {' '.join(products) if len(products) == 1 else 'all'} up -d",
                "",
                "Do not bind-mount a full monorepo over /app or unpaid code will reappear.",
                "First install uses products present on disk (see product_catalog / migrate.py).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Exported {out} with products: {', '.join(sorted(wanted))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--products",
        required=True,
        help="Comma-separated optional products, e.g. market_planner or "
        "market_planner,telephone_agent",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Destination directory (created/replaced).",
    )
    args = parser.parse_args(argv)
    products = [p.strip() for p in args.products.split(",") if p.strip()]
    if not products:
        raise SystemExit("Pass at least one product in --products")
    export_tree(products, Path(args.out).expanduser().resolve())
    return 0


if __name__ == "__main__":
    # Allow `python scripts/export_client_tree.py` without installing as a package.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
