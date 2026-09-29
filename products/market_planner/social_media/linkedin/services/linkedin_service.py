from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime, timezone
from typing import List, Optional


from core.repository.company_repo import CompanyRepository
from products.market_planner.social_media.linkedin.repository.linkedin_repo import LinkedinRepository
from products.market_planner.social_media.linkedin.tables import linkedin_tables 
from shared.database.postgres import serialization
from shared.utils.error import error
from products.market_planner.social_media.linkedin.configuration import linkedin_config



class LinkedInService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = LinkedinRepository(db)


    def save_account(self, payload):
        if payload.author_urn:
            author_urn = payload.author_urn
        elif payload.acc_type == "linkedin_user":
            author_urn = f"urn:li:person:{payload.linkedin_id}"
        elif payload.acc_type == "linkedin_page":
            author_urn = f"urn:li:organization:{payload.linkedin_id}"
        else:
            raise error.BadRequest("Unknown account type")

        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            payload.company_id
        )

        account = self.repo.save_account(
            company_id_int=company_id_int,
            payload=payload,
            author_urn=author_urn,
        )

        return serialization.sqlalchemy_to_dict(account)


    def list_accounts(self, company_id: str) -> list[dict]:
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            company_id
        )

        accounts = self.repo.list_accounts(company_id_int)

        result = []

        for account, pages in accounts:
            row = serialization.sqlalchemy_to_dict(account)

            # Hide sensitive fields
            row["access_token"] = "********"
            row["author_urn"] = "********"

            if pages:
                row["pages"] = [
                    serialization.sqlalchemy_to_dict(page)
                    for page in pages
                ]

            result.append(row)

        return result
            
            
        
    def get_default_company_linkedin_account(self, company_id: str) -> Optional[Dict[str, Any]]:
        account = self.repo.get_default_company_linkedin_account(company_id)
        return serialization.sqlalchemy_to_dict(account)
        


    def delete_account(
        self,
        company_id: str,
        account_id: str,
     ) -> dict[str, str]:
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            company_id
        )

        deleted = self.repo.delete_account(
            company_id_int=company_id_int,
            account_id=account_id,
        )

        if not deleted:
            return {"status": "not_found"}

        return {
            "status": "disconnected",
            "message": "LinkedIn account has been disconnected successfully",
        }


    def deactivate_company_accounts(self, company_id: str) -> dict[str, Any]:
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            company_id
        )

        success = self.repo.deactivate_company_accounts(company_id_int)

        if not success:
            return {
                "status": "not_found",
                "message": "No LinkedIn accounts found for this company",
            }

        return {
            "status": "inactive",
            "message": "LinkedIn accounts have been deactivated successfully",
        }

    def get_account(
        self,
        company_id: str,
        account_id: str,
     ):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            company_id
        )

        account, pages = self.repo.get_account(
            company_id_int=company_id_int,
            account_id=account_id,
        )

        if account is None:
            return None

        if pages:
            return {
                "account": serialization.sqlalchemy_to_dict(account),
                "pages": [
                    serialization.sqlalchemy_to_dict(page)
                    for page in pages
                ],
            }

        return serialization.sqlalchemy_to_dict(account)



    def select_page(
        self,
        page_id: str,
        company_id: str,
     ):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            company_id
        )

        page = self.repo.select_page(
            company_id_int=company_id_int,
            page_id=page_id,
        )

        if page is None:
            return None

        return serialization.sqlalchemy_to_dict(page)


    def get_connected_page(self, company_id: str):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)

        page = self.repo.get_connected_page(company_id_int)

        if not page:
            return None

        return serialization.sqlalchemy_to_dict(page)



    def list_posts(self, company_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all LinkedIn posts for the given company_id
        """
      
        posts_record = self.repo.list_posts(company_id)
        return [serialization.sqlalchemy_to_dict(post) for post in posts_record]



    def publish_post(
        self,
        company_id: int,
        caption: str,
        media_urls: Optional[List[str]],
     ) -> Dict[str, Any]:
        account = self.repo.get_active_account(company_id)

        if not account:
            return {"error": "Account not found", "status": "ERROR"}

        if account.account_type != "linkedin_page":
            return {
                "error": "Connect a LinkedIn Organization Page to post. Personal profiles are not supported.",
                "status": "ERROR",
            }

        page = self.repo.get_selected_page(account.id)

        if not page:
            return {
                "error": "No LinkedIn page found. Complete LinkedIn connection first.",
                "status": "ERROR",
            }

        if not page.author_urn or not page.author_urn.startswith("urn:li:organization:"):
            return {
                "error": "Only organization posts are supported.",
                "status": "ERROR",
            }

        if not account.access_token:
            return {
                "error": "No access token found",
                "status": "ERROR",
            }

        text = (caption or "").strip()

        media = [
            url.strip()
            for url in (media_urls or [])
            if isinstance(url, str) and url.strip()
        ]

        client = linkedin_config.LinkedInClient(account.access_token)
        now = datetime.now(timezone.utc)

        try:
            response = client.create_org_post(
                page.author_urn,
                text,
                media,
            )

            share_id = response.get("id")

            if not share_id:
                return {
                    "error": "Post failed: No ID returned from LinkedIn",
                    "status": "ERROR",
                    "linkedin_response": response,
                }

            self.repo.save_post(
                company_id=company_id,
                linkedin_account_id=account.id,
                caption=text,
                media_urls=media or None,
                target_urn=page.author_urn,
                linkedin_share_id=str(share_id),
                posted_at=now,
            )

            return {
                "status": "posted",
                "post_id": str(share_id),
                "posted_at": now.isoformat(),
            }

        except Exception as e:
            # logger.exception("LinkedIn publish_post failed")
            return {
                "error": str(e),
                "status": "ERROR",
            }


    def get_post(self, company_id: str, post_id: str) -> Dict[str, Any]:
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
        post = self.repo.get_post(company_id_int, post_id)
        return serialization.sqlalchemy_to_dict(post)

