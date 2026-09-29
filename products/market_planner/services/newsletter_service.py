import logging
from tarfile import data_filter
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException

from shared.database.postgres import serialization
from products.market_planner.integrations.openai.gpt_service import GPTservice
from products.market_planner.repository.newsletter_repo import NewsletterRepository
from core.repository.company_repo import CompanyRepository
from shared.utils.auth import auth
from shared.utils.error import error, error_handler
from shared.cache.redis import redis
from shared.logger.schema import log_schema

logger = logging.getLogger(__name__)


class NewsletterService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NewsletterRepository(db)
        self.company_repo = CompanyRepository(db)


    async def create_newsletter(self, data, company_id: str, user: dict):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            company = self.company_repo.get_company(company_id)
            company_data = serialization.sqlalchemy_to_dict(company)

            newsletter = GPTservice().generate_newsletter(
                company_data,
                data.theme,
                data.theme_description,
                data.regional_language,
            )

            return {
                "channel": newsletter.get("channel", ""),
                "subject_line": newsletter.get("subject_line", ""),
                "preheader": newsletter.get("preheader", ""),
                "greeting": newsletter.get("greeting", ""),
                "opening_paragraph": newsletter.get("opening_paragraph", ""),
                "main_content": newsletter.get("main_content", ""),
                "practical_tips_section": newsletter.get("practical_tips_section", ""),
                "call_to_action": newsletter.get("call_to_action", ""),
                "closing": newsletter.get("closing", ""),
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error generating newsletter: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_newsletter: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")



    async def save_newsletter(self, data, company_id: str, user: dict):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            newsletter = self.repo.create_newsletter(
                company_id=company_id_int,
                data=data,
            )

            await redis.redis_delete(f"all_newsletters_{company_id}")

            return {
                "status": "success",
                "message": "Newsletter saved successfully",
                "newsletter_id": newsletter.uuid,
            }

        except HTTPException:
            raise

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving newsletter: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"save_newsletter: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_newsletters_by_company_id(self, company_id: str, user: dict):
        try:
        
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            cached = await redis.redis_list_get_all(f"all_newsletters_{company_id}")
            if cached:
                return cached


            newsletters = self.repo.get_newsletters_by_company_id(company_id_int)

            if newsletters:
                await redis.redis_list_set_all(
                    f"all_newsletters_{company_id}",
                    newsletters,
                )

            return [
                serialization.sqlalchemy_to_dict(record)
                for record in newsletters
            ]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting newsletters by company id: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_newsletters_by_company_id: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")



    async def get_newsletter_by_id(
        self,
        company_id: str,
        newsletter_id: str,
        user: dict,
    ):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            newsletter = self.repo.get_newsletter_by_id(
                company_id_int,
                newsletter_id,
            )

            if not newsletter:
                raise error.NotFound("Newsletter not found")

            return serialization.sqlalchemy_to_dict(newsletter)

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error getting newsletter by id: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_newsletter_by_id: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")



    async def update_newsletter(
        self,
        company_id: str,
        newsletter_id: str,
        payload,
        user: dict,
    ):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            updated = self.repo.update_newsletter(
                newsletter_id=newsletter_id,
                payload=payload,
            )

            if not updated:
                raise error.NotFound("Newsletter not found")

            await redis.redis_delete(f"all_newsletters_{company_id}")

            return {
                "status": "success",
                "message": "Newsletter updated successfully",
                "newsletter_id": updated.uuid,
            }
    
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating newsletter: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_newsletter: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def delete_newsletter(
        self,
        company_id: str,
        newsletter_id: str,
        user: dict,
    ):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            deleted = self.repo.delete_newsletter(
                company_id=company_id_int,
                newsletter_id=newsletter_id,
            )

            if not deleted:
                raise error.NotFound("Newsletter not found")

            await redis.redis_delete(
                f"all_newsletters_{company_id}"
            )

            return {
                "status": "success",
                "message": "Newsletter deleted successfully",
            }

        except HTTPException:
            raise

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting newsletter: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"delete_newsletter: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")