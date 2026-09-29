import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from shared.database.postgres import serialization
from shared.logger.schema import log_schema
from shared.utils.auth import auth

from products.market_planner.repository.planner_repo import PlannerRepository
from products.market_planner.integrations.openai.gpt_service import GPTservice

from core.repository.company_repo import CompanyRepository
from shared.utils.error import error, error_handler
from core.services.usage_service import UsageService


logger = logging.getLogger(__name__)


class PlannerService:
    def __init__(self, db: Session):
        self.repo = PlannerRepository(db)
        self.company_repo = CompanyRepository(db)

    async def generate_linkedin_planner(self, data, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            company = self.company_repo.get_company(company_id)
            company_data = serialization.sqlalchemy_to_dict(company)

            planner = GPTservice().generate_linkedin_post(
                company_data,
                data.theme_title,
                data.theme_description,
            )

            image_data = self.repo.get_image_analysis_prompt_data(company.id)

            image = await GPTservice().generate_image_prompt(
                planner["caption"],
                planner["hashtags"],
                planner["overlay_text"],
                image_data,
                data.image_type,
            )

            result = {
                    "channel": planner["channel"].lower(),
                    "caption": planner["caption"],
                    "hashtags": planner["hashtags"],
                    "overlay_text": planner["overlay_text"],
                    "image_prompt": image["image_prompt"],
                    "company_id": company_id,
                }

            UsageService(self.db).increment_post_generation(
                company_id,
                user["uid"],
                channel="linkedin",
            )

            return result
        except Exception as e:
            logger.error(f"Error creating facebook planner: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_linkedin_planner: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def generate_facebook_planner(self, data, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            company = self.company_repo.get_company(company_id)
            company_data = serialization.sqlalchemy_to_dict(company)

            planner = GPTservice().generate_facebook_post(
                company_data,
                data.theme_title,
                data.theme_description,
            )

            caption = planner.get("caption", "")
            hashtags = planner.get("hashtags", [])
            overlay_text = planner.get("overlay_text", "")
            channel = planner.get("channel", "").lower().strip()

            image_analysis = self.repo.get_image_analysis_prompt_data(company.id)

            image_response = await GPTservice().generate_image_prompt(
                caption,
                hashtags,
                overlay_text,
                image_analysis,
                data.image_type,
            )

            result = {
                "channel": channel,
                "image_prompt": image_response.get("image_prompt", ""),
                "caption": caption,
                "hashtags": hashtags,
                "overlay_text": overlay_text,
                "company_id": company_id,
            }

            UsageService(self.db).increment_post_generation(
                company_uuid=company_id,
                firebase_uid=user["uid"],
                channel="facebook",
            )

            return result
        except Exception as e:
            logger.error(f"Error creating facebook planner: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_facebook_planner: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def generate_instagram_planner(self, data, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            company = self.company_repo.get_company(company_id)
            company_data = serialization.sqlalchemy_to_dict(company)

            planner = GPTservice().generate_instagram_post(
                company_data,
                data.theme_title,
                data.theme_description,
            )

            caption = planner.get("caption", "")
            hashtags = planner.get("hashtags", [])
            overlay_text = planner.get("overlay_text", "")
            channel = planner.get("channel", "").lower().strip()

            image_analysis = self.repo.get_image_analysis_prompt_data(company.id)

            image_response = await GPTservice().generate_image_prompt(
                caption,
                hashtags,
                overlay_text,
                image_analysis,
                data.image_type,
            )

            result = {
                "channel": channel,
                "image_prompt": image_response.get("image_prompt", ""),
                "caption": caption,
                "hashtags": hashtags,
                "overlay_text": overlay_text,
                "company_id": company_id,
            }

            UsageService(self.db).increment_post_generation(
                company_uuid=company_id,
                firebase_uid=user["uid"],
                channel="instagram",
            )

            return result
        except Exception as e:
            logger.error(f"Error creating facebook planner: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_instagram_planner: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def regenerate_caption(self, data, user):
        try:
            company_id_int = auth.check_user_company_access(
                data.company_id,
                user["uid"],
                self.db,
            )

            result = GPTservice().regenerate_caption(
                data.caption,
                data.hashtags,
                data.overlay_text,
            )

            if not result:
                raise error.InternalServerError("Failed to regenerate caption")

            UsageService(self.db).increment_caption_regeneration(
                company_id=company_id_int,
                firebase_uid=user["uid"],
                channel=data.channel,
            )

            return {
                "caption": result.get("caption", "")
            }

        except Exception as e:
            logger.error(f"Error regenerating caption: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"regenerate_caption: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")