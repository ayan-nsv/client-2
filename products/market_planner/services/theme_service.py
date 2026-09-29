import json
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone


from products.market_planner.repository.theme_repo import ThemeRepository
from core.repository.company_repo import CompanyRepository
from core.repository.user_repo import UserRepository

from shared.utils.auth import auth
from shared.cache.redis import redis
from shared.database.postgres import serialization 
from shared.utils.error import error, error_handler
from shared.logger.schema import log_schema
from shared.logger.log import setup_logger

from products.market_planner.integrations.openai.gpt_service import GPTservice

logger = setup_logger(__name__)

class ThemeService:
    def __init__(self, db: Session):
        self.repo = ThemeRepository(db)
        self.company_repo = CompanyRepository(db)


    async def get_theme(self, company_uuid, month_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            cached = await redis.redis_get(
                f"month_theme_{company_uuid}_{month_id}"
            )
            if cached:
                return cached

            theme = self.repo.get_theme(company_id_int, month_id)

            theme_data = serialization.sqlalchemy_to_dict(theme)

            await redis.redis_set(
                f"month_theme_{company_uuid}_{month_id}",
                json.dumps(theme_data),
            )
        except Exception as e:
            logger.error(f"Error getting theme: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_theme: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

        return theme_data
    def get_user_id_for_usage_tracking(self, firebase_uid: Optional[str]) -> int | None:
        """
        Get user ID for usage tracking. Returns None for guest user or if user not found.
        Use this when recording usage metrics - guest usage is tracked with user_id=None.

        The implementation moved to core.services.usage_service, which is where core
        needed it. Kept as a thin delegate so existing callers do not have to change.
        """
        # Deferred: usage_service imports company_repo, which imports this product's
        # tables through the hook registry at call time; a module-level import here
        # would close a cycle.
        from core.services.usage_service import get_user_id_for_usage_tracking

        return get_user_id_for_usage_tracking(self.db, firebase_uid)

    async def regenerate_month_theme(self, company_uuid, month_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            if month_id not in range(1, 13):
                raise error.BadRequest("month_id must be between 1 and 12")

            await redis.redis_delete(f"month_theme_{company_uuid}_{month_id}")
            await redis.redis_delete(f"all_themes_{company_uuid}")

            month_data, company = self.repo.regenerate_month_theme(
                company_uuid,
                month_id,
            )

            await redis.redis_set(
                f"month_theme_{company_uuid}_{month_id}",
                json.dumps(month_data),
            )

            user_id = self.get_user_id_for_usage_tracking(user["uid"])

            if user_id is not None:
                self.repo.record_theme_usage(
                    company.id,
                    user_id,
                )

            return {
                "data": month_data,
            }
        except Exception as e:
            logger.error(f"Error regenerating month theme: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"regenerate_month_theme: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def parse_themes_response(response_content: str):
        try:
            themes = json.loads(response_content)
            for month in themes:
                # Ensure "themes" key exists
                if "themes" not in month or not isinstance(month["themes"], list):
                    month["themes"] = []
            return themes
        except json.JSONDecodeError:
            raise ValueError(f"Model did not return valid JSON: {response_content[:200]}")


    def ensure_all_months(themes):

        expected_months = [
            "January","February","March","April","May","June",
            "July","August","September","October","November","December"
        ]
        normalized_themes = []
        for i, month_name in enumerate(expected_months, start=1):
            month_data = next((m for m in themes if m.get("month", "").lower() == month_name.lower()), None)
            if month_data:
                month_data["month_id"] = i
                normalized_themes.append(month_data)
            else:
                normalized_themes.append({"month": month_name, "month_id": i, "themes": []})
        return normalized_themes
    
    async def generate_all_themes(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            company = self.company_repo.get_company(company_uuid)

            company_data = serialization.sqlalchemy_to_dict(company)

            response = await GPTservice().generate_all_themes(company_data)

            if isinstance(response, str):
                themes = self.parse_themes_response(response)
            elif isinstance(response, list):
                themes = response
            else:
                raise error.InternalServerError("Invalid response from Gemini")

            themes = self.ensure_all_months(themes)

            themes = self.repo.save_all_themes(
                company.id,
                themes,
            )

            await redis.redis_set(
                f"all_themes_{company_uuid}",
                json.dumps(themes),
            )

            user_id = self.get_user_id_for_usage_tracking(user["uid"])

            if user_id is not None:
                self.repo.record_theme_generation_usage(
                    company.id,
                    user_id,
                )

            return {
                "message": "All themes generated successfully"
            }
        except Exception as e:
            logger.error(f"Error generating all themes: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_all_themes: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def get_all_themes(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            cached = await redis.redis_get(f"all_themes_{company_uuid}")
            if cached:
                return {"data": cached}

            company = self.company_repo.get_company(company_uuid)

            themes = self.repo.get_all_themes(company.id)

            await redis.redis_set(
                f"all_themes_{company_uuid}",
                json.dumps(themes),
            )

            return {"data": themes}
        except Exception as e:
            logger.error(f"Error getting all themes: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_all_themes: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")