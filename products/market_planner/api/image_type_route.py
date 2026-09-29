from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, status

from products.market_planner.schema import image_type_schema
from products.market_planner.services.image_type_service import ImageTypeService
from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth



router = APIRouter()
# logger = setup_logger("marketing-app")


@router.post("/image/config", status_code=status.HTTP_201_CREATED, tags=["image"])
def create_image_setting(
    request: image_type_schema.ImageTypeRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    service = ImageTypeService(db)
    return service.create_image_type(request.model_dump_json(), user)
   

@router.get("/image/config/{company_id}", tags=["image"])
def get_image_setting(
    company_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
 ):

    service = ImageTypeService(db)
    return service.get_image_type(company_id, user)
    


@router.put("/image/config", tags=["image"])
def update_image_setting(
    request: image_type_schema.ImageTypeRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    service = ImageTypeService(db)
    return service.update_image_setting(request.model_dump_json(), user)
    