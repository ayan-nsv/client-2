from pydantic import BaseModel
from typing import Optional


class PostRequest(BaseModel):
    company_id: str
    ig_user_id: str          
    image_url: str
    caption: Optional[str] = ""
   