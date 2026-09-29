import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship


class ChannelConfig(Base):
    __tablename__ = "channel_config"
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
        unique=True,
        index=True
    )

    # Relationship
    company = relationship(
        "Company",
        backref=backref("channel_config", uselist=False, cascade="all")
    )

    blog_post_active = Column(Boolean, nullable=False, default=False)
    blog_post_count = Column(Integer, nullable=False, default=1)

    email_campaign_active = Column(Boolean, nullable=False, default=False)
    email_campaign_count = Column(Integer, nullable=False, default=1)

    facebook_active = Column(Boolean, nullable=False, default=False)
    facebook_post_count = Column(Integer, nullable=False, default=1)

    instagram_active = Column(Boolean, nullable=False, default=False)
    instagram_post_count = Column(Integer, nullable=False, default=1)

    linkedin_active = Column(Boolean, nullable=False, default=False)
    linkedin_post_count = Column(Integer, nullable=False, default=1)

    tiktok_active = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self): 
        return f"<ChannelConfig(id={self.id}, company_id='{self.company_id}')>"