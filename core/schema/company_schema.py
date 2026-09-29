"""Pydantic models for CompanyConfig API (create, update, response). Same schema/response style as agent config."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any, Literal, Union
from datetime import datetime

LocationMode = Literal["on_site", "digital", "both"]

from pydantic import BaseModel, Field, AliasChoices
from typing import List, Optional, Dict, Any, Literal


class CompanyRequest(BaseModel):
    company_name: Optional[str] = None
    url: Optional[str] = None
    company_info: Optional[str] = None
    address: Optional[str] = None
    favicon_url: Optional[str] = None
    fonts_typography: Optional[List[str]] = None
    industry: Optional[str] = None
    keywords: Optional[List[str]] = None
    logo_url: Optional[str] = None
    target_group: Optional[str] = None
    theme_colors: Optional[List[str]] = None
    tone_analysis: Optional[str] = None
    products: Optional[List[str]] = None
    matched_fonts: Optional[Dict[str, Any]] = None
    product_categories: Optional[Dict[str, Any]] = None
    eco_id: Optional[str] = None
    tier: Optional[Literal["FREE", "PAID"]] = None
    agent_category: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("agent_category", "agentCategory"),
    )

    composition_and_style: Optional[str] = None
    environment_settings: Optional[str] = None
    image_types_and_animation: Optional[str] = None
    keywords_for_ai_image_generation: Optional[str] = None
    lighting_and_color_tone: Optional[str] = None
    subjects_and_people: Optional[str] = None
    technology_elements: Optional[str] = None
    theme_and_atmosphere: Optional[str] = None
    analyzed_images: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("analyzed_images", "analyzedImages"),
    )
    analyzed_images_urls: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("analyzed_images_urls", "analyzedImagesUrls"),
    )
    image_urls: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("image_urls", "imageUrls"),
    )


class CompanyConfigCreate(BaseModel):
    """Payload for creating a company config. company_id is the company UUID (converted to id before saving)."""
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "supported_languages": ["en", "sv"],
                    "default_language": "en",
                    "location_mode": "both",
                    "company_address": "Storgatan 1, 111 23 Stockholm",
                    "business_hours": {
                        "monday": {"enabled": True, "from": "09:00", "to": "17:00"},
                        "tuesday": {"enabled": True, "from": "09:00", "to": "17:00"},
                        "wednesday": {"enabled": True, "from": "09:00", "to": "17:00"},
                        "thursday": {"enabled": True, "from": "09:00", "to": "17:00"},
                        "friday": {"enabled": True, "from": "09:00", "to": "15:00"},
                        "saturday": {"enabled": False},
                        "sunday": {"enabled": False},
                    },
                    "exception_hours": [
                        {"date": "2026-12-24", "closed_all_day": True, "label": "Christmas Eve"},
                        {"date": "2026-12-25", "closed_all_day": True, "label": "Christmas Day"},
                    ],
                    "notification_email_recipients": ["bookings@example.com", "support@example.com"],
                    "bookings_enabled": True,
                    "caller_data_collection": {
                        "collect_name": "required",
                        "collect_phone_number": "required",
                        "collect_reason_for_call": "optional",
                        "collect_preferred_callback_time": True,
                    },
                    "callback_settings": {
                        "callback_message": {
                            "sv-SE": "Vi ringer dig snart.",
                            "en-US": "We will call you back shortly.",
                        },
                        "callback_email_recipients": ["support@example.com"],
                    },
                    "phone_no": "+46123456789",
                    "phone_summary": True,
                    "email_summary": True,
                }
            ]
        }
    )
    company_id: str = Field(..., description="Company UUID")
    supported_languages: List[str] = Field(..., min_length=1, description="e.g. ['en', 'sv']")
    default_language: str = Field(..., min_length=1, max_length=20)
    location_mode: LocationMode = Field(..., description="Must be 'on_site', 'digital', or 'both'")
    company_address: Optional[str] = Field(None, max_length=500)
    business_hours: Optional[Dict[str, Any]] = Field(
        None,
        description='e.g. {"monday": {"enabled": true, "from": "09:00", "to": "17:00"}}',
    )
    exception_hours: Optional[List[Dict[str, Any]]] = Field(
        None,
        description='e.g. [{"date": "2026-03-01", "closed_all_day": true, "label": "Holiday"}]',
    )
    notification_email_recipients: Optional[List[str]] = None
    bookings_enabled: bool = True
    caller_data_collection: Optional[Dict[str, Any]] = None
    callback_settings: Optional[Dict[str, Any]] = None
    phone_no: Optional[str] = Field(None, max_length=20)
    phone_summary: Optional[bool] = None
    email_summary: Optional[bool] = None
    daily_summary: Optional[bool] = None
    customer_sms_enabled: Optional[bool] = None
    sms_email: Optional[str] = Field(None, max_length=255)


class CompanyConfigUpdate(BaseModel):
    """Payload for updating a company config (all optional)."""
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "default_language": "sv",
                    "bookings_enabled": False,
                    "notification_email_recipients": ["updated@example.com"],
                    "business_hours": {
                        "monday": {"enabled": True, "from": "08:00", "to": "18:00"},
                        "tuesday": {"enabled": True, "from": "08:00", "to": "18:00"},
                        "wednesday": {"enabled": True, "from": "08:00", "to": "18:00"},
                        "thursday": {"enabled": True, "from": "08:00", "to": "18:00"},
                        "friday": {"enabled": True, "from": "08:00", "to": "16:00"},
                        "saturday": {"enabled": False},
                        "sunday": {"enabled": False},
                    },
                    "phone_summary": True,
                    "phone_no": "+46123456789",
                    "email_summary": True,
                }
            ]
        }
    )
    supported_languages: Optional[List[str]] = None
    default_language: Optional[str] = Field(None, min_length=1, max_length=20)
    location_mode: Optional[LocationMode] = None
    company_address: Optional[str] = Field(None, max_length=500)
    business_hours: Optional[Dict[str, Any]] = None
    exception_hours: Optional[List[Dict[str, Any]]] = None
    notification_email_recipients: Optional[List[str]] = None
    bookings_enabled: Optional[bool] = None
    caller_data_collection: Optional[Dict[str, Any]] = None
    callback_settings: Optional[Dict[str, Any]] = None
    phone_no: Optional[str] = Field(None, max_length=20)
    phone_summary: Optional[bool] = None
    email_summary: Optional[bool] = None
    daily_summary: Optional[bool] = None
    customer_sms_enabled: Optional[bool] = None
    sms_email: Optional[str] = Field(None, max_length=255)


# Response (item) model

class CompanyConfigItem(BaseModel):
    """Single company config in response."""
    uuid: UUID
    company_id: str
    supported_languages: List[str]
    default_language: str
    location_mode: str
    company_address: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    exception_hours: Optional[List[Dict[str, Any]]] = None
    notification_email_recipients: Optional[List[str]] = None
    bookings_enabled: bool
    caller_data_collection: Optional[Dict[str, Any]] = None
    callback_settings: Optional[Dict[str, Any]] = None
    phone_no: Optional[str] = None
    phone_summary: Optional[bool] = None
    email_summary: Optional[bool] = None
    daily_summary: Optional[bool] = None
    customer_sms_enabled: Optional[bool] = None
    sms_email: Optional[str] = None
    scheduled_email_time: Optional[str] = Field(
        None,
        description="Daily summary send time with offset, ISO time e.g. 16:27:02+05:30 (maps to scheduled_email_time)",
    )
    scheduled_timezone: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# Response: one config per company

class CompanyConfigResponse(BaseModel):
    """Standard response. data is the single company config object (one per company), or null."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[CompanyConfigItem] = None


class NotificationConfigData(BaseModel):
    """Notification settings returned in response."""
    company_id: str
    phone_no: Optional[str] = None
    phone_summary: Optional[bool] = None
    email_summary: Optional[bool] = None
    email_recipients: Optional[List[str]] = None
    daily_summary: Optional[bool] = None
    customer_sms_enabled: Optional[bool] = None
    sms_email: Optional[str] = None
    scheduled_email_time: Optional[str] = Field(
        None,
        description="Daily summary send time with offset, ISO time e.g. 16:27:02+05:30",
    )
    scheduled_timezone: Optional[str] = Field(
        None,
        description="IANA timezone for scheduled daily summary send, e.g. Asia/Kolkata",
    )

class NotificationConfigResponse(BaseModel):
    """Response model for notification config updates."""
    success: bool
    status_code: int
    message: Optional[str] = None
    data: Optional[NotificationConfigData] = None


class NotificationConfigRequest(BaseModel):
    """Payload for updating notification settings specifically."""
    company_id: str = Field(..., description="Company UUID")
    phone_no: Optional[str] = Field(None, max_length=20)
    phone_summary: Optional[bool] = None
    email_summary: Optional[bool] = None
    email_recipients: Optional[List[str]] = Field(
        None,
        description="Maps to company_configs.notification_email_recipients",
    )
    # email_receipient: Optional[str] = Field(None, description="Maps to notification_email_recipients")
    daily_summary: Optional[bool] = None
    customer_sms_enabled: Optional[bool] = None
    sms_email: Optional[str] = Field(None, max_length=255)
    scheduled_email_time: Optional[str] = Field(
        None,
        description="Time with UTC offset for DB TIME WITH TIME ZONE, e.g. 16:27:02+05:30. Send null to clear.",
    )
    scheduled_timezone: Optional[str] = Field(
        None,
        max_length=128,
        description="IANA timezone for daily summary window, e.g. Asia/Kolkata. Send null to clear.",
    )



class CompanyFeatureUpdateRequest(BaseModel):
    company_id: str 
    feature_id: int 
    enabled: bool 



class CompanyNotificationEmailsRequest(BaseModel):
    company_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of company UUID/string IDs. Required unless all_company is true.",
    )
    company_id: Optional[Union[str, List[str]]] = Field(
        None,
        description="Optional single company ID, repeated values, or comma-separated IDs.",
    )
    all_company: bool = Field(
        False,
        description="When true, return notification emails for all companies.",
    )
