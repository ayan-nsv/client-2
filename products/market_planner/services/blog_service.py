from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime, timezone

from products.market_planner.repository.blog_repo import BlogRepository
from core.repository.company_repo import CompanyRepository
from shared.utils.auth import auth
from core.services.usage_service import UsageService
from shared.database.postgres import serialization
from shared.utils.error import error, error_handler
from products.market_planner.integrations.openai.gpt_service import GPTservice
from shared.cache.redis import redis
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema


logger = setup_logger("marketing-app")

class BlogService:
    def __init__(self, db:Session):
        self.db = db
        self.repo = BlogRepository(db)
        self.company_repo = CompanyRepository(db)

    def create_blog(self, data, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            company = self.company_repo.get_company(company_id)
            company_data = serialization.sqlalchemy_to_dict(company)

            theme = data.theme or data.theme_title or ""
            if not theme:
                raise error.BadRequest(
                    "Either 'theme' or 'theme_title' is required"
                )

            blog = GPTservice().generate_blog(
                company_data=company_data,
                theme=theme,
                theme_description=data.theme_description,
                regional_language=data.regional_language,
            )

            UsageService(self.db).increment_blog_generation(
                company_id=company_id_int,
                firebase_uid=user["uid"],
            )

            return {
                "title": blog.get("title", ""),
                "meta_description": blog.get("meta_description", ""),
                "introduction": blog.get("introduction", ""),
                "sections": blog.get("sections", []),
                "conclusion": blog.get("conclusion", ""),
                "call_to_action": blog.get("call_to_action", ""),
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error creating blog: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_blog: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(
                f"Failed to create blog: {str(e)}"
            )

    async def save_blog(self, data, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            sections = [
                section.model_dump()
                for section in (data["sections"] or [])
            ]

            blog = self.repo.create_blog_post(
                company_id=company_id_int,
                title=data["title"],
                meta_description=data["meta_description"],
                introduction=data["introduction"],
                sections=sections,
                conclusion=data["conclusion"],
                call_to_action=data["call_to_action"],
                theme_index=data["theme_index"],
                scheduled_datetime=data["scheduled_datetime"],
                status=data["status"],
                month_id=data["month_id"],
            )

            await redis.redis_delete(f"all_blog_posts_{company_id}")

            return serialization.sqlalchemy_to_dict(blog)

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error saving blog: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"save_blog: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(
                f"Failed to save blog: {str(e)}"
            )


    async def get_blogs_by_company_id(self, company_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            cached_data = await redis.redis_list_get_all(
                f"all_blog_posts_{company_id}"
            )

            if cached_data:
                return {
                    "data": cached_data,
                }

            

            blogs = self.repo.get_blogs_by_company_id(company_id_int)

            if not blogs:
                return {
                    "data": [],
                    "message": "No blogs found for this company",
                }

            results = [serialization.sqlalchemy_to_dict(blog) for blog in blogs]

            await redis.redis_list_set_all(
                f"all_blog_posts_{company_id}",
                results,
            )

            return {
                "data": results,
            }
        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error getting blogs by company id: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_blogs_by_company_id: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
            ),
            self.db,
        )
        raise error.InternalServerError(message="Internal server error")


    def get_blog_by_id(self, company_id, blog_id, user):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            blog = self.repo.get_blog_by_id(
                company_id_int,
                blog_id,
            )

            if not blog:
                raise error.NotFound("Blog not found")

            return serialization.sqlalchemy_to_dict(blog)

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error getting blog by id: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_blog_by_id: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(
                f"Failed to get blog by id: {str(e)}"
            )
                

    async def update_blog(self, company_id, blog_id, data, user):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            sections = (
                [section.model_dump() for section in data.sections]
                if data.sections
                else None
            )

            blog = self.repo.update_blog(
                company_id=company_id_int,
                blog_id=blog_id,
                title=data.title,
                meta_description=data.meta_description,
                introduction=data.introduction,
                sections=sections,
                conclusion=data.conclusion,
                call_to_action=data.call_to_action,
                theme_index=data.theme_index,
                scheduled_datetime=data.scheduled_datetime,
                status=data.status,
                month_id=data.month_id,
            )

            if not blog:
                raise error.NotFound("Blog not found")

            await redis.redis_delete(f"all_blog_posts_{company_id}")

            return serialization.sqlalchemy_to_dict(blog)

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error updating blog: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_blog: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(
                f"Failed to update blog: {str(e)}"
            )


    async def delete_blog(self, company_id, blog_id, user):
        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            deleted = self.repo.delete_blog(
                company_id=company_id_int,
                blog_id=blog_id,
            )

            if not deleted:
                raise error.NotFound("Blog not found")

            await redis.redis_delete(f"all_blog_posts_{company_id}")

            return {
                "status": "success",
                "message": "Blog deleted successfully",
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error deleting blog: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"delete_blog: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(
                f"Failed to delete blog: {str(e)}"
            )