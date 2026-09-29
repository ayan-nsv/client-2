import time
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy.orm import Session

from shared.database.postgres import serialization 
from shared.logger.log import setup_logger

from core.repository.company_repo import CompanyRepository

from products.market_planner.social_media.tiktok.repository.tiktok_repo import TikTokRepository
from products.market_planner.social_media.tiktok.tables.tiktok_tables import TikTokAccount

logger = setup_logger("marketing-app")

class TikTokService:
    def __init__(self, db: Session):
        self.db = db
        self.tiktok_repo = TikTokRepository(db)
        self.company_repo = CompanyRepository(db)

    def save_tiktok_account(self, request: Dict[str, Any]) -> Dict[str, Any]:
        try:
            company_id_int = self.company_repo.get_company_id_from_uuid(request["company_id"])
            if self.tiktok_repo.exixting_account(company_id_int):
                tiktok_account = self.tiktok_repo.update_tiktok_account(company_id_int, request)
                return serialization.sqlalchemy_to_dict(tiktok_account)
            else:
                tiktok_account = self.tiktok_repo.create_tiktok_account(company_id_int, request)
                return serialization.sqlalchemy_to_dict(tiktok_account)
        except Exception as e:
            logger.error(f"[TIKTOK_SAVE_ACCOUNT_ERROR] error={e}")
            raise e

    def logout_tiktok_account(self, company_id: str) -> Dict[str, Any]:
        company_id_int = self.company_repo.get_company_id_from_uuid(company_id)
        tiktok_account = self.tiktok_repo.get_tiktok_account(company_id_int)
        if not tiktok_account:
            return None
        tiktok_account = self.tiktok_repo.logout_tiktok_account(company_id_int)
        return serialization.sqlalchemy_to_dict(tiktok_account)


    def get_tiktok_account(self, company_id: str) -> Dict[str, Any]:
        company_id_int = self.company_repo.get_company_id_from_uuid(company_id)
        tiktok_account = self.tiktok_repo.get_tiktok_account(company_id_int)
        if not tiktok_account:
            return None

        now = int(time.time())
        access_expired = (
            tiktok_account.access_expires_in is None
            or tiktok_account.access_expires_in < now
        )
        refresh_expired = (
            tiktok_account.refresh_expires_in is None
            or tiktok_account.refresh_expires_in < now
        )

        if access_expired and refresh_expired:
            self.logout_tiktok_account(company_id)
            return None

        return serialization.sqlalchemy_to_dict(tiktok_account)
