
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# ###########
from core.services.company_service import CompanyService
from core.schema import company_schema, billing_schema
from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth


router = APIRouter()



@router.get("/company", tags=["Company"])
def get_companies(page: int = 1, limit: int = 5, user: dict = Depends(auth.get_admin_user), db: Session = Depends(get_db)):
    service = CompanyService(db)
    return service.get_companies(page, limit, user)


@router.post("/company", tags=["Company"])
async def create_company(request: company_schema.CompanyRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = CompanyService(db)
    return await service.create_company(request, user)
    


# Register /company/feature/* before /company/{company_id} so paths like /company/feature are not
# matched with company_id="feature".
@router.put("/company/feature", tags=["Company_feature"])
def update_company_feature(
    payload: company_schema.CompanyFeatureUpdateRequest,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = CompanyService(db)
    return service.update_company_feature(payload, user)
    

@router.get("/company/feature/company/{company_id}", tags=["Company_feature"])
def get_company_features(
    company_id: str,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = CompanyService(db)
    return service.get_company_features(company_id, user)

@router.patch("/company/{company_id}", tags=["Company"])
async def patch_company_billing(
    company_id: str,
    payload: billing_schema.CompanyBillingPatchRequest,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Update billing tier and agent category for a company (idempotent)."""
    service = CompanyService(db)
    return await service.patch_company_billing(company_id, payload, user)
 

@router.post("/company/notification-emails", tags=["Company_config"])
def get_company_notification_emails(
    payload: company_schema.CompanyNotificationEmailsRequest,
    user: dict = Depends(auth.get_billing_api_user),
    db: Session = Depends(get_db),
):
    """Return company id, company name, and configured notification email recipients."""

    service = CompanyService(db)
    return service.get_company_notification_emails(payload, user)
    


@router.get("/company/{company_id}", tags=["Company"])
async def get_company(company_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = CompanyService(db)
    return await service.get_company(company_id, user)


############################################# update company ###########################################


@router.put("/company/{company_id}", tags=["Company"])
async def update_company(company_id: str, request: company_schema.CompanyRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = CompanyService(db)
    return await service.update_company(company_id, request, user)
    


@router.delete("/company/{company_id}", tags=["Company"])
async def delete_company(company_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = CompanyService(db)
    return await service.delete_company(company_id, user)
    


############################################# get usage for a company ###########################################


# Company config (same pattern as agent config)

@router.post("/company/config", response_model= company_schema.CompanyConfigResponse, response_model_exclude_none=True, tags=["Company"])
def create_company_config(
    payload: company_schema.CompanyConfigCreate,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = CompanyService(db)
    return service.create_company_config(payload, user)
    
    

@router.get("/company/config/company/{company_id}", response_model= company_schema.CompanyConfigResponse, response_model_exclude_none=True, tags=["Company"])
def get_company_config_by_company(
    company_id: str,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = CompanyService(db)
    return service.get_company_config_by_company(company_id, user)
   



@router.delete("/company/config/{config_uuid}", response_model= company_schema.CompanyConfigResponse, response_model_exclude_none=True, tags=["Company"])
def delete_company_config(
    company_uuid: str,
    config_uuid: UUID,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = CompanyService(db)
    return service.delete_company_config(company_uuid, config_uuid, user)
   


@router.put("/company/config/{config_uuid}", response_model= company_schema.CompanyConfigResponse, response_model_exclude_none=True, tags=["Company"])
def update_company_config(
    config_uuid: UUID,
    payload: company_schema.CompanyConfigUpdate,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
   service = CompanyService(db)
   return service.update_company_config(config_uuid, payload, user)
    


@router.post("/company/config/notification", response_model=company_schema.NotificationConfigResponse, response_model_exclude_none=True, tags=["Company"])
def update_notification_config(
    payload: company_schema.NotificationConfigRequest,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
   service = CompanyService(db)
   return service.update_notification_config(payload, user)
    

@router.get("/company/config/notification/{company_id}", response_model=company_schema.NotificationConfigResponse, response_model_exclude_none=True, tags=["Company"])
def get_notification_config(
    company_id: str,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get notification-specific settings for a company from CalendarConfig and CompanyConfig.
    Falls back to CompanyConfig if not found in CalendarConfig.
    """
    service = CompanyService(db)
    return service.get_notification_config(company_id, user)
    