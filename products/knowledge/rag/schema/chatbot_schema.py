"""
    Pydantic schemas for the chatbot feature.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from products.knowledge.rag.services.chatbot_validation import (
    ALLOWED_LEAD_STATUSES,
    ALLOWED_MESSAGE_SENDERS,
    DEFAULT_CHATBOT_PRIMARY_COLOR,
    validate_lead_status,
    validate_message_sender,
    validate_primary_color,
    validate_visitor_email,
    validate_website_url,
)

MessageSender = str
LeadStatus = str


# ChatBot

class ChatBotCreate(BaseModel):
    """Payload for creating a chatbot. company_id is the company UUID."""

    company_id: str = Field(..., description="Company UUID")
    name: str = Field(..., max_length=50, description="Chatbot display name")
    is_enabled: bool = True
    greeting_message: Optional[str] = None
    primary_color: Optional[str] = Field(
        default=DEFAULT_CHATBOT_PRIMARY_COLOR,
        description="Widget primary color as #RGB or #RRGGBB",
    )
    lead_collection_enabled: bool = True
    lead_recipient_email: Optional[EmailStr] = Field(
        default=None, description="Where new lead notifications are sent"
    )

    @field_validator("primary_color", mode="before")
    @classmethod
    def _normalize_primary_color(cls, value: Optional[str]) -> Optional[str]:
        return validate_primary_color(value)


class ChatBotUpdate(BaseModel):
    """Payload for updating a chatbot (all optional)."""

    name: Optional[str] = Field(default=None, max_length=50)
    is_enabled: Optional[bool] = None
    greeting_message: Optional[str] = None
    primary_color: Optional[str] = Field(
        default=None,
        description="Widget primary color as #RGB or #RRGGBB",
    )
    lead_collection_enabled: Optional[bool] = None
    lead_recipient_email: Optional[EmailStr] = None

    @field_validator("primary_color", mode="before")
    @classmethod
    def _normalize_primary_color(cls, value: Optional[str]) -> Optional[str]:
        return validate_primary_color(value)


class ChatBotItem(BaseModel):
    """Single chatbot in a response."""

    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    company_id: Optional[int] = None
    name: str
    is_enabled: Optional[bool] = None
    greeting_message: Optional[str] = None
    primary_color: Optional[str] = None
    lead_collection_enabled: Optional[bool] = None
    lead_recipient_email: Optional[str] = None
    script: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChatBotResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatBotItem] = None


class ChatBotListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: List[ChatBotItem] = Field(default_factory=list)


# ChatbotLeadFields

class ChatbotLeadFieldCreate(BaseModel):
    """Payload for adding a lead-collection field to a chatbot."""

    chatbot_uuid: UUID = Field(..., description="UUID of the parent chatbot")
    field_name: str = Field(..., max_length=50)
    is_required: bool = True


class ChatbotLeadFieldAddRequest(BaseModel):
    """Payload for adding a lead field; the chatbot UUID comes from the URL."""

    field_name: str = Field(..., max_length=50)
    is_required: bool = True


class ChatbotLeadFieldsBulkAddRequest(BaseModel):
    """Payload for adding multiple lead fields; the chatbot UUID comes from the URL."""

    fields: List[ChatbotLeadFieldAddRequest] = Field(
        ..., min_length=1, description="Lead fields to add"
    )


class ChatbotLeadFieldUpdate(BaseModel):
    field_name: Optional[str] = Field(default=None, max_length=50)
    is_required: Optional[bool] = None


class ChatbotLeadFieldItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    field_name: str
    is_required: Optional[bool] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChatbotLeadFieldResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotLeadFieldItem] = None


class ChatbotLeadFieldListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: List[ChatbotLeadFieldItem] = Field(default_factory=list)


# ChatBot settings (admin configuration view)

class ChatBotSettingsItem(BaseModel):
    """Full configuration of a chatbot, including its lead-collection fields."""

    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    # company_id: Optional[int] = None
    name: str
    is_enabled: Optional[bool] = None
    greeting_message: Optional[str] = None
    primary_color: Optional[str] = None
    lead_collection_enabled: Optional[bool] = None
    lead_recipient_email: Optional[str] = None
    script: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    lead_fields: List[ChatbotLeadFieldItem] = Field(default_factory=list)


class ChatBotSettingsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatBotSettingsItem] = None



# ChatbotConversations

class ChatbotConversationCreate(BaseModel):
    """Payload for starting a chatbot conversation."""

    chatbot_uuid: UUID = Field(..., description="UUID of the chatbot widget")
    visitor_email: Optional[str] = Field(
        default=None,
        description="Visitor email address, when the visitor chooses to provide it",
    )
    website_url: Optional[str] = Field(
        default=None,
        description="Page URL where the visitor started the chat (http/https)",
    )

    @field_validator("visitor_email", mode="before")
    @classmethod
    def _normalize_email(cls, value: Optional[str]) -> Optional[str]:
        return validate_visitor_email(value)

    @field_validator("website_url", mode="before")
    @classmethod
    def _normalize_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_website_url(value)


class ChatbotConversationStartRequest(BaseModel):
    """Payload for starting a conversation; the chatbot UUID comes from the URL."""

    email_id: Optional[str] = Field(
        default=None,
        description="Visitor email address, when the visitor chooses to provide it",
    )
    website_url: Optional[str] = Field(
        default=None,
        description="Page URL where the visitor started the chat (http/https)",
    )

    @field_validator("email_id", mode="before")
    @classmethod
    def _normalize_email(cls, value: Optional[str]) -> Optional[str]:
        return validate_visitor_email(value)

    @field_validator("website_url", mode="before")
    @classmethod
    def _normalize_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_website_url(value)


class ChatbotConversationUpdate(BaseModel):
    """Payload for updating a conversation (e.g. marking it ended)."""

    ended_at: Optional[datetime] = None
    lead_created: Optional[bool] = None


class ChatbotConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    visitor_email: Optional[str] = None
    website_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChatbotConversationResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotConversationItem] = None


class ChatbotConversationListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: List[ChatbotConversationItem] = Field(default_factory=list)


class ChatbotConversationCloseData(BaseModel):
    """Result of closing a conversation."""

    conversation_uuid: UUID
    ended_at: Optional[datetime] = None
    lead_created: bool = False
    captured_fields: dict = Field(default_factory=dict)
    lead: Optional["ChatbotLeadItem"] = None


class ChatbotConversationCloseResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotConversationCloseData] = None


# ChatbotMessages

class ChatbotMessageCreate(BaseModel):
    """Payload for appending a message to a conversation."""

    conversation_uuid: UUID = Field(..., description="UUID of the parent conversation")
    sender: MessageSender = Field(
        ..., description=f"One of: {', '.join(ALLOWED_MESSAGE_SENDERS)}"
    )
    message: str = Field(..., min_length=1)

    @field_validator("sender", mode="before")
    @classmethod
    def _normalize_sender(cls, value: str) -> str:
        return validate_message_sender(value)


class ChatbotMessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    sender: str
    message: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChatbotTextChatRequest(BaseModel):
    """Payload for a text-chat turn; the conversation UUID comes from the URL."""

    query: str = Field(..., min_length=1, description="Visitor's message text")


class ChatbotTextChatData(BaseModel):
    conversation_uuid: UUID
    answer: str
    visitor_message: ChatbotMessageItem
    bot_message: ChatbotMessageItem


class ChatbotTextChatResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotTextChatData] = None


class ChatbotMessageResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotMessageItem] = None


class ChatbotMessageListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: List[ChatbotMessageItem] = Field(default_factory=list)


# ChatbotLeads

class ChatbotLeadCreate(BaseModel):
    """Payload for creating a lead captured from a conversation."""

    chatbot_uuid: UUID = Field(..., description="UUID of the parent chatbot")
    conversation_uuid: UUID = Field(..., description="UUID of the source conversation")
    ai_summary: Optional[str] = None
    transcript: Optional[str] = None
    email_sent: bool = False
    status: Optional[LeadStatus] = Field(
        default="new", description=f"One of: {', '.join(ALLOWED_LEAD_STATUSES)}"
    )

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Optional[str]) -> Optional[str]:
        return validate_lead_status(value)


class ChatbotLeadUpdate(BaseModel):
    ai_summary: Optional[str] = None
    transcript: Optional[str] = None
    email_sent: Optional[bool] = None
    status: Optional[LeadStatus] = Field(
        default=None, description=f"One of: {', '.join(ALLOWED_LEAD_STATUSES)}"
    )

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Optional[str]) -> Optional[str]:
        return validate_lead_status(value)


class ChatbotLeadItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    ai_summary: Optional[str] = None
    transcript: Optional[str] = None
    email_sent: Optional[bool] = False
    status: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChatbotLeadResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ChatbotLeadItem] = None


class ChatbotLeadListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: List[ChatbotLeadItem] = Field(default_factory=list)


# Resolve forward reference to ChatbotLeadItem used in the close-conversation model.
ChatbotConversationCloseData.model_rebuild()
