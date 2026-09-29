import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ARRAY,
    Boolean,
    ForeignKey,
    text,
)

from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship


class Post(Base):
    __tablename__ = "posts"
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

    caption = Column(Text, nullable=True)
    channel = Column(String(50), nullable=True)

    company_id = Column(
            Integer,
            ForeignKey("core.companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        )

    # Many-to-one
    company = relationship(
        "Company",
        backref=backref("posts", cascade="all")
    )

    image_url = Column(Text, nullable=True)
    overlay_text = Column(Text, nullable=True)

    hashtags = Column(ARRAY(Text), nullable=True)

    month_id = Column(Integer, nullable=True)
    scheduled_month = Column(Integer, nullable=True)

    scheduled_datetime = Column(DateTime(timezone=True), nullable=True)

    status = Column(String(20), default="draft")

    theme_index = Column(Integer, nullable=True)
    variation_index = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class ImageConfig(Base):
    __tablename__ = "image_config"
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

    # One-to-one
    company = relationship(
        "Company",
        backref=backref("image_config", uselist=False, cascade="all"),
        uselist=False,
        cascade="all"
    )

    image_type = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<ImageConfig(id={self.id}, company_id='{self.company_id}')>"
