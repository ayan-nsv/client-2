import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from shared.database.postgres.database_config import Base


class LinkedinAccount(Base):
    __tablename__ = "linkedin_accounts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True)
    company = relationship(
        "Company",
        backref=backref("linkedin_accounts", cascade="all"),
    )
    linkedin_pages = relationship(
        "LinkedinPage",
        back_populates="linkedin_account",
        cascade="all",
    )
    linkedin_posts = relationship(
        "LinkedinPost",
        back_populates="linkedin_account",
        cascade="all",
    )
    account_type = Column(String(255), nullable=False)

    linkedin_id = Column(Text)
    author_urn = Column(Text)
    display_name = Column(Text)
    profile_image_url = Column(Text)

    access_token = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    status = Column(String(20), default="ok")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<LinkedinAccount(id={self.id}, company_id='{self.company_id}')>"


class LinkedinPage(Base):
    __tablename__ = "linkedin_pages"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    linkedin_account_id = Column(
        Integer,
        ForeignKey("market_planner.linkedin_accounts.id", ondelete="CASCADE"),
        index=False,
    )
    linkedin_account = relationship(
        "LinkedinAccount",
        back_populates="linkedin_pages",
    )
    linkedin_id = Column(String(255), nullable=True)
    author_urn = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    profile_image_url = Column(Text, nullable=True)

    is_selected = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<LinkedinPage(id={self.id}, linkedin_account_id='{self.linkedin_account_id}')>"


class LinkedinPost(Base):
    __tablename__ = "linkedin_posts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)

    company_id = Column(Integer, ForeignKey("core.companies.id", ondelete="CASCADE"), nullable=False, index=True)
    company = relationship(
        "Company",
        backref=backref("linkedin_posts", cascade="all"),
    )

    linkedin_account_id = Column(
        Integer,
        ForeignKey("market_planner.linkedin_accounts.id", ondelete="CASCADE"),
        index=False,
    )
    linkedin_account = relationship(
        "LinkedinAccount",
        back_populates="linkedin_posts",
    )

    caption = Column(Text, nullable=True)
    media_urls = Column(ARRAY(Text), nullable=True)

    target_urn = Column(String(255), nullable=False)
    linkedin_share_id = Column(Text, nullable=True)

    status = Column(String(20), default="posted")
    posted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<LinkedinPost(id={self.id}, linkedin_account_id='{self.linkedin_account_id}')>"
