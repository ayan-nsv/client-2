from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from shared.database.postgres.database_config import get_db

from core.schema import billing_schema
from core.services.billing_service import BillingService


# logger = setup_logger("billing_routes")

router = APIRouter()


@router.get("/billing/usage", response_model=List[billing_schema.BillingUsageResponse], tags=["billing"])
def get_all_billing_usage(
    _user: dict = Depends(BillingService.get_billing_api_user),
    db: Session = Depends(get_db),
 ):
    service = BillingService(db)
    return service.get_all_billing_usage()


@router.get("/billing/usage/{eco_id}", response_model=billing_schema.BillingUsageResponse, tags=["billing"])
def get_billing_usage(
    eco_id: str,
    _user: dict = Depends(BillingService.get_billing_api_user),
    db: Session = Depends(get_db),
 ):
    service = BillingService(db)
    return service.get_billing_usage(eco_id)

