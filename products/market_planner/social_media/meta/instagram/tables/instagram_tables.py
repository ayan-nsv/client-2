import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from shared.database.postgres.database_config import Base


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True)
    company = relationship("Company", backref=backref("instagram_accounts", cascade="all"))
    instagram_posts = relationship(
        "InstagramPost",
        back_populates="instagram_account",
        cascade="all",
    )
    facebook_insta_posts = relationship(
        "FacebookInstaPost",
        back_populates="instagram_account",
        cascade="all",
    )

    ig_user_id = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    account_type = Column(String(255), nullable=False, default="instagram_business_account")

    media_count = Column(Integer, nullable=False, default=0)
    profile_picture_url = Column(Text, nullable=True)

    facebook_insta_page_id = Column(
        Integer,
        ForeignKey("market_planner.facebook_insta_pages.id", ondelete="CASCADE"),
        nullable=True,
    )
    facebook_insta_page = relationship("FacebookInstaPage", back_populates="instagram_accounts")
    facebook_page_name = Column(String(255), nullable=True)

    access_token = Column(Text, nullable=True)
    token_type = Column(String(255), nullable=True)
    expires_in = Column(Integer, nullable=True)

    status = Column(String(20), nullable=False, default="ok")
    connected_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<InstagramAccount(id={self.id}, company_id='{self.company_id}')>"


class InstagramPost(Base):
    __tablename__ = "instagram_posts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True)
    company = relationship("Company", backref=backref("instagram_posts", cascade="all"))

    instagram_account_id = Column(
        Integer,
        ForeignKey("market_planner.instagram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instagram_account = relationship("InstagramAccount", back_populates="instagram_posts")

    caption = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)

    media_id = Column(Text, nullable=True)
    platform_post_id = Column(Text, nullable=True)
    status = Column(String(20), default="draft")
    platform_response = Column(JSONB, nullable=True)

    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<InstagramPost(id={self.id}, instagram_account_id='{self.instagram_account_id}')>"
