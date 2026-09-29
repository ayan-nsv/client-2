from pydantic import BaseModel
from typing import Optional

class ChannelConfigRequest(BaseModel):
    instagram_post_count: Optional[int] = None
    facebook_post_count: Optional[int] = None
    linkedin_post_count: Optional[int] = None
    email_campaign_count: Optional[int] = None
    blog_post_count: Optional[int] = None  
     
    instagram_active: Optional[bool] = False
    facebook_active: Optional[bool] = False
    linkedin_active: Optional[bool] = False
    email_campaign_active: Optional[bool] = False
    blog_post_active: Optional[bool] = False
    tiktok_active: Optional[bool] = False