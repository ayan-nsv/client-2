"""Deployment-level record of which products are installed, and at what version.

This is not a per-company table. The architecture gives each customer their own
Postgres, so a row here describes the *deployment*: "this product's code and schema
are installed on this database at version X". The installer/upgrader reads it to
decide which migrations to run and which services to start.

Deliberately distinct from ``core.company_features``, which answers a different
question — whether a tenant has a feature switched on. Keep the two apart:

    core.installed_products  -> is the product installed here at all (no company_id)
    core.company_features    -> is it enabled for company N

No ``relationship()`` to Company on purpose. Wiring this into ``core.Company`` would
repeat the coupling that already forces core to change on every product release.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
)
from sqlalchemy.sql import func
import uuid
from sqlalchemy.dialects.postgresql import UUID
from shared.database.postgres.database_config import Base


class InstalledProduct(Base):
    __tablename__ = "installed_products"
    __table_args__ = {"schema": "core"}

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    uuid = Column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
        unique=True,
        index=True,
    )

    # Matches PRODUCT_NAME in the product's module.py. Unique: one row per product.
    product_name = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    # The PRODUCT_VERSION the code declared the last time startup sync ran.
    installed_version = Column(
        String(50),
        nullable=False,
    )

    # Operator-controlled. Startup sync never writes this, so a product that was
    # deliberately turned off does not silently come back on the next deploy.
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Set once, when the product first appears. Upgrades move updated_at, not this.
    install_date = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # The PostgreSQL schema this product owns, e.g. "market_planner".
    schema_name = Column(
        String(63),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return (
            f"<InstalledProduct(product_name={self.product_name!r}, "
            f"installed_version={self.installed_version!r}, enabled={self.enabled})>"
        )
