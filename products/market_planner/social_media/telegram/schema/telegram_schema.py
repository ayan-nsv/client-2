"""Pydantic models/schemas for Telegram API endpoints."""

from pydantic import BaseModel
from typing import Optional


class RegisterCompanyRequest(BaseModel):
    """Request model for registering a company with Telegram chat."""
    company_id: str
    telegram_username: Optional[str] = None
    chat_id: Optional[str] = None


class RegisterCompanyResponse(BaseModel):
    """Response model for company registration."""
    success: bool
    chat_id: str
    company_id: str
    data: dict


class SendPostByCompanyRequest(BaseModel):
    """Request model for sending a post to a company for approval."""
    company_id: str
    image_url: str
    caption: str
    post_id: Optional[str] = None


class SendPostByCompanyResponse(BaseModel):
    """Response model for sending a post."""
    success: bool
    message: str
    chat_id: str
    company_id: str
    approval_key: Optional[str] = None


class PostStatusRequest(BaseModel):
    """Request model for getting post approval status."""
    company_id: str
    post_id: str


class PostStatusResponse(BaseModel):
    """Response model for post status."""
    success: bool
    company_id: Optional[str] = None
    post_id: Optional[str] = None
    status: str
    chat_id: Optional[str] = None
    image_url: Optional[str] = None
    caption: Optional[str] = None
    created_at: Optional[str] = None
    responded_at: Optional[str] = None
    message_id: Optional[int] = None
    source: str = "postgres"


class BotLinkRequest(BaseModel):
    """Request model for generating bot link."""
    company_id: str


class BotLinkResponse(BaseModel):
    """Response model for bot link generation."""
    success: bool
    bot_link: str


class ThemeInfo(BaseModel):
    """Model for theme information."""
    title: str
    description: str


class ThemeSendRequest(BaseModel):
    """Request model for sending theme selection to user."""
    company_id: str  # Company ID to find chat_id
    themes: list[ThemeInfo]  # List of themes (at least 2)
    theme_id: str
    month: Optional[str] = None  # Optional month string field


class ThemeSendResponse(BaseModel):
    """Response model for theme send."""
    success: bool
    message: str
    chat_id: str
    company_id: str
    selection_key: Optional[str] = None  # theme_id used as key


class ThemeSelectionStatusRequest(BaseModel):
    """Request model for getting theme selection status."""
    company_id: str
    theme_id: str


class ThemeSelectionStatusResponse(BaseModel):
    """Response model for theme selection status."""
    success: bool
    company_id: str
    theme_id: str
    status: str  # "pending" or "selected"
    selected_theme: Optional[int] = None  # Theme number (1, 2, etc.) if selected
    selected_theme_title: Optional[str] = None  # Title of selected theme
    chat_id: Optional[str] = None
    themes: Optional[list] = None  # List of available themes
    created_at: Optional[str] = None
    responded_at: Optional[str] = None
    message_id: Optional[int] = None
    month: Optional[str] = None  # Month string field from theme send


class CompanyChatInfo(BaseModel):
    """Model for company chat information."""
    chat_id: str
    company_id: str
    company_name: Optional[str] = None
    connected_at: Optional[str] = None
    first_name: Optional[str] = None
    username: Optional[str] = None


class CompanyChatsResponse(BaseModel):
    """Response model for company chats."""
    success: bool
    company_id: str
    chats: list[CompanyChatInfo]


class RejectedPostInfo(BaseModel):
    """Model for rejected post information."""
    post_id: Optional[str] = None
    chat_id: Optional[str] = None
    image_url: Optional[str] = None
    caption: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    responded_at: Optional[str] = None
    message_id: Optional[int] = None
    company_id: Optional[str] = None


class RejectedPostsResponse(BaseModel):
    """Response model for rejected posts."""
    success: bool
    company_id: str
    rejected_posts: list[RejectedPostInfo]


class LogoutResponse(BaseModel):
    """Response model for logout."""
    success: bool
    message: str
    company_id: str
    chat_id: str

