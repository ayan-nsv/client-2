from pydantic import BaseModel
from typing import Optional
from datetime import datetime




class NewsletterRequest(BaseModel):
    theme: str
    theme_description: str
    regional_language: Optional[str] = None


class NewsletterSaveRequest(BaseModel):
    channel: Optional[str] = None
    subject_line: Optional[str] = None
    preheader: Optional[str] = None
    greeting: Optional[str] = None
    opening_paragraph: Optional[str] = None
    main_content: Optional[str] = None
    practical_tips_section: Optional[str] = None
    call_to_action: Optional[str] = None
    closing: Optional[str] = None
    scheduled_datetime: Optional[datetime] = None
    status: str
    month_id: Optional[int] = None
    theme_index : Optional[int] = None

