from typing import Optional, List, Dict, Any
from pydantic import BaseModel, field_validator
from datetime import datetime, timezone
from fastapi import UploadFile

class ContentRequest(BaseModel):
    image_prompt: str
    aspect_ratio: str = "square"
    
class RegenerateContentRequest(BaseModel):
    """Request for /regenerate/image - prompt is generated from caption/hashtags/overlay_text"""
    channel: str
    caption: Optional[str] = ""
    hashtags: Optional[List[str]] = []
    overlay_text: Optional[str] = None
    image_type: Optional[int] = 5
    aspect_ratio: str = "square"

class ContentSaveRequest(BaseModel):
    image_url: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    status: Optional[str] = "draft"
    scheduled_datetime: Optional[datetime] = None
    scheduled_month: Optional[int] = None
    overlay_text: Optional[str] = None
    month_id: Optional[int] = None
    theme_index: Optional[int] = None

    @field_validator('scheduled_datetime')
    def validate_scheduled_datetime(cls, v):
        if v is not None:
            return v
        return None

    def is_future_schedule(self) -> bool:
        """Check if scheduled time is in the future with timezone awareness"""
        if self.scheduled_datetime:
            # Make both datetimes timezone-aware for comparison
            scheduled_dt = self.scheduled_datetime
            
            # If scheduled_dt is timezone-aware, make now timezone-aware too
            if scheduled_dt.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            
            return scheduled_dt > now
        return False

class ReframeImageRequest(BaseModel):
    company_id: str
    post_id: str
    channel: str
    target_ratio: int # 1:1 (Square)default  3:2 (Landscape)  2:3 (Portrait / Vertical)

class EditImageRequest(BaseModel):
    """Request for /edit/image - modify the currently previewed (unsaved) image.

    The image is referenced by its Firebase URL (the one returned from
    /generate or /regenerate). The instruction is applied as an override on
    top of the existing image: style/composition from the original are kept
    unless the instruction changes them.
    """
    image_url: str
    channel: str
    edit_instruction: str
    aspect_ratio: str = "square"

class GeneratePostsRequest(BaseModel):
    company_id: str
    brand_name: str
    channel: str



#################################### post from products ####################################


class GeneratePostsFromProductsRequest(BaseModel):
    products: List[Dict[str, Any]]
    product_image: Optional[UploadFile] = None
    channel: str
    month_id: Optional[str] = None

class GeneratedPost(BaseModel):
    channel: str
    image_data: str  # Base64 encoded image
    format: str  # e.g., "jpeg", "png"

class ProductImageRequest(BaseModel):
    product_image: Optional[UploadFile] = None
    Product_image_url: Optional[str] = None


class GeneratePostsFromProductsResponse(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    image_url: Optional[str] = None


class SchedularRequest(BaseModel):
    """Body of POST /content/{company_id}/schedule/create.

    Field names mirror the keys market_planner.generate_draft_posts reads off the
    payload it is handed.
    """
    theme: Optional[str] = None
    theme_description: Optional[str] = None
    scheduled_month: Optional[int] = None
    month_id: Optional[int] = None
    theme_index: Optional[int] = None
    image_type: Optional[int] = 5