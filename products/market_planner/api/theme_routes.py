from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from products.market_planner.services.theme_service import ThemeService
from shared.utils.auth import auth
from shared.database.postgres.database_config import get_db

# logger = setup_logger("marketing-app")

router = APIRouter()


# Get a single theme from a month
@router.get("/themes/{company_id}/{month_id}", tags=["theme"])
async def get_theme(company_id: str, month_id: int, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ThemeService(db)
    return await service.get_theme(company_id, month_id, user)

    

@router.post("/themes/{company_id}/{month_id}/regenerate", tags=["theme"])
async def regenerate_month_theme(company_id: str, month_id: int, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ThemeService(db)
    return await service.regenerate_month_theme(company_id, month_id, user)


# Generate all themes for a company
@router.post("/themes/{company_id}/generate-all", tags=["theme"])
async def generate_all_themes_route(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ThemeService(db)
    return await service.generate_all_themes(company_id, user)
    

@router.get("/themes/{company_id}", tags=["theme"])
async def get_all_themes(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ThemeService(db)
    return await service.get_all_themes(company_id, user)

    