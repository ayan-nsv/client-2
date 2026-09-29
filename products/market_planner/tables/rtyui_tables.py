"""SQLAlchemy models for the database."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.sql import func
import uuid
from sqlalchemy.dialects.postgresql import UUID
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship


class ProductCategory(Base):
    """ProductCategory table model for independent category management."""
    
    __tablename__ = "product_categories"
    __table_args__ = {"schema": "market_planner"}
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
        index=True
    )

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    name = Column(String, nullable=False, index=True)

    # Relationships
    company = relationship("Company", backref=backref("categories", cascade="all"))
    products = relationship("ScrapedProducts", back_populates="product_category")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name})>"


class ScrapedProducts(Base):
    """ScrapedProducts table model."""
    
    __tablename__ = "scraped_products"
    __table_args__ = {"schema": "market_planner"}
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
        index=True
    )

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Many-to-one
    company = relationship(
        "Company",
        backref=backref("scraped_products", cascade="all")
    )

    category = Column(String, nullable=True, index=True)
    
    category_id = Column(
        Integer,
        ForeignKey("market_planner.product_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Relationship to normalized categories
    product_category = relationship(
        "ProductCategory",
        back_populates="products"
    )
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    short_description = Column(Text, nullable=True)
    price = Column(String, nullable=True)
    source_url = Column(String, nullable=True, index=True)
    is_product = Column(Boolean, default=True)

    # Array of maps stored as JSONB
    features = Column(ARRAY(JSONB), nullable=True)

    # Array of image URLs
    images = Column(ARRAY(String), nullable=True) 

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    def __repr__(self):
        return f"<Product(id={self.id}, title={self.title})>"

