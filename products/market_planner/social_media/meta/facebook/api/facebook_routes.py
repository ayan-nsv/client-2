from fastapi import APIRouter, HTTPException, Query, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Optional
from urllib.parse import urlparse
import time
from sqlalchemy.orm import Session



from products.market_planner.social_media.meta.facebook.configuration.facebook_client import FacebookClient
from shared.utils.constants import constants
from shared.database.postgres.database_config import get_db
from products.market_planner.social_media.meta.facebook.services.facebook_service import FacebookService
from products.market_planner.social_media.meta.facebook.configuration.facebook_client import FacebookClient
from products.market_planner.social_media.meta.facebook.schemas import facebook_schema
from shared.utils.auth import auth
from shared.utils.error import error
from shared.logger.log import setup_logger



logger = setup_logger("marketing-app")

router = APIRouter(prefix="/facebook")

@router.get("/auth_url/facebook_instagram", tags=["facebook"])
def get_auth_url_facebook_instagram(company_id: str = Query(..., description="Company ID for Firestore")):
    service = FacebookService()
    return service.get_auth_url_facebook_instagram(company_id)
    
@router.get("/auth_url/facebook_only", tags=["facebook"])
def get_auth_url_facebook_only(company_id: str = Query(..., description="Company ID for Firestore")):
    service = FacebookService()
    return service.get_auth_url_facebook_only(company_id)
    

@router.get("/auth_url", tags=["facebook"])
def get_auth_url(company_id: str = Query(..., description="Company ID for Firestore")):
    """
    Legacy endpoint - redirects to Facebook + Instagram flow.
    """
    service = FacebookService()
    return service.get_auth_url(company_id)
    


@router.get("/callback", tags=["facebook"])
def facebook_callback(
    code: str = Query(...),
    state: str = Query(...),
    facebook_only: bool = Query(False),
    company_id: str = Query(...),
    db: Session = Depends(get_db), 
    user: dict = Depends(auth.get_current_user)
 ):
    service = FacebookService(db)
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

        tokens = FacebookClient.exchange_code_for_token(code)

        logger.debug("[FB_TOKEN_EXCHANGE_RESPONSE_KEYS] keys=%s", list(tokens.keys()))

        if "access_token" not in tokens:
            logger.error(
                "[FB_TOKEN_EXCHANGE_FAILED] response=%s",
                tokens,
            )
            raise HTTPException(400, detail=tokens)

        logger.info("[FB_TOKEN_EXCHANGE_SUCCESS]")

        # -----------------------------
        # Exchange long-lived token
        # -----------------------------
        logger.info("[FB_LONG_TOKEN_EXCHANGE_START]")

        user_token_resp = FacebookClient.exchange_for_long_lived_token(tokens["access_token"])

        logger.debug(
            "[FB_LONG_TOKEN_RESPONSE_KEYS] keys=%s",
            list(user_token_resp.keys()),
        )

        user_token = user_token_resp.get("access_token")

        if not user_token:
            logger.error(
                "[FB_LONG_TOKEN_EXCHANGE_FAILED] response=%s",
                user_token_resp,
            )
            raise HTTPException(400, detail=user_token_resp)

        logger.info("[FB_LONG_TOKEN_EXCHANGE_SUCCESS]")

        # -----------------------------
        # Fetch user profile
        # -----------------------------
        fb_client = FacebookClient(user_token)

        logger.info("[FB_FETCH_USER_START]")

        me = fb_client.get_me()

        logger.debug("[FB_FETCH_USER_RESPONSE] %s", me)

        fb_user_id = me.get("id")

        logger.info("[FB_FETCH_USER_SUCCESS] fb_user_id=%s", fb_user_id)

        # -----------------------------
        # Fetch pages
        # -----------------------------
        fields = "name,id,access_token"

        if flow_type == "facebook_instagram":
            fields += ",instagram_business_account{id,username,profile_picture_url,media_count}"

        logger.info("[FB_FETCH_PAGES_START] fields=%s", fields)

        pages_resp = fb_client.get_accounts(fields=fields)

        logger.debug("[FB_FETCH_PAGES_RESPONSE_KEYS] %s", list(pages_resp.keys()))

        if "data" not in pages_resp:
            logger.error(
                "[FB_FETCH_PAGES_FAILED] response=%s",
                pages_resp,
            )
            raise HTTPException(400, detail=pages_resp)

        logger.info("[FB_FETCH_PAGES_SUCCESS] page_count=%s", len(pages_resp["data"]))

        # -----------------------------
        # Process pages
        # -----------------------------
        pages = []
        instagram_accounts = []

        for index, page in enumerate(pages_resp["data"]):

            page_id = page.get("id")
            page_token = page.get("access_token")

            logger.info(
                "[FB_PAGE_PROCESSING] index=%s page_id=%s has_token=%s",
                index,
                page_id,
                bool(page_token),
            )

            try:

                pic_resp = FacebookClient(page_token).get_page_picture(page_id)

                pic_url = pic_resp.get("data", {}).get("url")

                logger.debug(
                    "[FB_PAGE_PICTURE_FETCHED] page_id=%s has_picture=%s",
                    page_id,
                    bool(pic_url),
                )

            except Exception as e:

                logger.exception(
                    "[FB_PAGE_PICTURE_FAILED] page_id=%s error=%s",
                    page_id,
                    str(e),
                )

                pic_url = None

            page_info = {
                "id": page_id,
                "name": page.get("name"),
                "page_access_token": page_token,
                "page_profile_picture_url": pic_url,
            }
            # DEBUG (optional but useful)
            logger.info(
                "[FB_PAGE_TOKEN_CAPTURED] page_id=%s token_len=%s",
                page_id,
                len(page_token) if page_token else 0
            )
            
            if flow_type == "facebook_instagram":

                ig = page.get("instagram_business_account")

                if ig and ig.get("id"):
                    logger.info(
                        "[FB_PAGE_HAS_INSTAGRAM] page_id=%s ig_id=%s username=%s",
                        page_id,
                        ig.get("id"),
                        ig.get("username"),
                    )
                else:
                    logger.info("[FB_PAGE_NO_INSTAGRAM] page_id=%s", page_id)

                page_info["instagram_business_account"] = ig if ig and ig.get("id") else None

            pages.append(page_info)

        logger.info("[FB_PAGE_PROCESSING_COMPLETE] processed_pages=%s", len(pages))

        # -----------------------------
        # Save to Firestore
        # -----------------------------
        logger.info("[FB_FIRESTORE_SAVE_START] company_id=%s page_count=%s", company_id, len(pages))

        service.save_all_accounts(
            company_id,
            user_token,
            fb_user_id,
            pages,
            flow_type,
        )

        logger.info("[FB_FIRESTORE_SAVE_SUCCESS]")

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

        logger.info(
            "[FB_CALLBACK_SUCCESS] company_id=%s pages=%s duration=%ss",
            company_id,
            len(masked_pages),
            duration,
        )

        return {
            "short_lived_token": "********",
            "user_long_token": "********",
            "flow_type": flow_type,
            "pages": masked_pages,
            "firestore_doc_path": "0",
        }

    except Exception as e:

        duration = round(time.time() - start_time, 3)

        logger.exception(
            "[FB_CALLBACK_FATAL_ERROR] state=%s duration=%ss error=%s",
            state,
            duration,
            str(e),
        )

        raise


@router.post("/select_page", tags=["facebook"])
def select_page(payload: facebook_schema.SelectPageRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = FacebookService(db)
    return service.select_page(payload.model_dump_json())
    

@router.post("/publish", tags=["facebook"])
def publish_post(payload: facebook_schema.PublishPostRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = FacebookService(db)
    return service.publish_post(payload.model_dump_json(), user)
    

@router.get("/posts_published", tags=["facebook"])
def get_published_posts(company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = FacebookService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    return {"posts": service.get_published_posts(company_id)}

# @router.delete("/posts/{post_identifier}")
# def delete_post_by_id(post_identifier: str, company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):

#     service = FacebookService(db)
    # # only authorized users can access this endpoint
    # if not user:
    #     raise error.PermissionDenied("Unauthorized")

    # company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    # if not company_id_int:
    #     raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    # post_data, _ = service.get_post_from_firestore(company_id, post_identifier)
    # if not post_data:
    #     raise error.NotFound("Post not found")

    # platform_id = post_data.get("platform_response", {}).get("id") or post_identifier
    # target_id = post_data.get("target_id")

    # data = service.get_account(company_id)
    # token = next((p["page_access_token"] for p in data.get("pages", []) if p["id"] == target_id), None) if data else None
    # token = token or (data.get("user_long_token") if data else None)

    # deleted_from_platform = False
    # if token:
    #     resp = FacebookClient(token).delete_platform_post(platform_id)
    #     deleted_from_platform = resp.get("success", False)

    # service.delete_post(company_id, post_identifier)
    # return {
    #     "status": "deleted",
    #     "deleted_from_firestore": True,
    #     "deleted_from_platform": deleted_from_platform,
    # }

@router.delete("/delete_post", tags=["facebook"])
def delete_facebook_post(payload: facebook_schema.DeletePostRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = FacebookService(db)
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(payload.company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {payload.company_id}")

    data = service.get_account(payload.company_id)
    token = next((p["page_access_token"] for p in data.get("pages", []) if p["id"] == payload.page_id), None) if data else None
    token = token or (data.get("user_long_token") if data else None)
    
    if not token:
        raise error.NotFound("Token not found")
    
    resp = FacebookClient(token).delete_platform_post(payload.post_id)
    if resp.get("success"):
        return {
            "status": "success",
            "message": f"Post {payload.post_id} deleted successfully from Facebook",
            "platform_response": resp
        }
    raise error.BadRequest(resp)

@router.put("/edit_post", tags=["facebook"])
def edit_facebook_post(payload: facebook_schema.EditPostRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = FacebookService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(payload.company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {payload.company_id}")

    data = service.get_account(payload.company_id)
    token = next((p["page_access_token"] for p in data.get("pages", []) if p["id"] == payload.page_id), None) if data else None
    token = token or (data.get("user_long_token") if data else None)
    
    if not token:
        raise error.NotFound("Token not found")
    
    fb_client = FacebookClient(token)
    # Check if exists
    get_resp = fb_client.get_post(payload.post_id)
    if "error" in get_resp:
        raise error.BadRequest(get_resp)
    
    resp = fb_client.update_post_message(payload.post_id, payload.message)
    if resp.get("success"):
        return {
            "status": "success",
            "message": f"Post {payload.post_id} updated successfully",
            "previous_message": get_resp.get("message"),
            "new_message": payload.message,
            "platform_response": resp
        }
    raise error.BadRequest(resp)

@router.delete("/logout", tags=["facebook"])
def facebook_logout(company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = FacebookService(db)
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    data = service.get_account(company_id)
    if not data:
        return {"status": "not_found"}

    pages = data.get("pages", [])
    ig_accounts = [{"instagram_business_account": p.get("instagram_business_account")} for p in pages if p.get("instagram_business_account")]

    service.update_all_accounts(company_id)
    
    # Preservation of posts is already handled by NOT deleting them (as per previous request)
    return {"status": "disconnected", "message": "Logged out, Instagram accounts preserved"}

@router.get("/pages/{page_id}/posts", tags=["facebook"])
def list_page_posts(page_id: str, company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = FacebookService(db)
    # only authorized users can access this endpoint
    if not auth.check_user_company_access(company_id, user["uid"], db):
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    data = service.get_account(company_id)
    token = next((p["page_access_token"] for p in data.get("pages", []) if p["id"] == page_id), None) if data else None
    token = token or (data.get("user_long_token") if data else None)

    if not token:
        raise error.NotFound("Token not found")

    fb_client = FacebookClient(token)
    posts_resp = fb_client.get_page_posts(page_id)
    if "error" in posts_resp:
        raise error.BadRequest(posts_resp)

    fb_posts = posts_resp.get("data", [])
    fb_post_ids = {p["id"] for p in fb_posts}
    fb_post_ids.update({p["id"].split("_")[1] for p in fb_posts if "_" in p["id"]})

    app_posts = service.get_app_posts(company_id, page_id)
    visible = []
    for post in app_posts:
        pid = post.get("platform_response", {}).get("id")
        if pid in fb_post_ids:
            fb_p = next((p for p in fb_posts if p["id"] == pid or ("_" in p["id"] and p["id"].split("_")[1] == pid)), {})
            visible.append({
                "id": pid,
                "message": fb_p.get("message"),
                "created_time": fb_p.get("created_time"),
                "permalink_url": fb_p.get("permalink_url"),
                "full_picture": fb_p.get("full_picture"),
            })
    
    has_posts = len(visible) > 0
    message = (
        "You have not posted any content to this Page using the app in this session, "
        "or some posts were deleted directly on Facebook."
        if not has_posts
        else "Posts created via the app on this Page."
    )

    return {
        "page_id": page_id,
        "has_posts": has_posts,
        "message": message,
        "posts": visible,
    }

# Data deletion
@router.post("/data-deletion", tags=["facebook"])
async def facebook_data_deletion(signed_request: str = Form(...), db: Session = Depends(get_db)):
    service = FacebookService(db)
    payload = service.parse_signed_request(signed_request)
    fb_user_id = payload.get("user_id")
    if not fb_user_id:
        raise error.BadRequest("No user_id")

    service.delete_facebook_user_data(fb_user_id)
    
    base_url = "https://yourdomain.com"
    if constants.REDIRECT_URI:
        base_url = f"{urlparse(constants.REDIRECT_URI).scheme}://{urlparse(constants.REDIRECT_URI).netloc}"
        
    return JSONResponse({
        "url": f"{base_url}/facebook/data-deletion-status?code={fb_user_id}",
        "confirmation_code": fb_user_id
    })

@router.post("/deauthorize", tags=["facebook"])
async def facebook_deauthorize(signed_request: str = Form(...), db: Session = Depends(get_db)):
    service = FacebookService(db)
    payload = service.parse_signed_request(signed_request)
    fb_user_id = payload.get("user_id")
    if fb_user_id:
        service.delete_facebook_user_data(fb_user_id)
    return JSONResponse({"status": "ok"})

@router.get("/data-deletion-status", tags=["facebook"])
async def data_deletion_status(code: Optional[str] = None):
    """
    Simple confirmation page users can see if they click from Facebook.
    """
    html = f'''
    <html>
      <head>
        <title>Data Deletion Status</title>
        <style>
          body {{ font-family: sans-serif; padding: 40px; max-width: 600px; margin: 0 auto; text-align: center; }}
          h3 {{ color: #333; }}
          .card {{ border: 1px solid #ddd; padding: 20px; border-radius: 8px; background: #f9f9f9; }}
          .code {{ font-family: monospace; background: #eee; padding: 5px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h3>Data Deletion Request Received</h3>
          <p>Your data associated with our Facebook app has been successfully removed.</p>
          <p>Reference Code: <span class="code">{code or "N/A"}</span></p>
        </div>
      </body>
    </html>
    '''
    return HTMLResponse(content=html, status_code=200)


@router.get("/facebook/account", tags=["facebook"])
def get_facebook_account(company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = FacebookService(db)
    return service.get_facebook_account(company_id, user)
    