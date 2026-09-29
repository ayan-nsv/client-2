from sqlalchemy.orm import Session
from datetime import datetime, timezone

from shared.utils.error import error
from products.market_planner.social_media.meta.facebook.tables import facebook_tables
from products.market_planner.social_media.meta.instagram.tables import instagram_tables
from core.repository.company_repo import CompanyRepository


class FacebookRepository:
    def __init__(self, db: Session):
        self.db = db
        self.company_repo = CompanyRepository(db)

    def save_account(
        self,
        company_id: int,
        account_type: str,
        platform_id: str,
        user_long_token: str,
        ):
        try:
            account = (
                self.db.query(facebook_tables.FacebookInstaAccount)
                .filter(
                    facebook_tables.FacebookInstaAccount.company_id == company_id,
                    facebook_tables.FacebookInstaAccount.fb_user_id == platform_id,
                )
                .first()
            )

            if account is None:
                account = facebook_tables.FacebookInstaAccount(
                    company_id=company_id,
                    fb_user_id=platform_id,
                    user_long_token=user_long_token,
                    flow_type=account_type,
                )
                self.db.add(account)
            else:
                account.user_long_token = user_long_token

            self.db.commit()
            self.db.refresh(account)
            return account
        except Exception:
            self.db.rollback()
            raise

    def save_all_accounts(
        self,
        company_id: int,
        user_token: str,
        fb_user_id: str,
        pages: list[dict],
        flow_type: str,
     ):

        try:
            account = (
                self.db.query(facebook_tables.FacebookInstaAccount)
                .filter(
                    facebook_tables.FacebookInstaAccount.company_id == company_id
                )
                .first()
            )

            if account:
                account.fb_user_id = fb_user_id
                account.user_long_token = user_token
                account.flow_type = flow_type
            else:
                account = facebook_tables.FacebookInstaAccount(
                    company_id=company_id,
                    fb_user_id=fb_user_id,
                    user_long_token=user_token,
                    flow_type=flow_type,
                )
                self.db.add(account)
                self.db.flush()

            for page in pages:
                page_obj = (
                    self.db.query(facebook_tables.FacebookInstaPage)
                    .filter(
                        facebook_tables.FacebookInstaPage.facebook_insta_account_id
                        == account.id,
                        facebook_tables.FacebookInstaPage.page_id
                        == page["id"],
                    )
                    .first()
                )

                if page_obj:
                    page_obj.page_name = page["name"]
                    page_obj.page_access_token = page["page_access_token"]
                    page_obj.page_profile_picture_url = page[
                        "page_profile_picture_url"
                    ]
                    page_obj.instagram_connected = bool(
                        page.get("instagram_business_account")
                    )
                else:
                    page_obj = facebook_tables.FacebookInstaPage(
                        facebook_insta_account_id=account.id,
                        page_id=page["id"],
                        page_name=page["name"],
                        page_access_token=page["page_access_token"],
                        page_profile_picture_url=page[
                            "page_profile_picture_url"
                        ],
                        instagram_connected=bool(
                            page.get("instagram_business_account")
                        ),
                    )
                    self.db.add(page_obj)
                    self.db.flush()

                ig = page.get("instagram_business_account")

                if not ig:
                    continue

                ig_account = (
                    self.db.query(instagram_tables.InstagramAccount)
                    .filter(
                        instagram_tables.InstagramAccount.company_id
                        == company_id,
                        instagram_tables.InstagramAccount.ig_user_id
                        == ig["id"],
                    )
                    .first()
                )

                if ig_account:
                    ig_account.username = ig.get("username")
                    ig_account.profile_picture_url = ig.get(
                        "profile_picture_url"
                    )
                    ig_account.media_count = ig.get("media_count")
                    ig_account.facebook_insta_page_id = page_obj.id
                    ig_account.facebook_page_name = page["name"]
                    ig_account.access_token = page["page_access_token"]
                    ig_account.status = "ok"
                else:
                    self.db.add(
                        instagram_tables.InstagramAccount(
                            company_id=company_id,
                            ig_user_id=ig.get("id"),
                            username=ig.get("username"),
                            profile_picture_url=ig.get(
                                "profile_picture_url"
                            ),
                            media_count=ig.get("media_count"),
                            facebook_insta_page_id=page_obj.id,
                            facebook_page_name=page["name"],
                            access_token=page["page_access_token"],
                            status="ok",
                        )
                    )

            self.db.commit()

            return account
        except Exception:
            self.db.rollback()
            raise


    def get_account(self, company_id: int):
        account = self.db.query(facebook_tables.FacebookInstaAccount).filter(facebook_tables.FacebookInstaAccount.company_id == company_id).first()
        if not account:
            return None
        return account

    def get_all_pages(self, company_id):
        pages = (
        self.db.query(facebook_tables.FacebookInstaPage)
        .join(facebook_tables.FacebookInstaAccount)
        .filter(facebook_tables.FacebookInstaAccount.company_id == company_id)
        .all()
        )
        if not pages:
            return None
        return pages


    def get_selected_page(self, company_id):
        page_record = (
        self.db.query(facebook_tables.FacebookInstaPage.page_id)
        .join(facebook_tables.FacebookInstaAccount, facebook_tables.FacebookInstaPage.facebook_insta_account_id == facebook_tables.FacebookInstaAccount.id)
        .filter(
            facebook_tables.FacebookInstaAccount.company_id == company_id,
            facebook_tables.FacebookInstaPage.is_selected == True
        )
        .first()
        )
        if not page_record:
            return None
        return page_record

    def get_instagram_accounts(self, company_id):
        accounts = self.db.query(instagram_tables.InstagramAccount).filter(instagram_tables.InstagramAccount.company_id == company_id).all()
        if not accounts:
            return None
        return accounts


    def delete_facebook_user_data(self, fb_user_id):
        accounts = self.db.query(facebook_tables.FacebookInstaAccount).filter(facebook_tables.FacebookInstaAccount.fb_user_id == fb_user_id).all()
        if not accounts:
            return False
        for account in accounts:
            self.db.delete(account)
        self.db.commit()
        return True


    def save_post(
        self,
        company_id: int,
        target: str,
        target_id: str,
        message: str | None,
        image_url: str | None,
        response_data: dict,
        ):
        post = facebook_tables.FacebookInstaPost(
            company_id=company_id,
            target=target,
            message=message,
            image_url=image_url,
            status="posted",
            platform_response=response_data,
            platform_post_id=response_data.get("post_id"),
            posted_at=datetime.now(timezone.utc),
        )

        if target == "page":
            page = (
                self.db.query(facebook_tables.FacebookInstaPage)
                .filter(
                    facebook_tables.FacebookInstaPage.page_id == target_id
                )
                .first()
            )

            if page is None:
                raise error.NotFound("Facebook page not found")

            post.facebook_page_id = page.id
            post.facebook_insta_account_id = page.facebook_insta_account_id

        elif target == "instagram":
            instagram_account = (
                self.db.query(instagram_tables.InstagramAccount)
                .filter(
                    instagram_tables.InstagramAccount.ig_user_id == target_id
                )
                .first()
            )

            if instagram_account is None:
                raise error.NotFound("Instagram account not found")

            post.instagram_account_id = instagram_account.id
            post.facebook_insta_account_id = (
                instagram_account.facebook_insta_account_id
            )

        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        return post


    def get_published_posts(self, company_id):
        posts = (
            self.db.query(facebook_tables.FacebookInstaPost)
            .filter(
                facebook_tables.FacebookInstaPost.company_id == company_id,
                facebook_tables.FacebookInstaPost.status == "posted"
            )
            .order_by(facebook_tables.FacebookInstaPost.posted_at.desc())
            .all()
        )
        if not posts:
            return None
        return posts


    def get_post(self, company_id: int, post_identifier: str):
        post = self.db.query(facebook_tables.FacebookInstaPost).filter(
            facebook_tables.FacebookInstaPost.company_id == company_id,
            facebook_tables.FacebookInstaPost.platform_post_id == post_identifier
        ).first()

        if not post:
            return None
        return post

    def get_app_posts(self, company_id: int, page_id: str):
        posts = (
            self.db.query(facebook_tables.FacebookInstaPost)
            .join(facebook_tables.FacebookInstaPage)
            .filter(
                facebook_tables.FacebookInstaPost.company_id == company_id,
                facebook_tables.FacebookInstaPage.page_id == page_id
            )
            .all()
        )
        if not posts:
            return None
        return posts


    def update_post_status(self, post_id: str, status: str):
        try:
            post = self.db.query(facebook_tables.FacebookInstaPost).filter(
                facebook_tables.FacebookInstaPost.platform_post_id == post_id
            ).first()
            if not post:
                return None
            post.status = status
            self.db.commit()
            self.db.refresh(post)
            return post
        except Exception:
            self.db.rollback()
            raise


    def delete_post(self, company_id: int, post_id: str):
        try:
            post = self.db.query(facebook_tables.FacebookInstaPost).filter(
            facebook_tables.FacebookInstaPost.company_id == company_id,
            facebook_tables.FacebookInstaPost.platform_post_id == post_id
            ).first()
            if not post:
                return False
            self.db.delete(post)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def update_all_accounts(self, company_id: int):
        try:
            accounts = self.db.query(facebook_tables.FacebookInstaAccount).filter(facebook_tables.FacebookInstaAccount.company_id == company_id).all()
            if not accounts:
                return False
            for account in accounts:
                account.user_long_token = None
                account.flow_type = None
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def select_page(self, company_id_int: int, page_id: str):
        page = (
            self.db.query(facebook_tables.FacebookInstaPage)
            .join(
                facebook_tables.FacebookInstaAccount,
                facebook_tables.FacebookInstaPage.facebook_insta_account_id
                == facebook_tables.FacebookInstaAccount.id,
            )
            .filter(
                facebook_tables.FacebookInstaAccount.company_id == company_id_int,
                facebook_tables.FacebookInstaPage.page_id == page_id,
            )
            .first()
        )

        if not page:
            return None

        account_id = page.facebook_insta_account_id

        page.is_selected = True

        (
            self.db.query(facebook_tables.FacebookInstaPage)
            .filter(
                facebook_tables.FacebookInstaPage.facebook_insta_account_id == account_id,
                facebook_tables.FacebookInstaPage.page_id != page_id,
            )
            .update(
                {"is_selected": False},
                synchronize_session=False,
            )
        )

        self.db.commit()
        self.db.refresh(page)

        return page


    def get_facebook_account(self, company_id: int):
        account = self.db.query(facebook_tables.FacebookInstaPage).join(facebook_tables.FacebookInstaAccount, facebook_tables.FacebookInstaPage.facebook_insta_account_id == facebook_tables.FacebookInstaAccount.id).filter(facebook_tables.FacebookInstaAccount.company_id == company_id, facebook_tables.FacebookInstaPage.is_selected == True, facebook_tables.FacebookInstaAccount.user_long_token != None, facebook_tables.FacebookInstaAccount.flow_type != None).first()
        if not account:
            return None
        return account

    
    def get_access_token_from_company_id(self, company_id) -> str:
        """Get Meta user long-lived access token for a company."""
        company_id_int = self.company_repo.get_company_id_from_uuid(company_id)
        account = self.db.query(facebook_tables.FacebookInstaAccount).filter(
            facebook_tables.FacebookInstaAccount.company_id == company_id_int
        ).first()
        if not account:
            raise error.NotFound(
                message=f"Facebook account not found for company {company_id}"
            )
        access_token = account.user_long_token
        if not access_token:
            raise error.NotFound(
                message=f"Access token not found for company {company_id}"
            )
        return access_token







