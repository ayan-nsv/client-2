import os
import httpx
import secrets

from urllib.parse import urlencode
from dotenv import load_dotenv

from fastapi import APIRouter, Query, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from products.market_planner.social_media.tiktok.schema.tiktok_schema import (
    TikTokPullUploadRequest,
)

from sqlalchemy.orm import Session
from shared.database.postgres.database_config import get_db

from products.market_planner.social_media.tiktok.services.tiktok_services import TikTokService

from shared.logger.log import setup_logger
from shared.utils.auth.auth import get_current_user
from shared.utils.auth.auth import check_user_company_access

logger = setup_logger("marketing-app")

load_dotenv()

router = APIRouter( tags=["TikTok routes"])

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI")

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_VIDEO_POST_TARGET_URL = (
    "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
)

# IMPORTANT:
# TikTok expects comma-separated scopes
SCOPES = "user.info.basic,user.info.profile,user.info.stats,video.publish,video.upload,video.list"


def _raise_tiktok_error(response: httpx.Response, action: str) -> None:
    try:
        error_payload = response.json()
    except ValueError:
        error_payload = {"raw": response.text}

    error_info = (
        error_payload.get("error", {})
        if isinstance(error_payload, dict)
        else {}
    )

    detail = {
        "action": action,
        "status_code": response.status_code,
        "code": error_info.get("code"),
        "message": error_info.get("message"),
        "log_id": error_info.get("log_id"),
        "raw": error_payload,
    }

    logger.error("[TIKTOK_API_ERROR] %s", detail)

    raise HTTPException(
        status_code=response.status_code,
        detail=detail
    )


@router.get("/auth/tiktok/login")
def tik_tok_login():

    try:
        state = secrets.token_urlsafe(16)

        params = {
            "client_key": CLIENT_KEY,
            "response_type": "code",
            "scope": SCOPES,
            "redirect_uri": REDIRECT_URI,
            "state": state,
        }

        auth_url = f"{TIKTOK_AUTH_URL}?{urlencode(params)}"

        logger.info("[TIKTOK_AUTH_URL] %s", auth_url)

        return {"auth_url": auth_url}

    except Exception as e:
        logger.error("[TIKTOK_LOGIN_ERROR] %s", str(e))

        raise HTTPException(
            status_code=500,
            detail="Failed to start TikTok login"
        )


@router.get("/auth/tiktok/callback")
async def tiktok_callback(
    code: str = Query(...),
    state: str = Query(None),
    error: str = Query(None),
    company_id: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
 ):
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"TikTok OAuth error: {error}"
        )
    if not check_user_company_access(company_id, user["uid"], db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")

    payload = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(
            TIKTOK_TOKEN_URL,
            data=payload,
            headers=headers,
        )

    if response.status_code != 200:
        _raise_tiktok_error(response, action="oauth_token")

    token_data = response.json()

    # Redact sensitive token credentials from logs
    log_token_data = {}
    if isinstance(token_data, dict):
        log_token_data = token_data.copy()
        if "access_token" in log_token_data:
            log_token_data["access_token"] = "********"
        if "refresh_token" in log_token_data:
            log_token_data["refresh_token"] = "********"
    logger.info("[TIKTOK_TOKEN_RESPONSE] %s", log_token_data)

    granted_scopes = token_data.get("scope", "")

    payload = {
        "company_id": company_id,
        "open_id": token_data.get("open_id"),

        "access_token": token_data.get("access_token"),
        "token_type": token_data.get("token_type"),
        "access_expires_in": token_data.get("expires_in"),

        "refresh_token": token_data.get("refresh_token"),
        "refresh_expires_in": token_data.get("refresh_expires_in"),

        "scope": granted_scopes
    }

    result = TikTokService(db).save_tiktok_account(payload)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to save TikTok account")
    return {
        "success": True,
        "granted_scopes": granted_scopes,
        "access_token": "********",
    }


@router.post("/tiktok/video_upload")
async def post_video_upload(
    company_id: str = Query(...),
    video: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    if not check_user_company_access(company_id, user["uid"], db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    # get the access token from the database
    account = TikTokService(db).get_tiktok_account(company_id)
    if not account:
        raise HTTPException(status_code=404, detail="TikTok account not found")
    access_token = account["access_token"]
    """
    Two-in-one single endpoint executing:
    1. TikTok Official Inbox Init via "source_info" schema
    2. Dynamic binary HTTP PUT file upload using raw byte ranges
    """
    # 1. Read binary to calculate exact byte offsets
    video_bytes = await video.read()
    video_size = len(video_bytes)
    
    if video_size == 0:
        raise HTTPException(status_code=400, detail="The uploaded video file is empty.")

    # 2. Match exact headers from initialization cURL
    init_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8"
    }

    # 3. Official documentation payload formatting
    init_payload = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,        # Treating total file as 1 block
            "total_chunk_count": 1           # Singular direct stream transfer
        }
    }

    async with httpx.AsyncClient() as client:
        # --- TASK 1: Initialize Upload Request ---
        init_response = await client.post(
            TIKTOK_VIDEO_POST_TARGET_URL,
            json=init_payload,
            headers=init_headers
        )
        
        # Catch errors immediately if TikTok rejects parameter data
        if init_response.status_code != 200:
            raise HTTPException(
                status_code=init_response.status_code,
                detail=f"TikTok Init Failed: {init_response.text}"
            )
            
        init_data = init_response.json()
        upload_data = init_data.get("data", {})
        
        # Extract the dynamic targets returned from task 1
        upload_url = upload_data.get("upload_url")
        publish_id = upload_data.get("publish_id")

        if not upload_url:
            raise HTTPException(
                status_code=500, 
                detail=f"Missing upload parameters in TikTok response: {init_data}"
            )

        # --- TASK 2: Binary PUT Stream Transmission ---
        # Construct byte indices strictly using 'bytes 0-(N-1)/N'
        put_headers = {
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            "Content-Length": str(video_size),
            "Content-Type": "video/mp4"
        }
        
        # Stream raw binary to the returned secure endpoint bucket
        upload_response = await client.put(
            upload_url,
            content=video_bytes,
            headers=put_headers
        )
        
        # Verify binary stream acceptance status code (Accepts 200 or 201)
        if upload_response.status_code not in [200, 201]:
            raise HTTPException(
                status_code=upload_response.status_code,
                detail=f"TikTok Binary Upload Failed: {upload_response.text}"
            )

        return {
            "success": True,
            "message": "Video successfully pushed into user Inbox/Drafts folder.",
            "publish_id": publish_id,
            "tiktok_upload_status": upload_response.status_code
        }


@router.post("/tiktok/video_url/post")
async def publish_video_from_url(
    body: TikTokPullUploadRequest,
    access_token: str,
    company_id: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
 ):

    if not check_user_company_access(company_id, user["uid"], db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = body.model_dump(mode="json")

    async with httpx.AsyncClient() as client:

        response = await client.post(
            TIKTOK_VIDEO_POST_TARGET_URL,
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        _raise_tiktok_error(
            response,
            action="video_url_post"
        )
    return response.json()

@router.put("/tiktok/logout")
async def logout_tiktok(
    company_id: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    if not check_user_company_access(company_id, user["uid"], db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")

    result = TikTokService(db).logout_tiktok_account(company_id)
    if not result:
        raise HTTPException(status_code=404, detail="TikTok account not found")
    return result


@router.get("/tiktok/account")
async def get_tiktok_account(company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if not check_user_company_access(company_id, user["uid"], db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    account = TikTokService(db).get_tiktok_account(company_id)
    if not account:
        raise HTTPException(status_code=404, detail="TikTok account not found")
    return account




@router.post("/tiktok/generate_video")
async def generate_tiktok_video(
    query: str = Form(...),
    ratio: str = Form(...),
    resolution: str = Form(...),
    duration: int = Form(...),
):
    try:
        from products.market_planner.integrations.seedance.services import seedance_service
    except ImportError as e:
        logger.error("[SEEDANCE_UNAVAILABLE] %s", e)
        raise HTTPException(status_code=501, detail="Seedance video generation is not available")

    try:
        result = await run_in_threadpool(
            seedance_service.generate_video, query, ratio, resolution, duration
        )
    except Exception as e:
        logger.exception("Seedance video generation failed")
        raise HTTPException(status_code=500, detail=str(e))

    if result.get("status") != "succeeded":
        raise HTTPException(
            status_code=502,
            detail=f"Seedance task {result.get('task_id')} {result.get('status')}: {result.get('error')}",
        )

    return {"url": result.get("video_url"), "task_id": result.get("task_id")}