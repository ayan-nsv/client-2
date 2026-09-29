from fastapi import APIRouter, Depends 
from sqlalchemy.orm import Session   

from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth

from products.market_planner.services.planner_service import PlannerService
from products.market_planner.schema import planner_schema

router = APIRouter()

# logger = setup_logger("marketing-app")



######## create linkedin planner
@router.post(
    "/planners/{company_id}/linkedin",
    tags=["LinkedIn Planners"],
    summary="Generate LinkedIn planner",
    description="Generate a social media planner specifically for LinkedIn platform",
    response_description="Generated LinkedIn planner details"
)

async def generate_linkedin_planner(request: planner_schema.PlannerRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user), tags=["Planners"]):
    service = PlannerService(db)
    return await service.generate_linkedin_planner(request.model_dump_json(), company_id, user)
    

##### create facebook planner
@router.post(
    "/planners/{company_id}/facebook",
    tags=["Facebook Planners"],
    summary="Generate Facebook planner",
    description="Generate a social media planner specifically for Facebook platform",
    response_description="Generated Facebook planner details"
)
async def generate_facebook_planner(request: planner_schema.PlannerRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user), tags=["Planners"]):
    service = PlannerService(db)
    return await service.generate_facebook_planner(request.model_dump_json(), company_id, user)
    

###### create instagram planner
@router.post(
    "/planners/{company_id}/instagram",
    tags=["Instagram Planners"],
    summary="Generate Instagram planner",
    description="Generate a social media planner specifically for Instagram platform",
    response_description="Generated Instagram planner details"
)
async def generate_instagram_planner(request: planner_schema.PlannerRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user), tags=["Planners"]):
    service = PlannerService(db)
    return await service.generate_instagram_planner(request.model_dump_json(), company_id, user)

######################################################### caption regenerate #########################################################

@router.post(
    "/planners/caption/regenerate",
    tags=["Caption Regenerate"],
    summary="Regenerate caption",
    description="Regenerate caption for a social media post using the same image prompt, hashtags and overlay text",
    response_description="Regenerated caption"
)
async def regenerate_caption_route(request: planner_schema.CaptionRegenerateRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user), tags=["Planners"]):
    service = PlannerService(db)
    return await service.regenerate_caption(request.model_dump_json(), user)
    