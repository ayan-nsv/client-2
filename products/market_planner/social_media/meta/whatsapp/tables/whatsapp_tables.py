"""
WhatsApp channel tables – compatible with existing Company/Theme/Post structure.
We do NOT store message/reply content. Only: per-company config + theme/post
deliveries; Celery (or webhook) updates delivery status (answered/pending,
approved/needs_changes) when replies are matched — no message log table.
"""
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship


class WhatsAppAccount(Base):
    """
    Per-company WhatsApp configuration (e.g. Twilio number, provider credentials).
    One row per company; used when sending themes/posts via WhatsApp.
    """
    __tablename__ = "whatsapp_accounts"

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
        index=True,
    )
    company = relationship(
        "Company",
        backref=backref("whatsapp_accounts", cascade="all"),
    )

    # E.164 or app-specific format
    phone_number = Column(String(32), nullable=False, index=True)
    # e.g. "twilio"
    # provider = Column(String(50), nullable=True, server_default="twilio")
    # # Optional: store provider SID / from number (secrets should live in env in production)
    # provider_from_number = Column(String(32), nullable=True)
    # is_active = Column(Boolean, nullable=False, server_default="true")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<WhatsAppAccount(id={self.id}, company_id={self.company_id}, phone={self.phone_number})>"


class WhatsAppThemeDelivery(Base):
    """
    Record of a theme sent via WhatsApp for selection (option 1 or 2).
    Links to Theme; stores delivery status and user's selected option.
    """
    __tablename__ = "whatsapp_theme_deliveries"

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
        index=True,
    )
    company = relationship(
        "Company",
        backref=backref("whatsapp_theme_deliveries", cascade="all"),
    )

    theme_id = Column(
        Integer,
        ForeignKey("market_planner.themes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    theme = relationship("Theme", foreign_keys=[theme_id])

    recipient_phone = Column(String(32), nullable=True, index=True)
    # Token in message body e.g. tp_abc123 — for Celery/webhook to match replies
    message_token = Column(String(64), nullable=True, unique=True, index=True)
    twilio_message_sid = Column(String(64), nullable=True, index=True)
    # pending | answered | superseded
    status = Column(String(20), nullable=False, index=True, server_default="pending")

    month = Column(String(32), nullable=True)  # e.g. month name or id
    option1_title = Column(String(255), nullable=True)
    option1_desc = Column(Text, nullable=True)
    option2_title = Column(String(255), nullable=True)
    option2_desc = Column(Text, nullable=True)
    selected_option = Column(String(10), nullable=True)  # "1" or "2"
    selected_option_title = Column(String(255), nullable=True)
    selected_option_desc = Column(Text, nullable=True)

    # Timestamps: created_at = when sent; updated_at = when status last changed (e.g. when answered/superseded)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<WhatsAppThemeDelivery(id={self.id}, theme_id={self.theme_id}, status={self.status})>"


class WhatsAppPostDelivery(Base):
    """
    Record of a post sent via WhatsApp for approval (ja/nej).
    Links to Post; stores delivery status and approval/rejection.
    """
    __tablename__ = "whatsapp_post_deliveries"

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
        index=True,
    )
    company = relationship(
        "Company",
        backref=backref("whatsapp_post_deliveries", cascade="all"),
    )

    post_id = Column(
        Integer,
        ForeignKey("market_planner.posts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    post = relationship("Post", foreign_keys=[post_id])

    recipient_phone = Column(String(32), nullable=True, index=True)
    # Token in message body e.g. post_xyz — for Celery/webhook to match replies
    message_token = Column(String(64), nullable=True, unique=True, index=True)
    twilio_message_sid = Column(String(64), nullable=True, index=True)
    # sent | approved | needs_changes (Celery updates only status, no reply content stored)
    status = Column(String(20), nullable=False, index=True, server_default="sent")

    # Timestamps: created_at = when sent; updated_at = when status last changed (e.g. when approved/needs_changes)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<WhatsAppPostDelivery(id={self.id}, post_id={self.post_id}, status={self.status})>"
