import uuid
from sqlalchemy import (
    Column, 
    String, 
    Boolean, 
    Integer, 
    DateTime, 
    ForeignKey, 
    Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship


class TelegramChat(Base):
    __tablename__ = "telegram_chats"
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

    telegram_chat_id = Column(
        String(255),
        unique=True,
        index=True,
        nullable=True # Nullable for now to allow migration of existing rows
    )
    
    first_name = Column(
        String(255),
        nullable=True
    )
    username = Column(
        String(255),
        nullable=True
    )

    user_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Many-to-one
    user = relationship(
        "User",
        backref=backref("telegram_chats", cascade="all")
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
        backref=backref("telegram_chats", cascade="all")
    )

    # One-to-many
    pending_approvals = relationship(
        "TelegramPendingApproval",
        back_populates="chat",
        cascade="all"
    )

    # One-to-many
    theme_selections = relationship(
        "TelegramThemeSelection",
        back_populates="chat",
        cascade="all"
    )

    connected_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):  
        return f"<TelegramChat(id={self.id}, user_id='{self.user_id}', company_id='{self.company_id}')>"



class TelegramPendingApproval(Base):
    __tablename__ = "telegram_pending_approvals"
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

    chat_id = Column(
        Integer,
        ForeignKey("market_planner.telegram_chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Many-to-one
    chat = relationship(
        "TelegramChat",
        back_populates="pending_approvals"
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
        backref=backref("telegram_pending_approvals", cascade="all")
    )


    # Not a foreign key, just a integer
    message_id = Column(
        Integer,
        nullable=True
    )

    # Not a foreign key, just a string
    post_id = Column(
        String(255),
        nullable=True
    )

    caption = Column(
        Text,
        nullable=True
    )

    status = Column(
        String(20),
        nullable=True
    )

    image_url = Column(
        Text,
        nullable=True
    )

    responded_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):  
        return f"<TelegramPendingApproval(id={self.id}, chat_id='{self.chat_id}', company_id='{self.company_id}')>"


class TelegramThemeSelection(Base):
    __tablename__ = "telegram_theme_selections"
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

    chat_id = Column(
        Integer,
        ForeignKey("market_planner.telegram_chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Many-to-one
    chat = relationship(
        "TelegramChat",
        back_populates="theme_selections"
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
        backref=backref("telegram_theme_selections", cascade="all")
    )
    
    # Not a foreign key, just a integer
    message_id = Column(
        Integer,
        nullable=True
    )

    # Not a foreign key, just a string
    post_id = Column(
        String(255),
        nullable=True
    )

    selected_theme = Column(
        Integer,
        nullable=True
    )

    selected_theme_title = Column(
        String(255),
        nullable=True
    )

    status = Column(
        String(20),
        nullable=True,
        index=True
    )

    data = Column(
        JSONB,
        nullable=True
    )

    responded_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):  
        return f"<TelegramThemeSelection(id={self.id}, chat_id='{self.chat_id}', company_id='{self.company_id}')>"
