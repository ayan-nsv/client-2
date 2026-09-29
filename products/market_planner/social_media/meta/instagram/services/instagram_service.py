import httpx
import asyncio
from sqlalchemy.orm import Session
from fastapi import  HTTPException
from typing import Optional, List, Dict

from shared.utils.auth import auth
from core.repository.company_repo import CompanyRepository
from shared.database.postgres import serialization
from products.market_planner.social_media.meta.instagram.repository.instagram_repo import InstagramRepository
from shared.utils.error import error
from shared.utils.constants import constants
from products.market_planner.social_media.meta.instagram.tables import instagram_tables
from products.market_planner.social_media.meta.facebook.tables import facebook_tables

class InstagramService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = InstagramRepository(db)
        self.company_repo = CompanyRepository(db)

    def save_instagram_account(
        self,
        company_id: str,
        ig_user_id: str,
        username: str,
        profile_picture_url: str,
        account_type: str,
        media_count: int,
        long_lived_token: str,
        expires_in: int,
     ):
        company_id_int = self.company_repo.get_company_id_from_uuid(company_id)

        try:
            account = self.repo.save_instagram_account(
                company_id_int=company_id_int,
                ig_user_id=ig_user_id,
                username=username,
                profile_picture_url=profile_picture_url,
                account_type=account_type,
                media_count=media_count,
                long_lived_token=long_lived_token,
                expires_in=expires_in,
            )

            return serialization.sqlalchemy_to_dict(account)

        except Exception:
            raise


    def deactivate_insta_account(self, company_id: str, user):
        if not user:
            raise error.PermissionDenied("Unauthorized")

        company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
        if not company_id_int:
            raise error.PermissionDenied(f"User does not have access to this company {company_id}")

        try:
            self.repo.deactivate_insta_account(company_id_int)
            return {
                "status": "disconnected",
                "message": "Instagram account disconnected."
            }
        except Exception as e:
            raise error.InternalServerError(f"Error logging out Instagram: {str(e)}")

    def get_insta_account(self, company_id: str, user):
        company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
        if not company_id_int:
            raise error.PermissionDenied(f"User does not have access to this company {company_id}")

        return self.repo.get_instagram_account_by_company_id(company_id_int)



    async def wait_until_media_ready(media_id: str, access_token: str, base_url: str, timeout_sec: int = 60):
        status_url = f"{base_url}/{media_id}"
        params = {
            "fields": "status_code",
            "access_token": access_token,
        }

        start = asyncio.get_event_loop().time()
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                resp = await client.get(status_url, params=params)
                if resp.status_code != 200:
                    # logger.error("Status check failed: status=%s", resp.status_code)
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail={"stage": "check_status", "error": resp.json()},
                    )

                data = resp.json()
                status = data.get("status_code")
                # logger.info(f"Container {media_id} status_code={status}")

                if status == "FINISHED":
                    return

                if asyncio.get_event_loop().time() - start > timeout_sec:
                    raise HTTPException(
                        status_code=504,
                        detail=f"Media container not ready after {timeout_sec}s, status={status}",
                    )

                await asyncio.sleep(3)


    async def instagram_post(self, request: dict, user: dict):
        if not user:
            raise error.PermissionDenied("Unauthorized")

        company_id_int = auth.check_user_company_access(request.company_id, user["uid"], self.db)
        if not company_id_int:
            raise error.PermissionDenied(f"User does not have access to this company {request.company_id}")

        try:
            insta_account = self.repo.get_insta_account(request.company_id)

            if not insta_account:
                raise error.NotFound("Instagram account not found")

            insta_account_id = insta_account.get("id")
            stored_user_id = str(insta_account.get("ig_user_id") or "").strip()
            access_token = (insta_account.get("access_token") or "").strip()

            # 🔥 NEW: detect account type
            is_fb_connected = bool(insta_account.get("facebook_insta_page_id"))

            if not access_token:
                raise error.BadRequest("No access token stored for this Instagram account")

            if stored_user_id and stored_user_id != request.ig_user_id:
                raise error.BadRequest("user_id does not match stored Instagram account")

            # 🔥 NEW: choose correct base URL
            base_url = constants.GRAPH_FB_BASE if is_fb_connected else constants.GRAPH_IG_BASE

            # logger.info("FB connected: %s", is_fb_connected)

            # -----------------------------
            # Step 1: Create media container
            # -----------------------------
            create_media_url = f"{base_url}/{request.ig_user_id}/media"

            create_params = {
                "image_url": request.image_url,
                "caption": request.caption,
                "access_token": access_token,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                create_resp = await client.post(create_media_url, params=create_params)

            # logger.info(...)

            if create_resp.status_code != 200:
                raise error.InternalServerError(
                    f"Failed to create media container: {create_resp.text}"
                )

            media_data = create_resp.json()
            media_id = media_data.get("id")

            if not media_id:
                raise error.InternalServerError("No media ID returned from /media")

            # logger.info(f"Media container created: {media_id}")

            # -----------------------------
            # Wait until ready
            # -----------------------------
            await self.wait_until_media_ready(media_id, access_token, base_url)

            # -----------------------------
            # Step 2: Publish media
            # -----------------------------
            publish_url = f"{base_url}/{request.ig_user_id}/media_publish"

            publish_params = {
                "creation_id": media_id,
                "access_token": access_token,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                publish_resp = await client.post(publish_url, params=publish_params)

            # logger.info(...)

            if publish_resp.status_code != 200:
                raise error.InternalServerError(
                    f"Failed to publish media: {publish_resp.text}"
                )

            publish_data = publish_resp.json()
            post_id = publish_data.get("id")

            # -----------------------------
            # Save post
            # -----------------------------
            post_doc = instagram_tables.InstagramPost(
                company_id=request.company_id,
                instagram_account_id=insta_account_id,
                caption=request.caption,
                image_url=request.image_url,
                media_id=media_id,
                platform_post_id=post_id,
                status="posted",
                platform_response=publish_data
            )

            self.save_instagram_post(post_doc)

            return {
                "status": "success",
                "post_id": post_id,
                "media_id": media_id,
                "message": "Post published successfully!",
            }

        except HTTPException:
            raise
        except Exception as e:
            # logger.exception(f"🔥 Instagram post failed: {str(e)}")
            raise error.InternalServerError(f"Instagram post failed: {str(e)}")


    def get_instagram_posts(self, company_id: str):
        try:
            company_id_int = self.company_repo.get_company_id_from_uuid(company_id)
            posts = self.repo.get_instagram_posts(company_id_int)
            return [serialization.sqlalchemy_to_dict(post) for post in posts]
        except Exception as e:
            raise error.InternalServerError(f"Error getting Instagram posts: {str(e)}")

    def _resolve_instagram_platform_post_id(self, post: instagram_tables.InstagramPost) -> Optional[str]:
        if post.platform_post_id:
            return post.platform_post_id
        if post.media_id:
            return post.media_id
        response = post.platform_response or {}
        if isinstance(response, dict):
            return response.get("id") or response.get("post_id")
        return None


    def _facebook_page_id_for_business_account(
        self,
        account_type: Optional[str],
        page_id: Optional[str],
    ) -> Optional[str]:
        if account_type == "instagram_business_account":
            return page_id
        return None


    def published_instagram_ids_by_image_url(
        self,
        company_id_int: int,
        image_urls: List[str]

    ) -> Dict[str, Dict[str, Optional[str]]]:
        """Map planner image_url -> platform_post_id, ig_user_id, and Facebook page_id for published IG posts."""
        urls = [url for url in image_urls if url]
        if not urls:
            return {}

        rows = (
            self.db.query(
                instagram_tables.InstagramPost,
                instagram_tables.InstagramAccount.ig_user_id,
                instagram_tables.InstagramAccount.account_type,
                facebook_tables.FacebookInstaPage.page_id,
            )
            .join(
                instagram_tables.InstagramAccount,
                instagram_tables.InstagramPost.instagram_account_id == instagram_tables.InstagramAccount.id,
            )
            .outerjoin(
                facebook_tables.FacebookInstaPage,
                instagram_tables.InstagramAccount.facebook_insta_page_id == facebook_tables.FacebookInstaPage.id,
            )
            .filter(
                instagram_tables.InstagramPost.company_id == company_id_int,
                instagram_tables.InstagramPost.status == "posted",
                instagram_tables.InstagramPost.image_url.in_(urls),
            )
            .order_by(
                instagram_tables.InstagramPost.posted_at.desc().nullslast(),
                instagram_tables.InstagramPost.id.desc(),
            )
            .all()
        )
        mapping: Dict[str, Dict[str, Optional[str]]] = {}
        for post, ig_user_id, account_type, page_id in rows:
            if not post.image_url or post.image_url in mapping:
                continue
            mapping[post.image_url] = {
                "platform_post_id": self._resolve_instagram_platform_post_id(post),
                "ig_user_id": ig_user_id,
                "page_id": self._facebook_page_id_for_business_account(account_type, page_id),
            }

        missing = [url for url in urls if url not in mapping]
        if missing:
            fallback_rows = (
                self.db.query(
                    facebook_tables.FacebookInstaPost,
                    instagram_tables.InstagramAccount.ig_user_id,
                    instagram_tables.InstagramAccount.account_type,
                    facebook_tables.FacebookInstaPage.page_id,
                )
                .join(
                    instagram_tables.InstagramAccount,
                    facebook_tables.FacebookInstaPost.instagram_account_id == instagram_tables.InstagramAccount.id,
                )
                .outerjoin(
                    facebook_tables.FacebookInstaPage,
                    instagram_tables.InstagramAccount.facebook_insta_page_id == facebook_tables.FacebookInstaPage.id,
                )
                .filter(
                    facebook_tables.FacebookInstaPost.company_id == company_id_int,
                    facebook_tables.FacebookInstaPost.status == "posted",
                    facebook_tables.FacebookInstaPost.target == "instagram",
                    facebook_tables.FacebookInstaPost.image_url.in_(missing),
                )
                .order_by(
                    facebook_tables.FacebookInstaPost.posted_at.desc().nullslast(),
                    facebook_tables.FacebookInstaPost.id.desc(),
                )
                .all()
            )
            for post, ig_user_id, account_type, page_id in fallback_rows:
                if not post.image_url or post.image_url in mapping:
                    continue
                platform_post_id = post.platform_post_id
                response = post.platform_response or {}
                if not platform_post_id and isinstance(response, dict):
                    platform_post_id = response.get("id") or response.get("post_id")
                mapping[post.image_url] = {
                    "platform_post_id": platform_post_id,
                    "ig_user_id": ig_user_id,
                    "page_id": self._facebook_page_id_for_business_account(account_type, page_id),
                }
        return mapping

    def select_instagram_account(
        self,
        company_id: str,
        account_id: str,
        user: dict,
     ):
        company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
        if not company_id_int:
            raise error.PermissionDenied(f"User does not have access to this company {company_id}")

        account = self.repo.select_instagram_account(
            company_id_int=company_id_int,
            ig_user_id=account_id,
        )

        if not account:
            raise error.NotFound("Instagram account not found")

        return serialization.sqlalchemy_to_dict(account)




















        