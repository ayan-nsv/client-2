import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from shared.database.postgres.database_config import Base


class TikTokAccount(Base):
    __tablename__ = "tiktok_accounts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company = relationship("Company", backref=backref("tiktok_accounts", cascade="all"))

    tiktok_posts = relationship(
        "TikTokPost",
        back_populates="tiktok_account",
        cascade="all",
    )
    open_id = Column(String(255), nullable=True)

    access_token = Column(Text, nullable=True)
    token_type = Column(String(255), nullable=True)
    access_expires_in = Column(Integer, nullable=True)

    refresh_token = Column(Text, nullable=True)
    refresh_expires_in = Column(Integer, nullable=True)

    status = Column(String(20), default="active")
    scope = Column(String(255), nullable=True)
    connected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<TikTokAccount(id={self.id}, company_id='{self.company_id}')>"


class TikTokPost(Base):
    __tablename__ = "tiktok_posts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company = relationship("Company", backref=backref("tiktok_posts", cascade="all"))

    tiktok_account_id = Column(
        Integer,
        ForeignKey("market_planner.tiktok_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tiktok_account = relationship("TikTokAccount", back_populates="tiktok_posts")

    publish_id = Column(Text, nullable=True)
    upload_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<TikTokPost(id={self.id}, tiktok_account_id='{self.tiktok_account_id}')>"
