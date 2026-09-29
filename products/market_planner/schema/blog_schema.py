from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class BlogSection(BaseModel):
    heading: str
    content: str


class BlogRequest(BaseModel):
    theme: Optional[str] = None
    theme_title: Optional[str] = None  # alternative to theme (matches planner API)
    theme_description: str
    regional_language: Optional[str] = None



class BlogSaveRequest(BaseModel):
    title: Optional[str] = None
    meta_description: Optional[str] = None
    introduction: Optional[str] = None
    sections: Optional[List[BlogSection]] = None
    conclusion: Optional[str] = None
    call_to_action: Optional[str] = None
    theme_index: Optional[int] = None
    scheduled_datetime: Optional[datetime] = None
    status: Optional[str] = "draft"
    month_id: Optional[int] = None