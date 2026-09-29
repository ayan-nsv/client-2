import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship, validates
from products.knowledge.rag.services import chatbot_validation

class ChatBot(Base):
    __tablename__ = "chat_bots"
    __table_args__ = {"schema": "knowledge"}
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
        ForeignKey("core.companies.id", ondelete="SET NULL"),
        index=True
    )
    company = relationship("Company")
    
    lead_fields = relationship(
        "ChatbotLeadFields",
        back_populates="chatbot",
        cascade="all"
    )
    
    leads = relationship(
        "ChatbotLeads",
        back_populates="chatbot",
        cascade="all"
    )
    
    conversations = relationship(
        "ChatbotConversations",
        back_populates="chatbot",
        cascade="all"
    )

    name = Column(String(50), nullable=False)
    
    is_enabled = Column(Boolean, nullable=True, default=True)
    
    greeting_message = Column(Text, nullable=True)

    primary_color = Column(String(7), nullable=True)
    
    lead_collection_enabled = Column(Boolean, nullable=True, default=True)
    
    lead_recipient_email = Column(String(255), nullable=True)

    created_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    script = Column(Text, nullable=False)

    created_by = relationship(
        "User",
        foreign_keys=[created_by_id],
        backref=backref("chat_bots", foreign_keys="ChatBot.created_by_id"),
    )
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    @validates("primary_color")
    def _validate_primary_color(self, _key: str, value: str | None) -> str | None:
        return chatbot_validation.validate_primary_color(value)
    
    def __str__(self):
        return f"ChatBot(id={self.id}, name='{self.name}', company_id={self.company_id})"
    
    
#ChatbotLeadFields:    
class ChatbotLeadFields(Base):
    __tablename__ = "chatbot_lead_fields"
    __table_args__ = {"schema": "knowledge"}
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
    
    chatbot_id = Column(
        Integer,
        ForeignKey("knowledge.chat_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    chatbot = relationship(
        "ChatBot",
        back_populates="lead_fields"
    )
    
    field_name = Column(String(50), nullable=False)
    
    is_required = Column(Boolean, nullable=True, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    def __str__(self):
        return f"ChatbotLeadFields(id={self.id}, field_name='{self.field_name}', is_required={self.is_required})"
    
#Chatbot conversations:
class ChatbotConversations(Base):
    __tablename__ = "chatbot_conversations"
    __table_args__ = {"schema": "knowledge"}
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
    
    # chatbot
    chatbot_id = Column(
        Integer,
        ForeignKey("knowledge.chat_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    chatbot = relationship(
        "ChatBot",
        back_populates="conversations"
    )
    
    messages = relationship(
        "ChatbotMessages",
        back_populates="conversation",
        cascade="all"
    )
    
    leads = relationship(
        "ChatbotLeads",
        back_populates="conversation",
        cascade="all"
    )
    
    visitor_email = Column(String(255), nullable=True)
    website_url = Column(String(2048), nullable=True)

    ended_at = Column(DateTime(timezone=True))
    lead_created = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    @validates("visitor_email")
    def _validate_visitor_email(
        self, _key: str, value: str | None
    ) -> str | None:
        return chatbot_validation.validate_visitor_email(value)

    @validates("website_url")
    def _validate_website_url(self, _key: str, value: str | None) -> str | None:
        return chatbot_validation.validate_website_url(value)

    def __str__(self):
        return f"ChatbotConversations(id={self.id}, chatbot_id={self.chatbot_id})"
    
# Chatbot messages:
class ChatbotMessages(Base):
    __tablename__ = "chatbot_messages"
    __table_args__ = {"schema": "knowledge"}
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
    
    conversation_id = Column(
        Integer,
        ForeignKey("knowledge.chatbot_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    conversation = relationship(
        "ChatbotConversations",
        back_populates="messages"
    )
    
    sender = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    @validates("sender")
    def _validate_sender(self, _key: str, value: str) -> str:
        return chatbot_validation.validate_message_sender(value)

    def __str__(self):
        return f"ChatbotMessages(id={self.id}, conversation_id={self.conversation_id})"    
    
# Chatbot leads:
class ChatbotLeads(Base):
    __tablename__ = "chatbot_leads"
    __table_args__ = {"schema": "knowledge"}
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
    
    
    # chatbot
    chatbot_id = Column(
        Integer,
        ForeignKey("knowledge.chat_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    chatbot = relationship(
        "ChatBot",
        back_populates="leads"
    )
    
    conversation_id = Column(
        Integer,
        ForeignKey("knowledge.chatbot_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    conversation = relationship(
        "ChatbotConversations",
        back_populates="leads"
    )
    
    ai_summary = Column(Text)
    transcript = Column(Text)
    email_sent = Column(Boolean, default=False)
    status = Column(String(50), nullable=True, default="new")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    @validates("status")
    def _validate_status(self, _key: str, value: str | None) -> str | None:
        return chatbot_validation.validate_lead_status(value)

    def __str__(self):
        return f"ChatbotLeads(id={self.id}, chatbot_id={self.chatbot_id})"