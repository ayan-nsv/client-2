from sqlalchemy.orm import Session
from fastapi import HTTPException
from fastapi.responses import JSONResponse
import json
from typing import Optional
from fastapi import UploadFile
from PIL import Image
import io
import base64
import uuid
from datetime import datetime, timezone

import gc
import time
from shared.utils.firebase.firebase_config import upload_image


from products.market_planner.repository.content_repo import ContentRepository
from products.market_planner.repository.newsletter_repo import NewsletterRepository
from products.market_planner.repository.blog_repo import BlogRepository
from products.market_planner.repository.theme_repo import ThemeRepository
from core.repository.company_repo import CompanyRepository
from core.services.usage_service import UsageService
from shared.utils.error import error
from shared.utils.auth import auth
from products.market_planner.schema import content_schema 
from products.market_planner.integrations.openai.gpt_service import GPTservice
from products.market_planner.integrations.gemini import gemini_service as GeminiService
from shared.database.postgres import serialization
from shared.cache.redis import redis
from celery_app import celery_app
from shared.queue.celery import celery_utils
from products.market_planner.tables import content_tables
from shared.utils.constants import constants
from products.market_planner.services import url_service 
from shared.utils.firebase import firebase_config
from shared.logger.schema import log_schema
from shared.logger.log import setup_logger
from shared.utils.error import error_handler


logger = setup_logger("marketing-app")


class ContentService:
    def __init__(self, db: Session):
        self.db = db
        self.contentrepo = ContentRepository(db)
        self.companyrepo = CompanyRepository(db)
        self.theme_repo = ThemeRepository(db)


    def platform_post_ids_by_image_url():
        pass
    def published_instagram_ids_by_image_url():
        pass
        
    async def process_company(self, planner_info: dict) -> str:
        image_bytes = None
        try:
            total_t0 = time.perf_counter()
            # Generate a unique ID for this content
            content_id = str(uuid.uuid4())
            
            # Generate image using Gemini
            gen_t0 = time.perf_counter()
            image_bytes, mime_type = await GeminiService.generate_image(planner_info)
            gen_ms = int((time.perf_counter() - gen_t0) * 1000)

            # Sanity check image size; guard against corrupt/empty results
            if not image_bytes or len(image_bytes) < 1024:  # <1 KB is almost certainly invalid
                raise RuntimeError("Generated image appears invalid or truncated (size < 1KB)")

            # Create storage path with the generated content ID
            company_id = planner_info.get('company_id', 'unknown')
            # Choose file extension based on mime type
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/webp": ".webp",
            }
            file_ext = ext_map.get(mime_type, ".png")
            path = f"content/{company_id}/{content_id}{file_ext}"
            
            # Upload image to Firebase Storage (this function will handle cleanup)
            upload_t0 = time.perf_counter()
            url = await upload_image(image_bytes, path, content_type=mime_type)
            upload_ms = int((time.perf_counter() - upload_t0) * 1000)

            # Clear image bytes from memory immediately after upload
            del image_bytes
            image_bytes = None
            gc.collect()

            # Save metadata to Firestore with additional info
            additional_data = {
                "company_id": planner_info.get('company_id'),
                "channel": planner_info.get('channel'),
            }

            channel = planner_info["channel"].lower()
            company_id = planner_info.get('company_id')
            
            total_ms = int((time.perf_counter() - total_t0) * 1000)
            # logger.info(
            #     "image_pipeline: company_id=%s channel=%s content_id=%s "
            #     "gen_ms=%s upload_ms=%s total_ms=%s mime=%s path=%s",
            #     company_id, channel, content_id, gen_ms, upload_ms, total_ms, mime_type, path,
            # )

            return url
            
        except Exception as e:
            if image_bytes is not None:
                del image_bytes
                gc.collect()
            raise e

    async def create_company_image(self, planner_info: dict):
        """
        Keep image-generation routing independent of optional controller package imports.
        This function mirrors controllers.company_controller.create_company_image behavior.
        """
        try:
            url = await self.process_company(planner_info)
            return {"status": "success", "image_url": url}
        except Exception as e:
            logger.error(f"Error creating company image: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_company_image: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def generate_social_image(self, company_id, data, channel, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            planner_info = {
                "image_prompt": data.image_prompt,
                "company_id": company_id,
                "channel": channel,
                "aspect_ratio": data.aspect_ratio,
            }

            result = await self.create_company_image(planner_info)

            if isinstance(result, JSONResponse):
                error_content = (
                    result.body.decode("utf-8")
                    if hasattr(result.body, "decode")
                    else str(result.body)
                )

                try:
                    error_msg = json.loads(error_content).get(
                        "message",
                        "Unknown error",
                    )
                except Exception:
                    error_msg = error_content

                raise HTTPException(
                    status_code=result.status_code,
                    detail=error_msg,
                )

             

            UsageService(self.db).increment_image_generation(
                company_id_int,
                user["uid"],
                channel,
            )

            return result

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error generating image: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_social_image: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
    
    def _raise_if_generation_failed(self, result):
        if not isinstance(result, JSONResponse):
            return

        error_content = (
            result.body.decode("utf-8")
            if hasattr(result.body, "decode")
            else str(result.body)
        )

        try:
            error_msg = json.loads(error_content).get(
                "message",
                "Unknown error",
            )
        except Exception:
            error_msg = error_content

        raise HTTPException(
            status_code=result.status_code,
            detail=error_msg,
        )
    
    async def parse_regenerate_request(
        self,
        request,
     ) -> content_schema.RegenerateContentRequest:

        content_type = request.headers.get("content-type", "")
        body_bytes = await request.body()

        if "application/json" in content_type:
            return await self._parse_json_request(body_bytes)

        if (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        ):
            return await self._parse_form_request(request)

        raise HTTPException(
            status_code=415,
            detail="Content-Type must be application/json or application/x-www-form-urlencoded",
        )
    
    async def regenerate_image(self, company_id, request, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            content = await self.parse_regenerate_request(request)

            company, image_analysis = (
                self.contentrepo.get_company_with_image_analysis(company_id)
            )

            image_prompt = await GPTservice().generate_image_prompt(
                content.caption,
                content.hashtags,
                content.overlay_text,
                self.contentrepo.get_image_analysis_prompt_data(image_analysis),
                content.image_type,
            )

            result = await self.create_company_image(
                {
                    "image_prompt": image_prompt["image_prompt"],
                    "channel": content.channel,
                    "aspect_ratio": content.aspect_ratio,
                }
            )

            self._raise_if_generation_failed(result)

            UsageService(self.db).increment_image_generation(
                company.id,
                user["uid"],
                content.channel,
            )

            return result

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error regenerating image: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"regenerate_image: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_instagram_post(self, company_id, post_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            cache_key = f"instagram_post_{company_id}_{post_id}"

            cached = await redis.redis_get(cache_key)
            if cached:
                return cached

            post = self.contentrepo.get_post(company_id, post_id)

            post_data = serialization.sqlalchemy_to_dict(post)
            if post.status == "published":
                published = self.published_instagram_ids_by_image_url(
                    company_id_int, [post.image_url]
                )
                ids = published.get(post.image_url) or {}
                post_data["platform_post_id"] = ids.get("platform_post_id")
                post_data["ig_user_id"] = ids.get("ig_user_id")
                post_data["page_id"] = ids.get("page_id")
           

            await redis.redis_set(
                cache_key,
                json.dumps(post_data),
            )

            return {
                "status": post.status,
                "data": post_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching Instagram post: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_instagram_post: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_facebook_post(self, company_id, post_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            cache_key = f"facebook_post_{company_id}_{post_id}"

            cached = await redis.redis_get(cache_key)
            if cached:
                return cached

            post = self.contentrepo.get_post(company_id, post_id)

            post_data = serialization.sqlalchemy_to_dict(post)
            if post.status == "published":
                platform_ids = self.platform_post_ids_by_image_url(
                    company_id_int, [post.image_url]
                )
                post_data["platform_post_id"] = platform_ids.get(post.image_url)

            await redis.redis_set(
                cache_key,
                json.dumps(post_data),
            )

            return {
                "status": post.status,
                "data": post_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching Facebook post: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_facebook_post: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            raise error.InternalServerError(message="Internal server error")


    async def get_linkedin_post(self, company_id, post_id, user):
        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            cache_key = f"linkedin_post_{company_id}_{post_id}"

            cached = await redis.redis_get(cache_key)
            if cached:
                return cached

            post = self.contentrepo.get_post(company_id, post_id)

            post_data = serialization.sqlalchemy_to_dict(post)

            await redis.redis_set(
                cache_key,
                json.dumps(post_data),
            )

            return {
                "status": post.status,
                "data": post_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching LinkedIn post: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_linkedin_post: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_social_media_posts_with_theme_index(
        self,
        company_uuid,
        month_id,
        channel,
        theme_index,
     ):
        try:
            channel = channel.lower().strip()

            if channel not in ("instagram", "facebook", "linkedin"):
                raise error.BadRequest("Invalid channel")

            company_id = self.companyrepo.get_company_id_from_uuid(
                company_uuid
            )

            posts = self.contentrepo.get_posts_by_theme(
                company_id,
                month_id,
                theme_index,
            )

            return {
                "data": [
                    serialization.sqlalchemy_to_dict(post)
                    for post in posts
                ]
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching posts: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_social_media_posts_with_theme_index: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_all_instagram_posts(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db)

            cache_key = f"all_instagram_posts_{company_uuid}"

            cached_posts = await redis.redis_list_get_all(cache_key)
            cache_has_published_ids = bool(cached_posts) and all(
                "platform_post_id" in p and "ig_user_id" in p and "page_id" in p
                for p in cached_posts
                if isinstance(p, dict) and p.get("status") == "published"
            )
            if cache_has_published_ids:
                return {
                    "data": cached_posts,
                }

            posts = self.contentrepo.get_posts_by_channel(
                company_id_int,
                "instagram",
            )

            posts_data = [
                serialization.sqlalchemy_to_dict(post)
                for post in posts
            ]

            published = self.published_instagram_ids_by_image_url(
                company_id_int,
                [post.image_url for post in posts if post.status == "published"]
            )
            for post_data in posts_data:
                if post_data.get("status") == "published":
                    ids = published.get(post_data.get("image_url")) or {}
                    post_data["platform_post_id"] = ids.get("platform_post_id")
                    post_data["ig_user_id"] = ids.get("ig_user_id")
                    post_data["page_id"] = ids.get("page_id")

            if posts_data:
                await redis.redis_list_set_all(
                    cache_key,
                    posts_data,
                )

            return {
                "data": posts_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching posts: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_all_instagram_posts: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_all_facebook_posts(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db)

            cache_key = f"all_facebook_posts_{company_uuid}"

            cached_posts = await redis.redis_list_get_all(cache_key)
            cache_has_platform_ids = bool(cached_posts) and all(
                "platform_post_id" in p
                for p in cached_posts
                if isinstance(p, dict) and p.get("status") == "published"
            )
            if cache_has_platform_ids:
                return {
                    "data": cached_posts,
                }

            posts = self.contentrepo.get_posts_by_channel(
                company_id_int,
                "facebook",
            )

            posts_data = [
                serialization.sqlalchemy_to_dict(post)
                for post in posts
            ]
            platform_ids = self.platform_post_ids_by_image_url(
                company_id_int,
                [post.image_url for post in posts if post.status == "published"]
            )
            for post_data in posts_data:
                if post_data.get("status") == "published":
                    post_data["platform_post_id"] = platform_ids.get(post_data.get("image_url"))

            if posts_data:
                await redis.redis_list_set_all(
                    cache_key,
                    posts_data,
                )

            return {
                "data": posts_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching posts: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_all_facebook_posts: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_all_linkedin_posts(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db)

            cache_key = f"all_linkedin_posts_{company_uuid}"

            cached_posts = await redis.redis_list_get_all(cache_key)
            if cached_posts:
                return {
                    "data": cached_posts,
                }

            posts = self.contentrepo.get_posts_by_channel(
                company_id_int,
                "linkedin",
            )

            posts_data = [
                serialization.sqlalchemy_to_dict(post)
                for post in posts
            ]

            if posts_data:
                await redis.redis_list_set_all(
                    cache_key,
                    posts_data,
                )

            return {
                "data": posts_data,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error fetching posts: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_all_linkedin_posts: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def create_scheduled_posts(self, company_id, data, background_task, user):
        try:
            ## check if the user has access to the company
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            task_name = "market_planner.generate_draft_posts"
            task = celery_app.send_task(task_name, args=[company_id, data.model_dump(), user, company_id_int])
            print(task)
            background_task.add_task(celery_utils.background_on_message, task)

            ##invalidate the cache
            if await redis.redis_delete(f"all_instagram_posts_{company_id}"):
                logger.info(f"✅ Instagram posts cache invalidated for company {company_id}")
               
            if await redis.redis_delete(f"all_facebook_posts_{company_id}"):
                logger.info(f"✅ Facebook posts cache invalidated for company {company_id}")
               
            if await redis.redis_delete(f"all_linkedin_posts_{company_id}"):
                logger.info(f"✅ LinkedIn posts cache invalidated for company {company_id}")
                
            if await redis.redis_delete(f"all_blog_posts_{company_id}"):
                logger.info(f"✅ Blogs cache invalidated for company {company_id}")
           
            if await redis.redis_delete(f"all_newsletters_{company_id}"):
                logger.info(f"✅ Newsletters cache invalidated for company {company_id}")
            


            return {
                "status": "success",
                "message": "Scheduled posts generation task sent to Celery",
                "task_id": task.id
            }
        except HTTPException:
            raise  # Re-raise HTTPException (like 403, 404) to let FastAPI handle it properly
        except Exception as e:
            logger.error(f"Error creating scheduled posts for company {company_id}: {str(e)}")
            ## record the log in the databas
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_scheduled_posts: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def save_social_post_to_db(self, company_id, data, channel, background_task, user):
        try:
            ## check if the user has access to the company
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
            
            final_data = content_tables.Post(
                company_id = company_id_int,
                channel = channel, 
                image_url = data.image_url,
                caption = data.caption,
                hashtags = data.hashtags,
                scheduled_datetime = data.scheduled_datetime.isoformat() if data.scheduled_datetime else None,
                status = data.status,
                month_id = data.month_id,
                theme_index = data.theme_index,
                overlay_text = data.overlay_text,
                scheduled_month = data.scheduled_month,
            )
            
            task_name = "market_planner.save_post"
            task = celery_app.send_task(task_name, args=[company_id_int, company_id, serialization.sqlalchemy_to_dict(final_data), channel])
            print(task)
            background_task.add_task(celery_utils.background_on_message, task)
            

        
            return {
                "status": "success",
                "message": "Post updated successfully",
                "task_id": task.id
            }

        except HTTPException:
            raise  # Re-raise HTTPException (like 403, 404) to let FastAPI handle it properly
        except Exception as e:
            logger.error(f"Error saving social post to db: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"save_social_post_to_db: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def update_social_post_to_db(self, company_id, post_id, data, channel, background_task, user):
        try:
            ## check if the user has access to the company
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            # Get company integer ID from UUID
            channel = channel
            task_name = "market_planner.update_post"
            task = celery_app.send_task(task_name, args=[company_id, post_id, channel, data.model_dump(exclude_unset=True)])
            print(task)
            background_task.add_task(celery_utils.background_on_message, task)
        
            # logger.info(f"{channel} post '{post_id}' updated successfully")
            return {
                "status": "success",
                "message": f"{channel} post {post_id} for Company {company_id} updated",
                "task_id": task.id
            }
        except HTTPException:
            raise  # Re-raise HTTPException (like 403, 404) to let FastAPI handle it properly
        except Exception as e:
            logger.error(f"Error updating social post to db: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_social_post_to_db: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def delete_social_post(self, company_id, post_id, channel, background_task, user):
        try:
            ## check if the user has access to the company
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)

            task_name = "market_planner.delete_post"
            task = celery_app.send_task(task_name, args=[company_id, post_id])
            print(task)
            background_task.add_task(celery_utils.background_on_message, task)

            # logger.info(f"{channel} post '{post_id}' deleted successfully")
            return {"status": "success", "message": "Post deleted successfully", "task_id": task.id}
        except HTTPException:
            raise  # Re-raise HTTPException (like 403, 404) to let FastAPI handle it properly
        except Exception as e:
            logger.error(f"Error deleting social post: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"delete_social_post: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_image_bytes(self, image_url: str) -> bytes:
        """
        Download image from URL and return raw bytes.
        HTTPS-only with DNS/IP SSRF checks, redirect re-validation, and size cap.
        """
        try:
            return url_service.download_https_bytes(
                image_url,
                timeout=constants.IMAGE_DOWNLOAD_TIMEOUT,
                max_bytes=constants.MAX_IMAGE_DOWNLOAD_BYTES,
                headers={"User-Agent": "Marketing-App/1.0"},
            )
        except url_service.SafeUrlFetchError as e:
            # logger.warning(f"Rejected or failed image URL fetch: {e}")
            raise error.BadRequest(str(e))
        except Exception as e:
            # logger.error(f"Failed to process image bytes from {image_url}: {str(e)}")
            logger.error(f"Failed to process image bytes from {image_url}: {str(e)}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_image_bytes: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def process_product_image(self, product_image: Optional[UploadFile]) -> tuple[bytes, str, Image.Image]:
        """
        Process the uploaded image and return image bytes, format, and PIL Image.
        """
        if not product_image:
            raise error.BadRequest(message="Product image is required")
        
        try:
            # Read the image file
            contents = await product_image.read()
            
            # Validate image using PIL
            image = Image.open(io.BytesIO(contents))
            
            # Basic image validation
            if image.size[0] < 100 or image.size[1] < 100:
                raise error.BadRequest(
                    message="Image dimensions too small. Minimum 100x100 pixels required."
                )
            
            # Get image format
            image_format = image.format.lower() if image.format else "jpeg"
            
            return contents, image_format
            
        except Exception as e:
            # logger.error(f"Error processing product image: {str(e)}")
            logger.error(f"Error processing product image: {str(e)}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"process_product_image: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def _parse_product_image_slots(data) -> tuple[
        tuple[Optional[UploadFile], Optional[str]],
        tuple[Optional[UploadFile], Optional[str]],
     ]:
        """
        Manually parse multipart form to handle Swagger sending empty string for optional file fields.
        Slot 1 (required downstream): product_image / product_image_file OR product_image_url.
        Slot 2 (optional): product_image_2 / product_image_file_2 OR product_image_url_2.
        Each slot returns (upload_file_or_none, url_or_none).
        """
        s1_file: Optional[UploadFile] = None
        s1_url: Optional[str] = None
        s2_file: Optional[UploadFile] = None
        s2_url: Optional[str] = None

        form = await data.form()
        for key, value in form.items():
            k = key.lower()
            if k in ("product_image", "product_image_file"):
                if isinstance(value, UploadFile) and value.filename:
                    s1_file = value
            elif k == "product_image_url" and isinstance(value, str) and value.strip():
                s1_url = value.strip()
            elif k in ("product_image_2", "product_image_file_2"):
                if isinstance(value, UploadFile) and value.filename:
                    s2_file = value
            elif k in ("product_image_url_2", "product_image_url2") and isinstance(value, str) and value.strip():
                s2_url = value.strip()

        return (s1_file, s1_url), (s2_file, s2_url)


    async def generate_posts_from_products(self, company_id, channel,data, month_id, aspect_ratio, user):

        (s1_file, s1_url), (s2_file, s2_url) = await self._parse_product_image_slots(data)

        try:
            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
            if not company_id_int:
                raise error.PermissionDenied("You are not authorized to access this company")


            ## get the company
            company_record = self.companyrepo.get_company_from_id(company_id_int)
            if not company_record:
                raise error.NotFound("Company not found")

            company_data = serialization.sqlalchemy_to_dict(company_record)
            company_payload = {
                "company_id": company_id_int,
                "company_name": company_data.get("company_name"),
                "company_info": company_data.get("company_info"),
                "industry": company_data.get("industry"),
                "address": company_data.get("address"),
                "target_group": company_data.get("target_group"),
                "tone_analysis": company_data.get("tone_analysis"),
            }

            ## get the theme
            theme_record = self.theme_repo.get_theme(company_id_int, month_id)
            if not theme_record:
                raise error.NotFound("Theme not found")
            theme_data = serialization.sqlalchemy_to_dict(theme_record)
            theme = theme_data.get("theme_title")

            async def _resolve_slot(
                slot_file: Optional[UploadFile], slot_url: Optional[str], slot_label: str
            ) -> tuple[bytes, str]:
                if slot_file and slot_url:
                    raise error.BadRequest(
                       f"For {slot_label}, provide only one of file upload or URL, not both",
                    )
                if slot_file and not slot_url:
                    return await self.process_product_image(slot_file)
                if slot_url and not slot_file:
                    data = await self.get_image_bytes(slot_url)
                    fmt = slot_url.split(".")[-1].split("?")[0]
                    return data, fmt
                raise error.BadRequest(
                    f"{slot_label}: either a file upload or image URL must be provided",
                )

            if s1_file and s1_url:
                raise error.BadRequest(
                    "For the first product, provide only one of product_image_file (or product_image) or product_image_url, not both",
                )
            # Slot 1 required; slot 2 optional (up to two products)
            if not s1_file and not s1_url:
                raise error.BadRequest(
                    "Provide product_image_file (or product_image) or product_image_url for the first product",
                )
            if s2_file and s2_url:
                raise error.BadRequest(
                  "For the second product, provide only one of product_image_file_2 or product_image_url_2, not both",
                )

            product_images: list[tuple[bytes, str]] = [await _resolve_slot(s1_file, s1_url, "First product image")]
            if s2_file or s2_url:
                product_images.append(await _resolve_slot(s2_file, s2_url, "Second product image"))

            # Default to 1:1 (square) when aspect_ratio is omitted or blank
            resolved_aspect_ratio = (aspect_ratio or "square").strip().lower() or "square"

            post = await GeminiService.generate_post_from_product_with_gemini(
                company_payload=company_payload,
                product_images=product_images,
                theme=theme,
                channel=channel,
                aspect_ratio=resolved_aspect_ratio,
            )
            post_data = GPTservice().generate_post_metadata(
                company_payload=company_payload,
                product_images=product_images,
                theme=theme,
                channel=channel,
            )
            image_bytes = base64.b64decode(post.image_data)
            mime_type = f"image/{post.format}" if post.format in ("png", "jpeg", "jpg", "webp") else "image/png"
            post_image_url = await firebase_config.upload_image_to_firebase(image_bytes, company_id, mime_type)

            return content_schema.GeneratePostsFromProductsResponse(
                caption=post_data.get("caption"),
                hashtags=post_data.get("hashtags"),
                image_url=post_image_url,
            )
            
        except Exception as e:
            ## record the log in the database
            logger.error(f"Error generating posts from products: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"generate_posts_from_products: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def edit_image(self, company_id, payload, user):
        edit_instruction = (payload.edit_instruction or "").strip()
        if not edit_instruction:
            raise error.BadRequest("edit_instruction is required")

        image_url = (payload.image_url or "").strip()
        if not image_url:
            raise error.BadRequest("image_url is required")

        channel = (payload.channel or "").lower().strip()
        if channel not in constants.VALID_CHANNELS:
            raise error.BadRequest(
                f"Invalid channel. Must be one of: {', '.join(constants.VALID_CHANNELS)}"
            )

        try:
            company_id_int = auth.check_user_company_access(
                company_id,
                user["uid"],
                self.db,
            )

            image_bytes = await self.get_image_bytes(image_url)

            if (
                not image_bytes
                or len(image_bytes) < constants.MIN_IMAGE_SIZE
            ):
                raise error.InternalServerError(
                    "Could not download a valid source image."
                )

            edited = await GeminiService.generate_edited_image(
                image_bytes=image_bytes,
                edit_instruction=edit_instruction,
                channel=channel,
                aspect_ratio=payload.aspect_ratio,
            )

            if not edited:
                raise error.InternalServerError(
                    "Failed to edit image."
                )

            edited_bytes, mime_type = edited

            if (
                not edited_bytes
                or len(edited_bytes) < constants.MIN_IMAGE_SIZE
            ):
                raise error.InternalServerError(
                    "Edited image appears invalid."
                )

            file_ext = constants.MIME_TYPE_EXT_MAP.get(
                mime_type,
                ".png",
            )

            path = (
                f"content/{company_id}/"
                f"{uuid.uuid4()}{file_ext}"
            )

            edited_url = await firebase_config.upload_image(
                edited_bytes,
                path,
                content_type=mime_type,
            )

            UsageService(self.db).increment_image_edit(
                company_id_int,
                user["uid"],
                channel,
            )

            return {
                "status": "success",
                "image_url": edited_url,
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error editing image: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"edit_image: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def generate_channel_posts(
        self,
        channel_name: str,
        post_count: int,
        company_id: str,
        planner_request,
        month_id: str,
        theme_index: int,
        scheduled_month: str,
        user: dict,
        generate_planner_func=None,
        generate_image_func=None,
        company_id_int: int = None
     ):
        # """Helper function to generate posts for a single channel"""
        posts = []
        
        for count in range(post_count):
            try:
        
                company_record = self.companyrepo.get_company_by_id(company_id_int)
                if not company_record:
                    raise Exception("Company not found")

                if channel_name == "newsletter":

                    company_data = serialization.sqlalchemy_to_dict(company_record)
                    newsletter = GPTservice().generate_newsletter(
                        company_data,
                        planner_request.theme_title,
                        planner_request.theme_description,
                        None
                    )
                    if not newsletter:
                        raise Exception("Newsletter returned None")

                    # generate_newsletter returns a dict (from json.loads), not a Pydantic model
                    # Exclude token_usage; add caller-provided fields
                    newsletter_columns = {"channel", "subject_line", "preheader", "greeting", "opening_paragraph", "main_content", "practical_tips_section", "call_to_action", "closing"}
                    newsletter_payload = {k: newsletter.get(k) for k in newsletter_columns}
                    newsletter_payload.update(
                        company_id=company_id_int,
                        theme_index=theme_index,
                        scheduled_datetime=None,
                        status="draft",
                        month_id=int(month_id) if month_id else None,
                    )

                    newsletter_post = NewsletterRepository(self.db).create_newsletter(newsletter_payload)
                    posts.append(newsletter_post.uuid)
                    # logger.info(f"✅ Generated newsletter {count+1}/{post_count} with ID: {newsletter_post.uuid}")

                elif channel_name == "blog":
                    # logger.info(f"Generating blog {count+1}/{post_count} for company {company_id}")
                    company_data = serialization.sqlalchemy_to_dict(company_record)
                    
                    blog_response = GPTservice().generate_blog(  # type: ignore
                        company_data,
                        theme=planner_request.theme_title,
                        theme_description=planner_request.theme_description,
                        regional_language=None,
                    )
                    
                    if not blog_response:
                        raise Exception("Blog returned None")
                    
                    # generate_blog returns a dict (from json.loads), not a Pydantic model
                    # sections is already a list of dicts [{"heading": "", "content": ""}]
                    sections_raw = blog_response.get("sections") or []
                    sections_list = [
                        {"heading": s.get("heading", ""), "content": s.get("content", "")}
                        for s in sections_raw
                        if isinstance(s, dict)
                    ]

                    blog_post = {
                            "company_id": company_id_int,
                            "title":blog_response.get("title") or "",
                            "meta_description":blog_response.get("meta_description") or "",
                            "introduction":blog_response.get("introduction") or "",
                            "sections":sections_list,
                            "conclusion":blog_response.get("conclusion") or "",
                            "call_to_action":blog_response.get("call_to_action") or "",
                            "theme_index":theme_index,
                            "scheduled_datetime":None,  # Set by spread_posts_over_month
                            "status":"draft",
                            "month_id":int(month_id) if month_id else None,
                        }

                    blog_post = BlogRepository(self.db).create_blog_post(**blog_post)
                    posts.append(blog_post.uuid)
                    # logger.info(f"✅ Generated blog {count+1}/{post_count} with ID: {blog_post.uuid}")

                else:
                    # logger.info(f"Generating {channel_name.title()} post {count+1}")
                    # logger.debug("[%s:%s] Calling planner", channel_name.title(), count + 1)
                    
                    # Generate planner - pass db instance
                    planner = await generate_planner_func(planner_request, company_id, self.db, user)
                    if not planner:
                        raise Exception("Planner returned None")
                    
                    # logger.info(f"{channel_name.title()} planner result received")
                    # logger.debug(f"[{channel_name.title()}:{count+1}] Planner response keys: {list(planner.keys())}")
                    
                    # Generate image
                    image_prompt = planner.get('image_prompt')
                    if not image_prompt:
                        raise Exception("No image prompt returned from planner")
                    
                    content_request = content_schema.ContentRequest(image_prompt=image_prompt)
                    # logger.debug(
                    #     f"[{channel_name.title()}:{count+1}] Image prompt preview: {image_prompt[:120]}{'...' if len(image_prompt) > 120 else ''}"
                    # )
                    
                    image_result = await generate_image_func(content_request, company_id, self.db, user)
                    
                    # Handle case where image_result might be a JSONResponse (error case)
                    if isinstance(image_result, JSONResponse):
                        # Extract error details from JSONResponse
                        try:
                            error_content = image_result.body.decode('utf-8') if hasattr(image_result.body, 'decode') else str(image_result.body)
                            error_dict = json.loads(error_content)
                            error_msg = error_dict.get('message', 'Unknown error during image generation')
                        except:
                            error_msg = f"Image generation failed with status {image_result.status_code}"
                        raise Exception(f"Image generation error: {error_msg}")
                    
                    # Ensure image_result is a dict before calling .get()
                    if not isinstance(image_result, dict):
                        raise Exception(f"Unexpected image_result type: {type(image_result)}, expected dict")
                    
                    image_url = image_result.get('image_url')
                    
                    if not image_url:
                        raise Exception("No image URL returned from image generation")
                    
                    # Prepare post data
                    # logger.debug(f"[{channel_name.title()}:{count+1}] Post data prepared for company {company_id}")
                    post_data = {
                        "company_id": company_id_int,
                        "channel": channel_name,
                        "image_url": image_url,
                        "caption": planner.get('caption', ''),
                        "hashtags": planner.get('hashtags', []),
                        "overlay_text": planner.get('overlay_text', ''),
                        "status": "draft",
                        "month_id": month_id,
                        "theme_index": theme_index,
                        "scheduled_month": scheduled_month
                    }
                    
                    # Check for existing posts and set variation index
                    existing_posts = ContentRepository(self.db).get_posts_by_company_id_and_month_id_and_theme_index(company_id_int, month_id, theme_index)
                    variation_index = len(existing_posts)
                    if variation_index > 0:
                        variation_index = variation_index + 1
                    else:
                        variation_index = 1
                    post_data["variation_index"] = variation_index
                    
                    post_record = ContentRepository(self.db).create_post(**post_data)

                    #calculate the usage with UsageMetric table
                    post_id = post_record.uuid
                    posts.append(post_id)
                    
                    # logger.debug(
                    #     f"[{channel_name.title()}:{count+1}] Post data keys persisted: {list(post_data.keys())} | "
                    #     f"Post ID: {post_id}"
                    # )
                    # logger.info(f"✅ Generated {channel_name.title()} post {count+1}/{post_count} with ID: {post_id}")
                
            except Exception as e:
                # logger.error(f"Failed to generate {channel_name.title()} post {count+1}: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Couldn't generate {channel_name.title()} post number {count+1} for company {company_id}: {str(e)}"
                )
        #invalidate cache
        if await redis.redis_delete(f"all_{channel_name}_posts_{company_id}"):
            logger.info(f"✅ all_{channel_name}_posts cache invalidated for company {company_id}")
            
        else:
            logger.warning(f"⚠️ Failed to invalidate all_{channel_name}_posts cache for company {company_id}")
  
        return posts



    #################################################### spread posts over month ##################################################
    @staticmethod
    def _get_scheduling_year(month: int) -> int:
        current_date = datetime.now(timezone.utc)

        if month < current_date.month:
            return current_date.year + 1

        return current_date.year


    async def spread_posts_over_month(
        self,
        posts: list,
        month_id: str,
        channel_name: str,
        company_id: str,
    ):
        if not posts:
            return True

        month = int(month_id)

        # Resolve company UUID → integer ID once.
        # Your original code was doing this inside the loop.
        company_id_int = self.company_repo.get_company_id_from_uuid(
            company_id
        )

        year = self._get_scheduling_year(month)

        total_days = constants.MONTH_DAYS[month]

        spacing = total_days / len(posts)

        for index, post_id in enumerate(posts):

            day_offset = int(index * spacing)

            day = min(
                day_offset + 1,
                total_days,
            )

            scheduled_datetime = datetime(
                year,
                month,
                day,
                10,
                0,
                tzinfo=timezone.utc,
            )

            post_record = self.repo.get_post_by_uuid(
                post_id=post_id,
                company_id=company_id_int,
                channel_name=channel_name,
            )

            if not post_record:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"{channel_name} post not found "
                        f"for company {company_id} "
                        f"and post ID {post_id}"
                    ),
                )

            self.repo.update_scheduled_datetime(
                post_record=post_record,
                scheduled_datetime=scheduled_datetime,
            )

        return True