import json
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

# logger = setup_logger("marketing-app")



###############################################
from products.market_planner.schema import newsletter_schema
from shared.utils.auth import auth
from shared.database.postgres.database_config import get_db
from products.market_planner.services.newsletter_service import NewsletterService

router = APIRouter()


@router.post("/newsletter/{company_id}/generate", tags=["newsletter"])
async def create_newsletter(request: newsletter_schema.NewsletterRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = NewsletterService(db)
    return service.create_newsletter(request.model_dump_json(), company_id, user)
    
    

@router.post("/newsletter/{company_id}/save", tags=["newsletter"])
def save_newsletter(newsletter: newsletter_schema.NewsletterSaveRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = NewsletterService(db)
    return service.save_newsletter(newsletter.model_dump_json(), company_id, user)
    


@router.get("/newsletters/{company_id}", tags=["newsletter"])
async def get_newsletters_by_company_id(
    company_id: str, db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user)
    ):
    service = NewsletterService(db)
    return service.get_newsletters_by_company_id(company_id, user)
    
                    
@router.get("/newsletters/{company_id}/{newsletter_id}", tags=["newsletter"])
async def get_newsletter_by_id(
    company_id: str, newsletter_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)
    ):
    service = NewsletterService(db)
    return service.get_newsletter_by_id(company_id, newsletter_id, user)
    


@router.put("/newsletters/{company_id}/{newsletter_id}/schedule", tags=["newsletter"])
async def update_newsletter(
    company_id: str,
    newsletter_id: str,
    payload: newsletter_schema.NewsletterSaveRequest,
    db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)
    ):
    service = NewsletterService(db)
    return service.update_newsletter(company_id, newsletter_id, payload, user)
    

@router.delete("/newsletters/{company_id}/{newsletter_id}", tags=["newsletter"])
async def delete_newsletter(
    company_id: str, newsletter_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)
    ):

    service = NewsletterService(db)
    return service.delete_newsletter(company_id, newsletter_id, user)
    