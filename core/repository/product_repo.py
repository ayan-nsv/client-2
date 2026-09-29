from sqlalchemy.orm import Session

from core.tables import product_tables
from shared.database.postgres import serialization
from shared.utils.error import error


class InstalledProductRepository:
    """Data access for core.installed_products (deployment-level, not per-company)."""

    def __init__(self, db: Session):
        self.db = db

    def list_installed(self):
        return (
            self.db.query(product_tables.InstalledProduct)
            .order_by(product_tables.InstalledProduct.product_name)
            .all()
        )

    def list_installed_dicts(self):
        return [serialization.sqlalchemy_to_dict(row) for row in self.list_installed()]

    def get_by_name(self, product_name: str):
        return (
            self.db.query(product_tables.InstalledProduct)
            .filter(product_tables.InstalledProduct.product_name == product_name)
            .first()
        )

    def get_enabled_names(self) -> set[str]:
        """Product names currently switched on. Used to decide what to load/start."""
        rows = (
            self.db.query(product_tables.InstalledProduct.product_name)
            .filter(product_tables.InstalledProduct.enabled.is_(True))
            .all()
        )
        return {row[0] for row in rows}

    def create(self, product_name: str, installed_version: str, schema_name: str | None,
               enabled: bool = True):
        row = product_tables.InstalledProduct(
            product_name=product_name,
            installed_version=installed_version,
            schema_name=schema_name,
            enabled=enabled,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update_version(self, row, installed_version: str, schema_name: str | None = None):
        """Record a new code version. Deliberately does not touch `enabled`."""
        row.installed_version = installed_version
        if schema_name is not None:
            row.schema_name = schema_name
        self.db.flush()
        return row

    def set_enabled(self, product_name: str, enabled: bool):
        try:
            row = self.get_by_name(product_name)
            if row is None:
                raise error.NotFound(f"Product '{product_name}' is not installed")

            row.enabled = enabled
            self.db.commit()
            self.db.refresh(row)

            return serialization.sqlalchemy_to_dict(row)

        except Exception:
            self.db.rollback()
            raise
