from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Text, DateTime, func, text
from sqlalchemy.orm import backref, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from shared.database.postgres.database_config import Base

## facebook instagram tables

class FacebookInstaAccount(Base):
    __tablename__ = "facebook_insta_accounts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    company = relationship("Company", backref=backref("facebook_insta_accounts", cascade="all"))
    facebook_insta_pages = relationship(
        "FacebookInstaPage",
        back_populates="facebook_insta_account",
        cascade="all"
    )
    facebook_insta_posts = relationship(
        "FacebookInstaPost",
        back_populates="facebook_insta_account",
        cascade="all"
    )

    fb_user_id = Column(String(255), nullable=True)
    user_long_token = Column(Text, nullable=True)
    flow_type = Column(String(255),nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    def __repr__(self):
        return f"<FacebookInstaAccount(id={self.id}, company_id='{self.company_id}')>"
   
class FacebookInstaPage(Base):
    __tablename__ = "facebook_insta_pages"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    facebook_insta_account_id = Column(Integer, ForeignKey("market_planner.facebook_insta_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    facebook_insta_account = relationship("FacebookInstaAccount", back_populates="facebook_insta_pages")
    instagram_accounts = relationship(
        "InstagramAccount",
        back_populates="facebook_insta_page",
        cascade="all,delete-orphan"
    )
    facebook_insta_posts = relationship(
        "FacebookInstaPost",
        back_populates="page",
        cascade="all,delete-orphan"
    )

    page_id = Column(String(255), index=True)
    page_name = Column(String(255), nullable=True)
    page_access_token = Column(Text, nullable=True)
    page_profile_picture_url = Column(Text, nullable=True)
    instagram_connected = Column(Boolean, default=False)
    is_selected = Column(Boolean, default=False, server_default=text('false'))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    def __repr__(self):
        return f"<FacebookInstaPage(id={self.id}, facebook_insta_account_id='{self.facebook_insta_account_id}')>"

class FacebookInstaPost(Base):
    __tablename__ = "facebook_insta_posts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True)
    company = relationship("Company", backref=backref("facebook_insta_posts", cascade="all"))

    facebook_insta_account_id = Column(Integer, ForeignKey("market_planner.facebook_insta_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    facebook_insta_account = relationship("FacebookInstaAccount", back_populates="facebook_insta_posts")
    
    message = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)

    target = Column(String(255), nullable=True)
  
    facebook_page_id = Column(Integer, ForeignKey("market_planner.facebook_insta_pages.id", ondelete="CASCADE"), nullable=True, index=True)
    page = relationship(
        "FacebookInstaPage",
        back_populates="facebook_insta_posts",
        foreign_keys=[facebook_page_id],
    )


    instagram_account_id = Column(Integer, ForeignKey("market_planner.instagram_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    instagram_account = relationship("InstagramAccount", back_populates="facebook_insta_posts")

    platform_post_id = Column(Text, index=True)
    status = Column (String(20), default="draft")
    platform_response = Column(JSONB, nullable=True)

    posted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    def __repr__(self):
        return f"<FacebookInstaPost(id={self.id}, facebook_page_id='{self.facebook_page_id}', instagram_account_id='{self.instagram_account_id}')>"
