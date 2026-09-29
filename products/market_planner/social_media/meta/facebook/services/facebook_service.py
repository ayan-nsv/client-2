from urllib.parse import urlencode
import time
import hmac
import hashlib
import base64
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session

from shared.utils.constants import constants
from shared.utils.error import error
from shared.utils.auth import auth
from products.market_planner.social_media.meta.facebook.configuration.facebook_client import FacebookClient
from products.market_planner.social_media.meta.facebook.repository.facebook_repo import FacebookRepository
from core.repository.company_repo import CompanyRepository
from shared.database.postgres import serialization
from shared.database.postgres.database_config import get_db
from products.market_planner.social_media.meta.facebook.tables import facebook_tables 
from shared.logger.log import setup_logger

logger = setup_logger(__name__)


class FacebookService:
    
    def __init__(self, db: Optional[Session] = None):
        self.client = FacebookClient()
        self.repo = FacebookRepository(db if db else get_db())

    def get_auth_url_facebook_instagram(self, company_id: str):
            # logger.info(f"[AUTH_URL_INSTAGRAM] Generating auth url for company_id={company_id}")

        if not constants.FACEBOOK_APP_ID or not constants.FACEBOOK_APP_SECRET:
            # logger.error("Facebook credentials not configured")
            raise error.InternalServerError( "Facebook credentials not configured")
        
        scopes = ",".join([
            "pages_manage_posts", "pages_show_list", "pages_read_engagement",
            "business_management", "instagram_basic", "instagram_content_publish"
        ])
        params = {
            "client_id": constants.FACEBOOK_APP_ID,
            "redirect_uri": constants.FACEBOOK_REDIRECT_URI,
            "scope": scopes,
            "response_type": "code",
            "state": f"{company_id}|facebook_instagram",
        }
        fb_auth_url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
        return {
            "auth_url": fb_auth_url,
            "flow_type": "facebook_instagram",
            "description": "Connects Facebook pages and their linked Instagram business accounts"
        }

    def get_auth_url_facebook_only(company_id):
        if not constants.FACEBOOK_APP_ID or not constants.FACEBOOK_APP_SECRET:
            raise error.InternalServerError( "Facebook credentials not configured")
    
        scopes = ",".join([
            "pages_manage_posts", "pages_show_list", "pages_read_engagement", "business_management"
        ])
        params = {
            "client_id": constants.FACEBOOK_APP_ID,
            "redirect_uri": constants.FACEBOOK_REDIRECT_URI,
            "scope": scopes,
            "response_type": "code",
            "state": f"{company_id}|facebook_only",
        }
        fb_auth_url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
        return {
            "auth_url": fb_auth_url,
            "flow_type": "facebook_only",
            "description": "Connects Facebook pages only (no Instagram accounts)"
        }


    def get_auth_url(company_id):
        scopes = ",".join([
        "pages_manage_posts", "pages_show_list", "pages_read_engagement",
        "business_management", "instagram_basic", "instagram_content_publish"
        ])
        params = {
            "client_id": constants.FACEBOOK_APP_ID,
            "redirect_uri": constants.FACEBOOK_REDIRECT_URI,
            "scope": scopes,
            "response_type": "code",
            "state": f"{company_id}|facebook_instagram",
        }
        fb_auth_url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
        return {"auth_url": fb_auth_url}


    def facebook_callback(self, code, state, facebook_only, company_id, db, user):
            # only authorized users can access this endpoint
        if not user:
            raise error.PermissionDenied("Unauthorized")

        company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
        if not company_id_int:
            raise error.PermissionDenied(f"User does not have access to this company {company_id}")

        start_time = time.time()

        logger.info(
            "[FB_CALLBACK_START] state=%s facebook_only=%s code_length=%s",
            state,
            facebook_only,
            len(code) if code else 0,
        )

        try:

            # -----------------------------
            # Parse state
            # -----------------------------
            if "|" in state:
                company_id, state_flow_type = state.split("|", 1)
            else:
                company_id = state
                state_flow_type = None

            flow_type = "facebook_only" if facebook_only else (state_flow_type or "facebook_instagram")

            logger.info(
                "[FB_CALLBACK_STATE_PARSED] company_id=%s state_flow_type=%s resolved_flow=%s",
                company_id,
                state_flow_type,
                flow_type,
            )

            # -----------------------------
            # Exchange short-lived token
            # -----------------------------
            logger.info("[FB_TOKEN_EXCHANGE_START] exchanging code for short-lived token")

            tokens = self.client.exchange_code_for_token(code)

            # logger.debug("[FB_TOKEN_EXCHANGE_RESPONSE_KEYS] keys=%s", list(tokens.keys()))

            if "access_token" not in tokens:
                # logger.error(
                #     "[FB_TOKEN_EXCHANGE_FAILED] response=%s",
                #     tokens,
                # )
                raise error.BadRequest(tokens)

            # logger.info("[FB_TOKEN_EXCHANGE_SUCCESS]")

            # -----------------------------
            # Exchange long-lived token
            # -----------------------------
            # logger.info("[FB_LONG_TOKEN_EXCHANGE_START]")

            user_token_resp = self.client.exchange_for_long_lived_token(tokens["access_token"])

            # logger.debug(
            #     "[FB_LONG_TOKEN_RESPONSE_KEYS] keys=%s",
            #     list(user_token_resp.keys()),
            # )

            user_token = user_token_resp.get("access_token")

            if not user_token:
                # logger.error(
                #     "[FB_LONG_TOKEN_EXCHANGE_FAILED] response=%s",
                #     user_token_resp,
                # )
                raise error.BadRequest(user_token_resp)

            # logger.info("[FB_LONG_TOKEN_EXCHANGE_SUCCESS]")

            # -----------------------------
            # Fetch user profile
            # -----------------------------
            fb_client = self.client(user_token)

            # logger.info("[FB_FETCH_USER_START]")

            me = fb_client.get_me()

            # logger.debug("[FB_FETCH_USER_RESPONSE] %s", me)

            fb_user_id = me.get("id")

            # logger.info("[FB_FETCH_USER_SUCCESS] fb_user_id=%s", fb_user_id)

            # -----------------------------
            # Fetch pages
            # -----------------------------
            fields = "name,id,access_token"

            if flow_type == "facebook_instagram":
                fields += ",instagram_business_account{id,username,profile_picture_url,media_count}"

            # logger.info("[FB_FETCH_PAGES_START] fields=%s", fields)

            pages_resp = fb_client.get_accounts(fields=fields)

            # logger.debug("[FB_FETCH_PAGES_RESPONSE_KEYS] %s", list(pages_resp.keys()))

            if "data" not in pages_resp:
                # logger.error(
                #     "[FB_FETCH_PAGES_FAILED] response=%s",
                #     pages_resp,
                # )
                raise error.BadRequest(pages_resp)

            # logger.info("[FB_FETCH_PAGES_SUCCESS] page_count=%s", len(pages_resp["data"]))

            # -----------------------------
            # Process pages
            # -----------------------------
            pages = []
            instagram_accounts = []

            for index, page in enumerate(pages_resp["data"]):

                page_id = page.get("id")
                page_token = page.get("access_token")

                # logger.info(
                #     "[FB_PAGE_PROCESSING] index=%s page_id=%s has_token=%s",
                #     index,
                #     page_id,
                #     bool(page_token),
                # )

                try:

                    pic_resp = self.client(page_token).get_page_picture(page_id)

                    pic_url = pic_resp.get("data", {}).get("url")

                    # logger.debug(
                    #     "[FB_PAGE_PICTURE_FETCHED] page_id=%s has_picture=%s",
                    #     page_id,
                    #     bool(pic_url),
                    # )

                except Exception as e:

                    # logger.exception(
                    #     "[FB_PAGE_PICTURE_FAILED] page_id=%s error=%s",
                    #     page_id,
                    #     str(e),
                    # )

                    pic_url = None

                page_info = {
                    "id": page_id,
                    "name": page.get("name"),
                    "page_access_token": page_token,
                    "page_profile_picture_url": pic_url,
                }
                # DEBUG (optional but useful)
                # logger.info(
                #     "[FB_PAGE_TOKEN_CAPTURED] page_id=%s token_len=%s",
                #     page_id,
                #     len(page_token) if page_token else 0
                # )
                
                if flow_type == "facebook_instagram":

                    ig = page.get("instagram_business_account")

                    if ig and ig.get("id"):
                        # logger.info(
                        #     "[FB_PAGE_HAS_INSTAGRAM] page_id=%s ig_id=%s username=%s",
                        #     page_id,
                        #     ig.get("id"),
                        #     ig.get("username"),
                        # )
                        pass
                    else:
                        # logger.info("[FB_PAGE_NO_INSTAGRAM] page_id=%s", page_id)
                        pass

                    page_info["instagram_business_account"] = ig if ig and ig.get("id") else None

                pages.append(page_info)

            # logger.info("[FB_PAGE_PROCESSING_COMPLETE] processed_pages=%s", len(pages))

            # -----------------------------
            # Save to Firestore
            # -----------------------------
            # logger.info("[FB_FIRESTORE_SAVE_START] company_id=%s page_count=%s", company_id, len(pages))

            self.repo.save_all_accounts(
                company_id,
                user_token,
                fb_user_id,
                pages,
                flow_type,
                db
            )

            # logger.info("[FB_FIRESTORE_SAVE_SUCCESS]")

            # -----------------------------
            # Prepare masked response
            # -----------------------------
            masked_pages = []

            for p in pages:

                masked = {
                    "id": p["id"],
                    "name": p["name"],
                    "page_access_token": "********",
                    "page_profile_picture_url": p["page_profile_picture_url"],
                }

                if flow_type == "facebook_instagram":

                    ig = p.get("instagram_business_account")

                    masked["instagram_business_account"] = {**ig, "id": ig.get("id")} if ig else None

                masked_pages.append(masked)

            duration = round(time.time() - start_time, 3)

            # logger.info(
                # "[FB_CALLBACK_SUCCESS] company_id=%s pages=%s duration=%ss",
                # company_id,
                # len(masked_pages),
                # duration,
            # )

            return {
                "short_lived_token": "********",
                "user_long_token": "********",
                "flow_type": flow_type,
                "pages": masked_pages,
                "firestore_doc_path": "0",
            }

        except Exception as e:

            duration = round(time.time() - start_time, 3)

            # logger.exception(
            #     "[FB_CALLBACK_FATAL_ERROR] state=%s duration=%ss error=%s",
            #     state,
            #     duration,
            #     str(e),
            # )

            raise


    def parse_signed_request(signed_request: str) -> Dict[str, Any]:
        """Validate Facebook signed_request and return its payload dict."""
        try:
            if not constants.FACEBOOK_APP_SECRET:
                raise ValueError("APP_SECRET not configured")

            sig_b64, payload_b64 = signed_request.split(".", 1)

            def b64url_decode(s: str) -> bytes:
                s += "=" * ((4 - len(s) % 4) % 4)
                return base64.urlsafe_b64decode(s.encode())

            sig = b64url_decode(sig_b64)
            payload_json = b64url_decode(payload_b64)
            payload = json.loads(payload_json.decode())

            expected_sig = hmac.new(
                constants.FACEBOOK_APP_SECRET.encode(),
                msg=payload_b64.encode(),
                digestmod=hashlib.sha256,
            ).digest()

            if not hmac.compare_digest(sig, expected_sig):
                raise ValueError("Invalid signature")

            return payload
        except Exception as e:
            raise HTTPException(status_code=400, detail="Invalid signed_request")


    def save_account_to_db(
        self,
        company_id: str,
        account_type: str,
        platform_id: str,
        display_name: str,
        access_token: str,
        user_long_token: str,
        instagram_details: Optional[Dict[str, Any]] = None,
     ):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            account = self.repo.save_account(company_id=company_id_int, account_type=account_type, platform_id=platform_id, user_long_token=user_long_token)
            return serialization.sqlalchemy_to_dict(account)
        except Exception as e:
            raise error.InternalServerError(f"Failed to save account: {e}")

    def save_all_accounts(
        self,
        company_id: str,
        user_token: str,
        fb_user_id: str,
        pages: list[dict],
        flow_type: str,
     ):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            account = self.repo.save_all_accounts(company_id=company_id_int, user_token=user_token, fb_user_id=fb_user_id, pages=pages, flow_type=flow_type)
            return serialization.sqlalchemy_to_dict(account)
        except Exception as e:
            raise error.InternalServerError(f"Failed to save all accounts: {e}")


    def get_account(self, company_id: str) -> Optional[Dict[str, Any]]:
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            account = self.repo.get_account(company_id_int)
            return serialization.sqlalchemy_to_dict(account)
        except Exception as e:
            raise error.InternalServerError(f"Failed to get account: {e}")

    def get_all_pages(self, company_id: str):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            pages = self.repo.get_all_pages(company_id_int)
            return [serialization.sqlalchemy_to_dict(p) for p in pages]
        except Exception as e:
            raise error.InternalServerError(f"Failed to get all pages: {e}")

    def get_selected_page(self, company_id):
        try:
            page_record = self.repo.get_selected_page(company_id)
            return serialization.sqlalchemy_to_dict(page_record)
        except Exception as e:
            raise error.InternalServerError(f"Failed to get selected page: {e}")
        return serialization.sqlalchemy_to_dict(page_record)

    def get_instagram_accounts(self, company_id: str):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            accounts = self.repo.get_instagram_accounts(company_id_int)
            return [serialization.sqlalchemy_to_dict(a) for a in accounts]
        except Exception as e:
            raise error.InternalServerError(f"Failed to get instagram accounts: {e}")
        return [serialization.sqlalchemy_to_dict(a) for a in accounts]


    def delete_facebook_user_data(self, fb_user_id: str):
        if not self.repo.delete_facebook_user_data(fb_user_id):
            raise error.InternalServerError("Failed to delete Facebook user data")
        return True
    
    def resolve_platform_post_id(self ,fb_post: facebook_tables.FacebookInstaPost) -> Optional[str]:
        if fb_post.platform_post_id:
            return fb_post.platform_post_id
        response = fb_post.platform_response or {}
        if isinstance(response, dict):
            return response.get("post_id") or response.get("id")
        return None


    def platform_post_ids_by_image_url(
        self,
        company_id_int: int,
        image_urls: List[str],
    ) -> Dict[str, Optional[str]]:
        """Map planner image_url -> platform_post_id of the post published from that image."""
        urls = [url for url in image_urls if url]
        if not urls:
            return {}
        rows = (
            self.db.query(facebook_tables.FacebookInstaPost)
            .filter(
                facebook_tables.FacebookInstaPost.company_id == company_id_int,
                facebook_tables.FacebookInstaPost.status == "posted",
                facebook_tables.FacebookInstaPost.image_url.in_(urls),
            )
            .order_by(
                facebook_tables.FacebookInstaPost.posted_at.desc().nullslast(),
                facebook_tables.FacebookInstaPost.id.desc(),
            )
            .all()
        )
        mapping: Dict[str, Optional[str]] = {}
        for row in rows:
            if not row.image_url or row.image_url in mapping:
                continue
            mapping[row.image_url] = self.resolve_platform_post_id(row)
        return mapping


    def save_post(
        self,
        company_id: str,
        target: str,
        target_id: str,
        message: str | None,
        image_url: str | None,
        response_data: dict,
     ):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
                company_id
            )
            platform_post_id = None
            if isinstance(response_data, dict):
                platform_post_id = response_data.get("post_id") or response_data.get("id")

            post = self.repo.save_post(
                company_id=company_id_int,
                target=target,
                target_id=target_id,
                message=message,
                image_url=image_url,
                response_data=response_data,
            )

            return serialization.sqlalchemy_to_dict(post)
        except Exception as e:
            raise error.InternalServerError(f"Failed to save post: {e}")


    def get_published_posts(self, company_id: str):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            posts = self.repo.get_published_posts(company_id_int)
            return [serialization.sqlalchemy_to_dict(p) for p in posts]
        except Exception:
            raise error.InternalServerError("Failed to get published posts")


    def get_post(
        self, company_id: str, post_identifier: str
     ) :
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            post = self.repo.get_post(company_id_int, post_identifier)
            return serialization.sqlalchemy_to_dict(post)
        except Exception as e:
            raise error.InternalServerError(f"Failed to get post: {e}")


    def get_app_posts(self, company_id: str, page_id: str):
        try:    
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            posts = self.repo.get_app_posts(company_id_int, page_id)
            if not posts:
                return None
            return [serialization.sqlalchemy_to_dict(p) for p in posts]
        except Exception as e:
            raise error.InternalServerError(f"Failed to get app posts: {e}")


    def update_post_status(self, post_id: str, status: str):
        try:
            post = self.repo.update_post_status(post_id, status)
            return serialization.sqlalchemy_to_dict(post)
        except Exception as e:
            raise error.InternalServerError(f"Failed to update post status: {e}")


    def delete_post(self, company_id: str, post_identifier: str):
        """Delete post by id or platform_response id from Firestore. Returns True if deleted."""
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
        if not self.repo.delete_post(company_id_int, post_identifier):
            raise error.InternalServerError("Failed to delete post")
        return True



    def update_all_accounts(self, company_id: str):
        try:
            company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(company_id)
            if not self.repo.update_all_accounts(company_id_int):
                raise error.InternalServerError("Failed to update all accounts")
            return True
        except Exception as e:
            raise error.InternalServerError(f"Failed to update all accounts: {e}")


    def select_page(self, data):
        company_id_int = CompanyRepository(self.db).get_company_id_from_uuid(
            data.company_id
        )

        page = self.repo.select_page(
            company_id_int=company_id_int,
            page_id=data.page_id,
        )

        if not page:
            raise error.NotFound(
              "Page not found for this company",
            )

        return {
            "status": "success",
            "selected_page_id": data.page_id,
        }
    
    def publish_post(self, data, user):
        if not auth.check_user_company_access(data.company_id, user["uid"], self.db):
            raise error.PermissionDenied("You are not authorized to access this resource")

        data = self.get_account(data.company_id)
        if not data:
            raise error.BadRequest("Accounts not found")
        
    
        token = None
        if data.target == "page":
            pages = self.get_all_pages(data.company_id)
            for page in pages:
                if str(page.get("page_id")) == str(data.id):
                    token = page.get("page_access_token")
                    break

        elif data.target == "instagram":
            insta_accounts = self.get_instagram_accounts(data.company_id)
            for account in insta_accounts:
                if account.get("ig_user_id") == data.id:
                    token = account.get("access_token")
                    break
        token = token or data.get("user_long_token")
        if not token:
            raise error.BadRequest("Token not found")

        fb_client = FacebookClient(token)
        if data.target == "page":
            resp = fb_client.publish_fb_post(data.id, data.message, data.image_url)
        elif data.target == "instagram":
            if not data.image_url:
                raise error.BadRequest("image_url required for Instagram")
            
            media_resp = fb_client.create_ig_media(data.id, data.image_url, data.message or "")
            creation_id = media_resp.get("id")
            if not creation_id:
                raise error.BadRequest(media_resp)
            
            # Poll for status
            ready = False
            for _ in range(20):
                status = fb_client.get_media_status(creation_id)
                if status.get("status_code") == "FINISHED":
                    ready = True
                    break
                elif status.get("status_code") == "ERROR":
                    raise error.BadRequest("Media processing failed")
                time.sleep(3)
            
            if not ready:
                raise error.BadRequest("Media not ready")
            
            resp = fb_client.publish_ig_media(data.id, creation_id)
            if "error" in resp and resp["error"].get("error_subcode") == 2207027:
                time.sleep(5)
                resp = fb_client.publish_ig_media(data.id, creation_id)
        else:
            raise error.BadRequest("Invalid target")

        if "id" not in resp and "id" not in (resp.get("platform_response") or {}):
            # Handle some cases where resp might be wrapped or error
            if "error" in resp:
                raise error.BadRequest(resp)

        post_id = self.save_post(data.company_id, data.target, data.id, data.message, data.image_url, resp)
        
        # Re-construct response doc to match original
        now = datetime.now(timezone.utc)
        response_doc = {
            "id": post_id,
            "company_id": data.company_id,
            "target": data.target,
            "target_id": data.id,
            "message": data.message,
            "image_url": data.image_url,
            "status": "posted",
            "created_at": now.isoformat(),
            "platform_response": resp,
        }
        if data.target != "instagram":
            response_doc["updated_at"] = now.isoformat()
        else:
            # Instagram original response doc structure was slightly different
            response_doc = {
                "id": post_id,
                "company_id": data.company_id,
                "target": data.target,
                "target_id": data.id,
                "message": data.message,
                "image_url": data.image_url,
                "status": "posted",
                "created_at": now.isoformat(),
                "platform_response": resp,
            }

        return {
            "post": response_doc
        }

    def get_facebook_account(self, company_id: str, user):
        # only authorized users can access this endpoint
        try:
            if not user:
                raise error.PermissionDenied("Unauthorized")

            company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db)
            if not company_id_int:
                raise error.PermissionDenied(f"User does not have access to this company {company_id}")

            account = self.repo.get_facebook_account(company_id_int)
            return serialization.sqlalchemy_to_dict(account) 
        
        except Exception as e:
            raise error.InternalServerError(f"Failed to get facebook account: {e}")






















