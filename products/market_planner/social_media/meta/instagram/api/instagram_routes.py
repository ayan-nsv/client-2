from fastapi import  HTTPException, Body, APIRouter, Depends, Query
import httpx
import asyncio
from urllib.parse import urlencode
from dotenv import load_dotenv

from datetime import datetime
from sqlalchemy.orm import Session
#########################################################################################
from shared.utils.error import error
from shared.utils.constants import constants
from shared.utils.auth import auth
from shared.database.postgres.database_config import get_db
from products.market_planner.social_media.meta.instagram.services.instagram_service import InstagramService
from products.market_planner.social_media.meta.instagram.schema import instagram_schema
from shared.logger.log import setup_logger

router = APIRouter()
load_dotenv()

logger = setup_logger("marketing-app")




# Step 1: Login redirect (Instagram API with Instagram Login) with company_id in state
@router.get("/auth/instagram/login", tags=["instagram"])
async def instagram_login(company_id: str, user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    # logger.info(f"[IG_LOGIN_START] company_id={company_id}")

    try:
        # In production sign/encrypt/validate this if needed
        state = company_id
        # logger.info(f"[IG_LOGIN_STATE_SET] state={state}")

        query_params = {
            "client_id": constants.INSTAGRAM_APP_ID,
            "redirect_uri": constants.INSTAGRAM_REDIRECT_URI,
            "scope": constants.SCOPES,
            "response_type": "code",
            "state": state,
        }

        logger.info(f"[IG_LOGIN_QUERY_PARAMS] {query_params}")

        query = urlencode(query_params)

        auth_url = f"https://api.instagram.com/oauth/authorize?{query}"

        logger.info(f"[IG_LOGIN_AUTH_URL_GENERATED] url={auth_url}")

        logger.info(
            f"[IG_LOGIN_URL_GENERATED] company_id={company_id}"
        )

        return {"auth_url": auth_url}

    except Exception as e:
        logger.error(
            f"[IG_LOGIN_ERROR] company_id={company_id} error={str(e)}",
            exc_info=True
        )
        raise error.InternalServerError(f"Failed to start Instagram login: {e}")


# Step 2: Callback + exchange code -> short-lived -> long-lived
@router.get("/auth/instagram/callback", tags=["instagram"])
async def instagram_callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
    company_id: str = Query(...),
    user: dict = Depends(auth.get_current_user)
 ):
    service = InstagramService(db)
    start_time = datetime.now()

    logger.info(
        f"[IG_CALLBACK_START] state={state} code_length={len(code) if code else 0} error={error}"
    )

    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")
    
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    if error:
        logger.error(f"[IG_CALLBACK_ERROR_PARAM] error={error}")
        raise error.BadRequest(f"Error: {error}")

    if not code:
        logger.error("[IG_CALLBACK_NO_CODE] No code provided")
        raise error.BadRequest("No code provided")

    company_id = state
    logger.info(f"[IG_CALLBACK_STATE_PARSED] company_id={company_id}")

    try:

        # ---------------------------
        # STEP 1: Exchange for short token
        # ---------------------------

        logger.info("[IG_TOKEN_EXCHANGE_START] exchanging code for short-lived token")

        token_url = "https://api.instagram.com/oauth/access_token"
        payload = {
            "client_id": constants.INSTAGRAM_APP_ID,
            "client_secret": constants.INSTAGRAM_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": constants.INSTAGRAM_REDIRECT_URI,
            "code": code,
        }

        logger.info(
            f"[IG_TOKEN_EXCHANGE_REQUEST] url={token_url} redirect_uri={constants.INSTAGRAM_REDIRECT_URI}"
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data=payload)

        logger.info(
            f"[IG_TOKEN_EXCHANGE_RESPONSE] status={resp.status_code}"
        )

        if resp.status_code != 200:
            logger.error("[IG_TOKEN_EXCHANGE_FAILED] status=%s", resp.status_code)
            raise error.InternalServerError(f"Failed to exchange code for short-lived token: {resp.text}")

        data = resp.json()

        short_lived_token = data.get("access_token")
        app_scoped_user_id = data.get("user_id")

        logger.info(
            f"[IG_TOKEN_EXCHANGE_SUCCESS] app_scoped_user_id={app_scoped_user_id}"
        )

        # ---------------------------
        # STEP 2: Exchange long-lived token
        # ---------------------------

        logger.info("[IG_LONG_TOKEN_EXCHANGE_START]")

        long_lived_url = "https://graph.instagram.com/access_token"
        long_lived_params = {
            "grant_type": "ig_exchange_token",
            "client_secret": constants.INSTAGRAM_APP_SECRET,
            "access_token": short_lived_token,
        }

        logger.info(f"[IG_LONG_TOKEN_REQUEST] url={long_lived_url}")

        async with httpx.AsyncClient() as client:
            long_lived_resp = await client.get(long_lived_url, params=long_lived_params)

        logger.info(
            f"[IG_LONG_TOKEN_RESPONSE] status={long_lived_resp.status_code}"
        )

        if long_lived_resp.status_code != 200:
            logger.error(
                f"[IG_LONG_TOKEN_FAILED] response={long_lived_resp.text}"
            )

            return {
                "company_id": company_id,
                "app_scoped_user_id": "********",
                "access_token": "********",
                "token_type": "short_lived",
                "warning": "Could not exchange for long-lived token",
            }

        long_lived_data = long_lived_resp.json()

        long_lived_token = long_lived_data.get("access_token")
        expires_in = long_lived_data.get("expires_in") or 5184000

        logger.info(
            f"[IG_LONG_TOKEN_SUCCESS] expires_in={expires_in}"
        )

        # ---------------------------
        # STEP 3: Resolve IG Account
        # ---------------------------

        logger.info("[IG_ME_FETCH_START] resolving IG account info")

        me_url = f"{constants.GRAPH_IG_BASE}/me"

        me_params = {
            "fields": "user_id,username,profile_picture_url,account_type,media_count",
            "access_token": long_lived_token,
        }

        logger.info(
            f"[IG_ME_REQUEST] endpoint=/me fields={me_params['fields']}"
        )

        async with httpx.AsyncClient() as client:
            me_resp = await client.get(me_url, params=me_params)

        logger.info(
            f"[IG_ME_RESPONSE] status={me_resp.status_code}"
        )

        if me_resp.status_code != 200:
            logger.error("[IG_ME_FAILED] status=%s", me_resp.status_code)
            raise error.InternalServerError(
                f"Failed to resolve IG user id: {me_resp.text}"
            )

        me_data = me_resp.json()

        ig_user_id = me_data.get("user_id")
        username = me_data.get("username")
        profile_picture_url = me_data.get("profile_picture_url")
        account_type = me_data.get("account_type")
        media_count = me_data.get("media_count", 0) or 0

        logger.info(
            f"[IG_ME_SUCCESS] ig_user_id={ig_user_id} username={username} account_type={account_type}"
        )

        # ---------------------------
        # STEP 4: Save to DB
        # ---------------------------

        logger.info(
            f"[IG_DB_SAVE_START] company_id={company_id} ig_user_id={ig_user_id}"
        )

        service.save_instagram_account(
            company_id,
            ig_user_id,
            username,
            profile_picture_url,
            account_type,
            media_count,
            long_lived_token,
            expires_in,
        )

        logger.info("[IG_DB_SAVE_SUCCESS]")

        # ---------------------------
        # Final Response
        # ---------------------------

        duration = round((datetime.now() - start_time).total_seconds(), 3)

        logger.info(
            f"[IG_CALLBACK_SUCCESS] company_id={company_id} duration={duration}s"
        )

        return {
            "company_id": company_id,
            "ig_user_id": ig_user_id,
            "username": username,
            "profile_picture_url": profile_picture_url,
            "access_token": "********",
            "token_type": "long_lived",
        }

    except Exception as e:

        duration = round((datetime.now() - start_time).total_seconds(), 3)

        logger.exception(
            f"[IG_CALLBACK_FATAL_ERROR] state={state} duration={duration}s error={str(e)}"
        )

        raise error.InternalServerError(f"Failed to complete Instagram callback: {e}")


# Helper: wait until media container is ready
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
                logger.error("Status check failed: status=%s", resp.status_code)
                raise error.InternalServerError(
                    f"Status check failed: status={resp.status_code}"
                )

            data = resp.json()
            status = data.get("status_code")
            logger.info(f"Container {media_id} status_code={status}")

            if status == "FINISHED":
                return

            if asyncio.get_event_loop().time() - start > timeout_sec:
                raise error.InternalServerError(
                    f"Media container not ready after {timeout_sec}s, status={status}"
                )

            await asyncio.sleep(3)


# Debug: verify token + IG account info
@router.get("/auth/instagram/verify", tags=["instagram"])
async def verify_token(user_id: str, access_token: str):
    """
    Verify if the access token is valid and get account info
    user_id must be the IG professional account id from /me.user_id
    """
    try:
        user_id = str(user_id).strip().replace("\n", "").replace("\r", "").replace(" ", "")
        access_token = access_token.strip().replace("\n", "").replace("\r", "").replace(" ", "")

        verify_url = f"{constants.GRAPH_IG_BASE}/{user_id}"
        params = {
            "fields": "username,account_type,media_count",
            "access_token": access_token,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(verify_url, params=params)

        if resp.status_code != 200:
            return {
                "valid": False,
                "error": resp.json(),
                "status_code": resp.status_code,
            }

        data = resp.json()
        return {
            "valid": True,
            "user_id": user_id,
            "username": data.get("username"),
            "account_type": data.get("account_type"),
            "media_count": data.get("media_count"),
            "token_length": len(access_token),
        }

    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        return {
            "valid": False,
            "error": str(e),
        }


@router.delete("/auth/instagram/logout", tags=["instagram"])
async def instagram_logout(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = InstagramService(db)
    return service.deactivate_insta_account(company_id, user)


@router.post("/auth/instagram/post", tags=["instagram"])
async def instagram_post(request: instagram_schema.PostRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = InstagramService(db)
    return service.instagram_post(request.model_dump_json())
    

@router.get("/auth/instagram/posts", tags=["instagram"])
async def list_instagram_posts(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = InstagramService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    posts = service.get_instagram_posts(company_id)
    if not posts:
        raise error.BadRequest("No posts found")
    return posts

# Optional: refresh long-lived token
@router.post("/auth/instagram/refresh", tags=["instagram"])
async def refresh_token(access_token: str = Body(..., embed=True), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    try:
        refresh_url = "https://graph.instagram.com/refresh_access_token"
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": access_token,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(refresh_url, params=params)

        if resp.status_code != 200:
            raise error.InternalServerError(f"Error refreshing token: {resp.text}")

        data = resp.json()
        return {
            "access_token": "********",
            "token_type": data["token_type"],
            "expires_in": data["expires_in"],
        }

    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        raise error.InternalServerError(f"Error refreshing token: {str(e)}")


@router.get("/auth/instagram/account", tags=["instagram"])
async def get_instagram_account(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = InstagramService(db)
    return service.get_insta_account(company_id, user)



@router.post("/auth/instagram/account/select", tags=["instagram"])
async def select_instagram_account(company_id: str, account_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    # only authorized users can access this endpoint
    service = InstagramService(db)
    return service.select_instagram_account(company_id, account_id, user)
    