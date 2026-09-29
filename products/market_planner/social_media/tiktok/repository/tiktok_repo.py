import time
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Any, Dict
from products.market_planner.social_media.tiktok.tables.tiktok_tables import TikTokAccount

class TikTokRepository:
    def __init__(self, db: Session):
        self.db = db

    def exixting_account(self, company_id_int: int) -> bool:
        tiktok_account = self.db.query(TikTokAccount).filter(TikTokAccount.company_id == company_id_int).first()
        if tiktok_account:
            return True
        return False
    
    def get_tiktok_account(self, company_id_int: int) -> TikTokAccount:
        return self.db.query(TikTokAccount).filter(TikTokAccount.company_id == company_id_int).first()
    
    def create_tiktok_account(self, company_id_int: int, request: Dict[str, Any]):
        tiktok_account = TikTokAccount(
            company_id=company_id_int,
            open_id=request["open_id"],
            access_token=request["access_token"],
            token_type=request["token_type"],
            access_expires_in=int(time.time()) + request["access_expires_in"],
            refresh_token=request["refresh_token"],
            refresh_expires_in=int(time.time()) + request["refresh_expires_in"],
            status="active",
            scope=request["scope"],
        )
        self.db.add(tiktok_account)
        self.db.commit()
        self.db.refresh(tiktok_account)
        return tiktok_account

    def update_tiktok_account(self, company_id_int: int, request: Dict[str, Any]):
        tiktok_account = self.db.query(TikTokAccount).filter(TikTokAccount.company_id == company_id_int).first()
        tiktok_account.open_id = request["open_id"]
        tiktok_account.access_token = request["access_token"]
        tiktok_account.token_type = request["token_type"]
        tiktok_account.access_expires_in = int(time.time()) + request["access_expires_in"]
        tiktok_account.refresh_token = request["refresh_token"]
        tiktok_account.refresh_expires_in = int(time.time()) + request["refresh_expires_in"]
        tiktok_account.status = "active"
        tiktok_account.scope = request["scope"]
        tiktok_account.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(tiktok_account)
        return tiktok_account

    def logout_tiktok_account(self, company_id_int: int):
        tiktok_account = self.get_tiktok_account(company_id_int)
        tiktok_account.status = "inactive"
        tiktok_account.access_token = None
        tiktok_account.refresh_token = None
        tiktok_account.access_expires_in = int(time.time()) + 0
        tiktok_account.refresh_expires_in = int(time.time()) + 0
        tiktok_account.scope = None
        tiktok_account.open_id = None
        tiktok_account.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(tiktok_account)
        return tiktok_account
