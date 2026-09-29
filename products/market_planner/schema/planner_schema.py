from pydantic import BaseModel
from typing import List, Optional

class PlannerRequest(BaseModel):
    theme_title: Optional[str] = None
    theme_description: Optional[str] = None
    image_type: Optional[int] = 5
    
class CaptionRegenerateRequest(BaseModel):
    channel: str
    caption: str
    hashtags: List[str]
    overlay_text: str
    company_id: str
