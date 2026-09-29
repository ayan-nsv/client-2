from pydantic import BaseModel

class ImageTypeRequest(BaseModel):
    company_id: str
    image_type: int