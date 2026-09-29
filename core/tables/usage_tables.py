import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ARRAY,
    ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Date

class UsageMetric(Base):
    __tablename__ = "usage_metrics"
    __table_args__ = {"schema": "core"}
    id = Column(Integer, primary_key=True)

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    user_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )

    # Many-to-one relationships
    company = relationship(
        "Company",
        back_populates="usage_metrics"
    )

    user = relationship(
        "User",
        back_populates="usage_metrics"
    )

    date = Column(
        Date,
        index=True,
        nullable=False
    )

    feature = Column(
        String,  # "image_generation", "theme_generation", "caption_generation"
        index=True,
        nullable=False
    )

    channel = Column(
        String,  # "instagram", "facebook", "linkedin"
        index=True,
        nullable=True
    )

    action = Column(
        String,  # "generate", "regenerate"
        index=True,
        nullable=False
    )

    count = Column(
        Integer,
        nullable=False,
        default=1
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
