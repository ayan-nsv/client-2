"""Ensure core reference data (roles, features, installed products) exists on startup."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.repository.product_repo import InstalledProductRepository
from core.tables import company_tables
from core.tables.user_tables import Role
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

# IDs must stay aligned with shared/utils/constants/roles.py and API defaults (role_id=1 → member).
DEFAULT_ROLES = (
    (1, "member"),
    (2, "admin"),
    (3, "manager"),
)

# Feature rows are derived entirely from the installed products (see
# _ensure_catalog_features). core names no product: the pinned `(1, "market_planner")`
# entry that used to live here existed only to keep an id stable for databases built
# before the migration history was rewritten, and no code depends on that id — the
# API takes whatever feature_id the registry assigned.


def ensure_reference_data(db: Session) -> None:
    _ensure_roles(db)
    _ensure_features(db)
    _backfill_company_features(db)
    sync_installed_products(db)


def sync_installed_products(db: Session) -> None:
    """Reconcile core.installed_products with the versions the code declares.

    Updates only. Installation is the installer's job (``migrate.py``), because only
    it knows which products' schemas and tables were actually created. If this
    inserted rows for everything in the catalogue, a telephone-only deployment would
    mark market_planner installed the first time the app booted, and then try to load
    routes against tables that do not exist.

    Three cases:

    1. In the catalogue, not in the table  -> not installed here. Left alone, logged
       at debug level. Use ``migrate.py --install <product>`` to add it.
    2. In both, versions differ            -> UPDATE installed_version only. `enabled`
       is never written here: a product an operator switched off must not come back
       on because someone deployed.
    3. In the table, not in the catalogue  -> leave it and warn. The row is the record
       of what was once installed; deleting it would lose that.
    """
    # Imported here rather than at module scope: product_catalog imports every
    # product's module.py, and core must not pull products in at import time.
    from product_catalog import get_catalog

    repo = InstalledProductRepository(db)
    changed = False

    catalog = get_catalog()
    known_names = set()

    for descriptor in catalog:
        known_names.add(descriptor.name)
        row = repo.get_by_name(descriptor.name)

        if row is None:
            # Shipped in this build but not installed on this deployment.
            logger.debug(
                "Product %s is available but not installed here; "
                "run `migrate.py --install %s` to add it.",
                descriptor.name,
                descriptor.name,
            )
            continue

        if row.installed_version != descriptor.version or row.schema_name != descriptor.schema:
            logger.info(
                "Product %s version %s -> %s",
                descriptor.name,
                row.installed_version,
                descriptor.version,
            )
            repo.update_version(row, descriptor.version, descriptor.schema)
            changed = True

    for row in repo.list_installed():
        if row.product_name not in known_names:
            logger.warning(
                "Product %s is recorded as installed (version %s) but this build does "
                "not ship it; leaving the row untouched.",
                row.product_name,
                row.installed_version,
            )

    if changed:
        db.commit()


def _ensure_roles(db: Session) -> None:
    changed = False
    for role_id, name in DEFAULT_ROLES:
        existing = db.query(Role).filter(Role.id == role_id).first()
        if existing:
            if existing.name != name:
                logger.warning(
                    "Role id=%s has name %r, expected %r",
                    role_id,
                    existing.name,
                    name,
                )
            continue

        if db.query(Role).filter(Role.name == name).first():
            continue

        db.add(Role(id=role_id, name=name))
        changed = True

    if changed:
        db.commit()
        db.execute(
            text(
                "SELECT setval("
                "pg_get_serial_sequence('core.roles', 'id'), "
                "COALESCE((SELECT MAX(id) FROM core.roles), 1)"
                ")"
            )
        )
        db.commit()


def _ensure_features(db: Session) -> None:
    _ensure_catalog_features(db)


def _ensure_catalog_features(db: Session) -> None:
    """Give every optional product a tenant-level feature row.

    Without this, core.features holds only the one id-pinned entry above, so
    company_features can never express "telephone_agent is off for this customer".
    Runs after the block above so the id sequence has already been fixed up — these
    rows take autoincrement ids rather than pinned ones.

    Scoped to products actually installed here: a telephone-only deployment has no
    use for a market_planner feature flag, and offering one would imply the product
    could be switched on when its tables do not exist.

    core is skipped: it is not optional, so there is nothing to switch per tenant.
    """
    from product_catalog import get_catalog

    installed = {row.product_name for row in InstalledProductRepository(db).list_installed()}

    changed = False
    for descriptor in get_catalog():
        if descriptor.required or descriptor.name not in installed:
            continue

        exists = (
            db.query(company_tables.Feature)
            .filter(company_tables.Feature.name == descriptor.name)
            .first()
        )
        if exists:
            continue

        db.add(company_tables.Feature(name=descriptor.name))
        changed = True
        logger.info("Added feature row for product %s", descriptor.name)

    if changed:
        db.commit()


def _backfill_company_features(db: Session) -> None:
    features = db.query(company_tables.Feature).all()
    if not features:
        return

    companies = db.query(company_tables.Company).all()
    to_add = []

    for company in companies:
        existing_feature_ids = {
            row.feature_id
            for row in db.query(company_tables.CompanyFeature)
            .filter(company_tables.CompanyFeature.company_id == company.id)
            .all()
        }
        for feature in features:
            if feature.id not in existing_feature_ids:
                to_add.append(
                    company_tables.CompanyFeature(
                        company_id=company.id,
                        feature_id=feature.id,
                        enabled=True,
                    )
                )

    if to_add:
        db.add_all(to_add)
        db.commit()
