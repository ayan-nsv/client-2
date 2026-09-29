import uuid
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone

from core.repository.company_repo import CompanyRepository
from products.market_planner.social_media.linkedin.tables import linkedin_tables


class LinkedinRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_account(
        self,
        company_id_int: int,
        payload,
        author_urn: str,
     ):
        try:    
            if payload.acc_type == "linkedin_user":
                account = (
                    self.db.query(linkedin_tables.LinkedinAccount)
                    .filter(
                        linkedin_tables.LinkedinAccount.company_id == company_id_int,
                        linkedin_tables.LinkedinAccount.account_type == "linkedin_user",
                    )
                    .first()
                )

                if account is None:
                    account = linkedin_tables.LinkedinAccount(
                        company_id=company_id_int,
                        account_type="linkedin_user",
                        linkedin_id=payload.linkedin_id,
                        author_urn=author_urn,
                        display_name=payload.display_name,
                        profile_image_url=payload.profile_image_url,
                        access_token=payload.access_token,
                        expires_at=payload.expires_at,
                        status="inactive",
                    )
                    self.db.add(account)
                else:
                    account.linkedin_id = payload.linkedin_id
                    account.author_urn = author_urn
                    account.display_name = payload.display_name
                    account.profile_image_url = payload.profile_image_url
                    account.access_token = payload.access_token
                    account.expires_at = payload.expires_at
                    account.status = "inactive"
                    account.updated_at = datetime.now(timezone.utc)

                self.db.commit()
                self.db.refresh(account)
                return account

            elif payload.acc_type == "linkedin_page":
                account = (
                    self.db.query(linkedin_tables.LinkedinAccount)
                    .filter(
                        linkedin_tables.LinkedinAccount.company_id == company_id_int,
                        linkedin_tables.LinkedinAccount.account_type == "linkedin_page",
                    )
                    .first()
                )

                if account is None:
                    account = linkedin_tables.LinkedinAccount(
                        company_id=company_id_int,
                        account_type="linkedin_page",
                        linkedin_id=payload.linkedin_id,
                        author_urn=author_urn,
                        display_name=payload.display_name,
                        profile_image_url=payload.profile_image_url,
                        access_token=payload.access_token,
                        expires_at=payload.expires_at,
                        status="ok",
                    )

                    self.db.add(account)
                    self.db.flush()

                    for page in payload.pages:
                        self.db.add(
                            linkedin_tables.LinkedinPage(
                                linkedin_account_id=account.id,
                                linkedin_id=page.linkedin_id,
                                author_urn=page.author_urn,
                                display_name=page.display_name,
                                profile_image_url=page.profile_image_url,
                            )
                        )

                else:
                    account.access_token = payload.access_token
                    account.expires_at = payload.expires_at
                    account.status = "ok"
                    account.updated_at = datetime.now(timezone.utc)

                    existing_pages = {
                        p.linkedin_id: p
                        for p in self.db.query(linkedin_tables.LinkedinPage)
                        .filter(
                            linkedin_tables.LinkedinPage.linkedin_account_id == account.id
                        )
                        .all()
                    }

                    for page in payload.pages:
                        db_page = existing_pages.get(page.linkedin_id)

                        if db_page:
                            db_page.author_urn = page.author_urn
                            db_page.display_name = page.display_name
                            db_page.profile_image_url = page.profile_image_url
                            db_page.updated_at = datetime.now(timezone.utc)
                        else:
                            self.db.add(
                                linkedin_tables.LinkedinPage(
                                    linkedin_account_id=account.id,
                                    linkedin_id=page.linkedin_id,
                                    author_urn=page.author_urn,
                                    display_name=page.display_name,
                                    profile_image_url=page.profile_image_url,
                                )
                            )

                self.db.commit()
                self.db.refresh(account)
                return account
        except Exception:
            self.db.rollback()
            raise 


    def list_accounts(
        self,
        company_id_int: int,
     ) -> list[tuple[linkedin_tables.LinkedinAccount, list[linkedin_tables.LinkedinPage]]]:
        accounts = (
            self.db.query(linkedin_tables.LinkedinAccount)
            .filter(
                linkedin_tables.LinkedinAccount.company_id == company_id_int
            )
            .all()
        )

        result = []

        for account in accounts:
            pages = []

            if account.account_type == "linkedin_page":
                pages = (
                    self.db.query(linkedin_tables.LinkedinPage)
                    .filter(
                        linkedin_tables.LinkedinPage.linkedin_account_id == account.id
                    )
                    .all()
                )

            result.append((account, pages))

        return result


    def get_default_company_linkedin_account(self, company_id: str):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
        account_record = self.db.query(linkedin_tables.LinkedinAccount).filter(linkedin_tables.LinkedinAccount.company_id == company_id_int).first()
        if not account_record:
            return None
        return account_record

    def delete_account(
        self,
        company_id_int: int,
        account_id: str,
     ) -> bool:
        account = (
            self.db.query(linkedin_tables.LinkedinAccount)
            .filter(
                linkedin_tables.LinkedinAccount.company_id == company_id_int,
                linkedin_tables.LinkedinAccount.id == account_id,
            )
            .first()
        )

        if account is None:
            return False

        try:
            (
                self.db.query(linkedin_tables.LinkedinPage)
                .filter(
                    linkedin_tables.LinkedinPage.linkedin_account_id == account.id
                )
                .delete(synchronize_session=False)
            )

            self.db.delete(account)

            self.db.commit()

            return True

        except Exception:
            self.db.rollback()
            raise


    def deactivate_company_accounts(
        self,
        company_id_int: int,
     ) -> bool:
        accounts = (
            self.db.query(linkedin_tables.LinkedinAccount)
            .filter(
                linkedin_tables.LinkedinAccount.company_id == company_id_int
            )
            .all()
        )

        if not accounts:
            return False

        try:
            now = datetime.now(timezone.utc)

            page_account_ids = [
                account.id
                for account in accounts
                if account.account_type == "linkedin_page"
            ]

            if page_account_ids:
                pages = (
                    self.db.query(linkedin_tables.LinkedinPage)
                    .filter(
                        linkedin_tables.LinkedinPage.linkedin_account_id.in_(
                            page_account_ids
                        )
                    )
                    .all()
                )

                for page in pages:
                    page.is_selected = False
                    page.updated_at = now

            for account in accounts:
                account.status = "inactive"
                account.updated_at = now

            self.db.commit()
            return True

        except Exception:
            self.db.rollback()
            raise

    def get_account(
        self,
        company_id_int: int,
        account_id: str,
     ):
        account = (
            self.db.query(linkedin_tables.LinkedinAccount)
            .filter(
                linkedin_tables.LinkedinAccount.company_id == company_id_int,
                linkedin_tables.LinkedinAccount.id == account_id,
            )
            .first()
        )

        if account is None:
            return None, None

        pages = (
            self.db.query(linkedin_tables.LinkedinPage)
            .filter(
                linkedin_tables.LinkedinPage.linkedin_account_id == account.id
            )
            .all()
        )

        return account, pages


    def select_page(
        self,
        company_id_int: int,
        page_id: str,
     ):
        try:
            now = datetime.now(timezone.utc)
            raw = (page_id or "").strip()

            base_query = (
                self.db.query(linkedin_tables.LinkedinPage)
                .join(
                    linkedin_tables.LinkedinAccount,
                    linkedin_tables.LinkedinPage.linkedin_account_id
                    == linkedin_tables.LinkedinAccount.id,
                )
                .filter(
                    linkedin_tables.LinkedinAccount.company_id == company_id_int,
                    linkedin_tables.LinkedinAccount.account_type == "linkedin_page",
                )
            )

            page = base_query.filter(
                linkedin_tables.LinkedinPage.linkedin_id == raw
            ).first()

            if page is None:
                try:
                    page_uuid = uuid.UUID(raw)
                    page = base_query.filter(
                        linkedin_tables.LinkedinPage.uuid == page_uuid
                    ).first()
                except ValueError:
                    pass

            if page is None:
                try:
                    page_pk = int(raw)
                    page = base_query.filter(
                        linkedin_tables.LinkedinPage.id == page_pk
                    ).first()
                except ValueError:
                    pass

            if page is None:
                return None

            others = (
                self.db.query(linkedin_tables.LinkedinPage)
                .join(
                    linkedin_tables.LinkedinAccount,
                    linkedin_tables.LinkedinPage.linkedin_account_id
                    == linkedin_tables.LinkedinAccount.id,
                )
                .filter(
                    linkedin_tables.LinkedinAccount.company_id == company_id_int,
                    linkedin_tables.LinkedinPage.id != page.id,
                )
                .all()
            )

            for other in others:
                other.is_selected = False
                other.updated_at = now

            page.is_selected = True
            page.updated_at = now

            self.db.commit()
            self.db.refresh(page)

            return page

        except Exception:
            self.db.rollback()
            raise



    def get_connected_page(self, company_id: int):
        return (
            self.db.query(linkedin_tables.LinkedinPage)
            .join(
                linkedin_tables.LinkedinAccount,
                linkedin_tables.LinkedinPage.linkedin_account_id
                == linkedin_tables.LinkedinAccount.id,
            )
            .filter(
                linkedin_tables.LinkedinAccount.account_type == "linkedin_page",
                linkedin_tables.LinkedinAccount.company_id == company_id,
                linkedin_tables.LinkedinAccount.status == "ok",
                linkedin_tables.LinkedinPage.is_selected.is_(True),
            )
            .first()
        )

    def list_posts(self, company_id):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
        posts_record = self.db.query(linkedin_tables.LinkedinPost).filter(linkedin_tables.LinkedinPost.company_id == company_id_int).all()
        if not posts_record:
            return []
        return posts_record

    def get_active_account(self, company_id: int):
        return (
            self.db.query(linkedin_tables.LinkedinAccount)
            .filter(
                linkedin_tables.LinkedinAccount.company_id == company_id,
                linkedin_tables.LinkedinAccount.status == "ok",
            )
            .first()
        )

    def get_selected_page(self, account_id: int):
        page = (
            self.db.query(linkedin_tables.LinkedinPage)
            .filter(
                linkedin_tables.LinkedinPage.linkedin_account_id == account_id,
                linkedin_tables.LinkedinPage.is_selected.is_(True),
            )
            .first()
        )

        if page:
            return page

        return (
            self.db.query(linkedin_tables.LinkedinPage)
            .filter(
                linkedin_tables.LinkedinPage.linkedin_account_id == account_id,
            )
            .order_by(linkedin_tables.LinkedinPage.id)
            .first()
        )

    def save_post(
        self,
        company_id: int,
        linkedin_account_id: int,
        caption: str,
        media_urls: Optional[List[str]],
        target_urn: str,
        linkedin_share_id: str,
        posted_at: datetime,
     ):
        try:
            post = linkedin_tables.LinkedinPost(
                company_id=company_id,
                linkedin_account_id=linkedin_account_id,
                caption=caption,
                media_urls=media_urls,
                target_urn=target_urn,
                linkedin_share_id=linkedin_share_id,
                posted_at=posted_at,
                status="posted",
            )

            self.db.add(post)
            self.db.commit()
            self.db.refresh(post)

            return post

        except Exception:
            self.db.rollback()
            raise



    def get_post(self, company_id: int, post_id: str):
        return (
            self.db.query(linkedin_tables.LinkedinPost)
            .filter(
                linkedin_tables.LinkedinPost.company_id == company_id,
                linkedin_tables.LinkedinPost.id == post_id,
            )
            .first()
        )
























