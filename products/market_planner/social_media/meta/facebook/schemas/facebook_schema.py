from pydantic import BaseModel
from typing import Optional

class DeletePostRequest(BaseModel):
    company_id: str
    page_id: str
    post_id: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_id": "your_company_id",
                "page_id": "123456789",
                "post_id": "123456789_987654321"
            }
        }

class PublishPostRequest(BaseModel):
    company_id: str
    id: str  # page_id or instagram_business_account_id
    target: str  # "page" or "instagram"
    message: Optional[str] = None
    image_url: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_id": "company_123",
                "target": "page",
                "id": "872752586781",
                "message": "Hello from FastAPI!",
                "image_url": "https://example.com/pic.jpg"
            }
        }

class EditPostRequest(BaseModel):
    company_id: str
    page_id: str
    post_id: str
    message: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_id": "company_123",
                "page_id": "123456789",
                "post_id": "123456789_987654321",
                "message": "Updated post message!"
            }
        }

class SelectPageRequest(BaseModel):
    company_id: str
    page_id: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_id": "your_company_id",
                "page_id": "872729452586781",
                "selected_instagram": True
            }
        }
