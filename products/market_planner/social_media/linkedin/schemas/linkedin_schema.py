from pydantic import BaseModel
from typing import Optional, List

class PostCreateRequest(BaseModel):
    company_id: str
    caption: str
    media_urls: Optional[List[str]] = None