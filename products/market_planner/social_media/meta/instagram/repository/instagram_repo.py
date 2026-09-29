from sqlalchemy.orm import Session
from datetime import datetime, timezone
from products.market_planner.social_media.meta.facebook.tables import facebook_tables
from products.market_planner.social_media.meta.instagram.tables import instagram_tables
from shared.database.postgres import serialization

class InstagramRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_instagram_account_by_company_id(self, company_id: str):
        return self.db.query(instagram_tables.InstagramAccount).filter(instagram_tables.InstagramAccount.company_id == company_id).first()

    def save_instagram_account(
        self,
        company_id_int: int,
        ig_user_id: str,
        username: str,
        profile_picture_url: str,
        account_type: str,
        media_count: int,
        long_lived_token: str,
        expires_in: int,
     ):
        try:
            account = (
                self.db.query(instagram_tables.InstagramAccount)
                .filter(instagram_tables.InstagramAccount.company_id == company_id_int)
                .first()
            )

            now = datetime.now(timezone.utc)

            if account:
                account.access_token = long_lived_token
                account.account_type = account_type
                account.profile_picture_url = profile_picture_url
                account.expires_in = expires_in
                account.username = username
                account.media_count = media_count
                account.ig_user_id = ig_user_id
                account.updated_at = now
                account.connected_at = now
                account.status = "ok"
            else:
                account = instagram_tables.InstagramAccount(
                    company_id=company_id_int,
                    ig_user_id=ig_user_id,
                    username=username,
                    account_type=account_type,
                    media_count=media_count,
                    profile_picture_url=profile_picture_url,
                    access_token=long_lived_token,
                    expires_in=expires_in,
                    token_type="long_lived",
                    connected_at=now,
                    updated_at=now,
                    status="ok",
                )
                self.db.add(account)

            self.db.commit()
            self.db.refresh(account)

            return account
        except Exception:
            self.db.rollback()
            raise

    def deactivate_insta_account(self, company_id_int: int):
        insta_account = self.db.query(instagram_tables.InstagramAccount).filter(
            instagram_tables.InstagramAccount.company_id == company_id_int,
            instagram_tables.InstagramAccount.status == "ok"
        ).first()

        if not insta_account:
            return None

        insta_account.status = "inactive"
        insta_account.updated_at = datetime.now(timezone.utc)

        # ✅ store FB page id BEFORE clearing
        fb_page_id = insta_account.facebook_insta_page_id

        if fb_page_id:
            facebook_insta_page = self.db.query(facebook_tables.FacebookInstaPage).filter(
                facebook_tables.FacebookInstaPage.id == fb_page_id
            ).first()

            if facebook_insta_page:
                facebook_insta_page.instagram_connected = False
                facebook_insta_page.updated_at = datetime.now(timezone.utc)

        # ✅ NOW clear the linkage
        insta_account.facebook_insta_page_id = None
        insta_account.facebook_page_name = None

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return serialization.sqlalchemy_to_dict(insta_account)


    def get_instagram_posts(self, company_id: str):
        posts = self.db.query(instagram_tables.InstagramPost).filter(instagram_tables.InstagramPost.company_id == company_id).all()
        if not posts:
            return None
        return posts

    def select_instagram_account(
        self,
        company_id_int: int,
        ig_user_id: str,
    ):
        try:    
            account = (
                self.db.query(instagram_tables.InstagramAccount)
                .filter(
                    instagram_tables.InstagramAccount.company_id == company_id_int,
                    instagram_tables.InstagramAccount.ig_user_id == ig_user_id,
                )
                .first()
            )

            if not account:
                return None

            now = datetime.now(timezone.utc)

            account.status = "ok"
            account.updated_at = now
            account.connected_at = now

            inactive_accounts = (
                self.db.query(instagram_tables.InstagramAccount)
                .filter(
                    instagram_tables.InstagramAccount.company_id == company_id_int,
                    instagram_tables.InstagramAccount.ig_user_id != ig_user_id,
                )
                .all()
            )

            for acc in inactive_accounts:
                acc.status = "inactive"
                acc.updated_at = now
                acc.connected_at = None

            self.db.commit()
            self.db.refresh(account)

            return account
        except Exception:
            self.db.rollback()
            raise