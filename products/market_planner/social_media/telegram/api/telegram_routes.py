"""FastAPI routes for Telegram Marketing Bot API."""

import os
import secrets
import time
import uuid
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from urllib.parse import quote

from products.market_planner.social_media.telegram.services.telegram_bot_class import TelegramMarketingBot
from products.market_planner.social_media.telegram.schema.telegram_schema import (
    RegisterCompanyRequest,
    RegisterCompanyResponse,
    SendPostByCompanyRequest,
    SendPostByCompanyResponse,
    PostStatusRequest,
    PostStatusResponse,
    BotLinkResponse,
    ThemeSendRequest,
    ThemeSendResponse,
    ThemeSelectionStatusRequest,
    ThemeSelectionStatusResponse,
    CompanyChatInfo,
    CompanyChatsResponse,
    RejectedPostInfo,
    RejectedPostsResponse,
    LogoutResponse,
)
from products.market_planner.social_media.telegram.configuration.telegram_config import get_bot_token, BOT_USERNAME
from sqlalchemy.orm import Session
from fastapi import Depends
from shared.database.postgres.database_config import get_db
from products.market_planner.social_media.telegram.tables.telegram_tables import TelegramChat, TelegramPendingApproval
from core.tables.company_tables import Company
from core.tables.user_tables import User
from datetime import datetime
from shared.utils.auth import auth
from shared.utils.error import error
from shared.logger.log import setup_logger


logger = setup_logger("marketing-app")

router = APIRouter()
TELEGRAM_WEBHOOK_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()

# Lazy bot initialization - only created when first accessed
_bot_instance = None

def _get_bot():
    """Get or create the bot instance. Validates token only when first accessed."""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = TelegramMarketingBot(get_bot_token())
    return _bot_instance

# Create a simple proxy object that lazily initializes the bot
class _BotProxy:
    def __getattr__(self, name):
        return getattr(_get_bot(), name)

bot = _BotProxy()


@router.get("/companies", tags=["telegram"])
async def list_companies_with_chats(
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_admin_user),
):
    """List all companies with active Telegram chats."""
    try:
        # Query Postgres for all distinct company_ids in telegram_chats
        company_ids = db.query(TelegramChat.company_id).distinct().all()
        company_ids = [c[0] for c in company_ids]
        
        companies_data = []
        if company_ids:
            # Get company details
            companies = db.query(Company).filter(Company.id.in_(company_ids)).all()
            for company in companies:
                companies_data.append({
                    "company_id": company.uuid,
                    "company_name": company.company_name
                })
        
        return {
            "success": True,
            "message": "Companies fetched successfully",
            "companies": companies_data,
            "source": "postgres"
        }
    except Exception as e:
        print(f"⚠️ Failed to list companies from Postgres: {e}")
        raise error.InternalServerError(f"Failed to list companies from Postgres: {e}")


@router.post("/register-company", response_model=RegisterCompanyResponse, tags=["telegram"])
def register_company(
    payload: RegisterCompanyRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Attach a company_id to an existing Telegram chat."""
    company_id_int = auth.check_user_company_access(payload.company_id, user["uid"], db)
    target_chat_id = None
    target_chat_obj = None

    if payload.chat_id:
        target_chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == payload.chat_id).first()
        if not target_chat_obj:
            raise error.NotFound("Chat ID not found. Make sure the user has started the bot.")
        target_chat_id = target_chat_obj.telegram_chat_id

    elif payload.telegram_username:
        username_lower = payload.telegram_username.lstrip("@").lower()
        target_chat_obj = db.query(TelegramChat).filter(TelegramChat.username.ilike(username_lower)).first()
        if not target_chat_obj:
            raise error.NotFound("No Telegram user with that username found. Make sure they have started the bot.")
        target_chat_id = target_chat_obj.telegram_chat_id

    else:
        raise error.BadRequest("Either chat_id or telegram_username is required.")

    company_obj = db.query(Company).filter(Company.uuid == payload.company_id).first()
    if not company_obj:
        raise error.NotFound(f"Company with UUID '{payload.company_id}' not found.")

    target_chat_obj.company_id = company_obj.id
    db.add(target_chat_obj)
    db.commit()
    db.refresh(target_chat_obj)

    return {
        "success": True,
        "message": f"Company {payload.company_id} registered successfully",
        "chat_id": target_chat_id,
        "company_id": payload.company_id,
        "data": {
            "chat_id": target_chat_id,
            "company_id": payload.company_id,
            "company_name": company_obj.company_name,
            "connected_at": target_chat_obj.connected_at.isoformat() if target_chat_obj.connected_at else None,
            "first_name": target_chat_obj.first_name,
            "username": target_chat_obj.username,
        },
    }


@router.post("/post-send", response_model=SendPostByCompanyResponse, tags=["telegram"])
async def send_post_by_company(
    request: SendPostByCompanyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Send a post (image + caption) to a company's Telegram chat for approval."""
    company_id = request.company_id
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    image_url = request.image_url
    caption = request.caption
    post_id = request.post_id or str(uuid.uuid4())[:8]

    chat_id = None
    try:
        company_obj = db.query(Company).filter(Company.uuid == company_id).first()
        if company_obj:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.company_id == company_obj.id).first()
            if chat_obj:
                chat_id = chat_obj.telegram_chat_id
    except Exception as e:
        print(f"⚠️ Error resolving chat_id from Postgres: {e}")
        chat_id = None

    if not chat_id:
        raise error.NotFound(f"No Telegram chat linked for company '{company_id}'")

    approval_key = bot.add_pending_approval_immediately(
        chat_id=chat_id,
        image_url=image_url,
        caption=caption,
        post_id=post_id,
        company_id=company_id,
        db=db
    )

    background_tasks.add_task(
        bot.send_post_and_wait,
        chat_id=chat_id,
        image_url=image_url,
        caption=caption,
        post_id=post_id,
        company_id=company_id
    )

    return {
        "success": True,
        "message": f"Post sent to chat {chat_id} for approval",
        "chat_id": chat_id,
        "company_id": company_id,
        "approval_key": approval_key or f"{chat_id}_{post_id}"
    }


@router.get("/post-status", response_model=PostStatusResponse, tags=["telegram"])
async def get_post_status(
    company_id: str,
    post_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Get the approval status for a specific post_id and company_id."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    try:
        status_data = bot.get_post_status(company_id, post_id, db=db)
        
        if status_data is None:
                raise error.NotFound(f"Post status not found for company_id: {company_id}, post_id: {post_id}")
        
        return {
            "success": True,
            "message": "Post status fetched successfully",
            "company_id": status_data.get("company_id"),
            "post_id": status_data.get("post_id"),
            "status": status_data.get("status"),
            "chat_id": status_data.get("chat_id"),
            "image_url": status_data.get("image_url"),
            "caption": status_data.get("caption"),
            "created_at": status_data.get("created_at"),
            "responded_at": status_data.get("responded_at"),
            "message_id": status_data.get("message_id"),
            "source": status_data.get("source", "postgres")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise error.InternalServerError(f"Failed to get post status: {str(e)}")


@router.get("/bot-link/{company_id}", response_model=BotLinkResponse, tags=["telegram"])
def get_bot_link_get(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    """Get Telegram bot deep link URL for a specific company_id."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    try:
        encoded_company_id = quote(company_id)
        bot_link = f"https://t.me/{BOT_USERNAME}?start={encoded_company_id}"
        return {
            "success": True,
            "message": "Bot link generated successfully",
            "bot_link": bot_link,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate bot link: {str(e)}"
        )


@router.get("/company/{company_id}/chats", response_model=CompanyChatsResponse, tags=["telegram"])
async def get_company_chats(
    company_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Get all chat information for a specific company_id."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    chats = []
    try:
        company_obj = db.query(Company).filter(Company.uuid == company_id).first()
        if not company_obj:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        
        telegram_chats = db.query(TelegramChat).filter(TelegramChat.company_id == company_obj.id).all()
        
        for chat_obj in telegram_chats:
            chats.append(CompanyChatInfo(
                chat_id=chat_obj.telegram_chat_id,
                company_id=company_id,
                company_name=company_obj.company_name,
                connected_at=chat_obj.connected_at.isoformat() if chat_obj.connected_at else None,
                first_name=chat_obj.first_name,
                username=chat_obj.username,
            ))
        
        return {
            "success": True,
            "message": "Company chats fetched successfully",
            "company_id": company_id,
            "chats": chats,
            "source": "postgres"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise error.InternalServerError(f"Failed to get company chats: {str(e)}")


@router.get("/company/{company_id}/rejected-posts", response_model=RejectedPostsResponse, tags=["telegram"])
async def get_rejected_posts(
    company_id: str,
    chat_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Get all rejected posts for a specific company_id, optionally filtered by chat_id."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    rejected_posts = []
    try:
        company_obj = db.query(Company).filter(Company.uuid == company_id).first()
        if not company_obj:
            raise error.NotFound(f"Company '{company_id}' not found")
            
        query = db.query(TelegramPendingApproval).filter(
            TelegramPendingApproval.company_id == company_obj.id,
            TelegramPendingApproval.status == "rejected"
        )
        
        if chat_id:
            tg_chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if tg_chat_obj:
                query = query.filter(TelegramPendingApproval.chat_id == tg_chat_obj.id)
            else:
                return {
                    "success": True,
                    "company_id": company_id,
                    "rejected_posts": [],
                    "source": "postgres"
                }
        
        rejected = query.order_by(TelegramPendingApproval.responded_at.desc()).all()
        
        for post in rejected:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.id == post.chat_id).first()
            tg_chat_id = chat_obj.telegram_chat_id if chat_obj else None
            
            rejected_posts.append(RejectedPostInfo(
                post_id=post.post_id,
                chat_id=tg_chat_id,
                image_url=post.image_url,
                caption=post.caption,
                status=post.status,
                created_at=post.created_at.isoformat() if post.created_at else None,
                responded_at=post.responded_at.isoformat() if post.responded_at else None,
                message_id=post.message_id,
                company_id=company_id
            ))
            
        return {
            "success": True,
            "message": "Rejected posts fetched successfully",
            "company_id": company_id,
            "rejected_posts": rejected_posts,
            "source": "postgres"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise error.InternalServerError(f"Failed to get rejected posts: {str(e)}")


@router.delete("/{company_id}/chatid/{chat_id}", response_model=LogoutResponse, tags=["telegram"])
def logout_chat(
    company_id: str,
    chat_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Delete/logout a chat from a company."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    try:
        company_obj = db.query(Company).filter(Company.uuid == company_id).first()
        if company_obj:
            db.query(TelegramChat).filter(
                TelegramChat.telegram_chat_id == chat_id,
                TelegramChat.company_id == company_obj.id
            ).delete()
            db.commit()
            
        try:
            bot._invalidate_chats_cache()
        except:
            pass
            
        return {
            "success": True,
            "message": f"Chat {chat_id} successfully logged out from company {company_id}",
            "company_id": company_id,
            "chat_id": chat_id,
        }
    except Exception as e:
        db.rollback()
        raise error.InternalServerError(f"Failed to logout chat: {str(e)}")


@router.post("/themesend", response_model=ThemeSendResponse, tags=["telegram"])
async def send_theme_selection(
    request: ThemeSendRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Send theme selection options to a company's Telegram chat."""
    company_id = request.company_id
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    themes = [theme.dict() for theme in request.themes]
    theme_id = request.theme_id
    month = request.month

    if len(themes) < 2:
        raise error.BadRequest("At least 2 themes are required for selection")

    chat_id = None
    try:
        company_obj = db.query(Company).filter(Company.uuid == company_id).first()
        if company_obj:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.company_id == company_obj.id).first()
            if chat_obj:
                chat_id = chat_obj.telegram_chat_id
    except Exception as e:
        print(f"⚠️ Error resolving chat_id from Postgres: {e}")
        chat_id = None

    if not chat_id:
        raise error.NotFound(f"No Telegram chat linked for company '{company_id}'")

    selection_key = bot.add_theme_selection_immediately(
        chat_id=chat_id,
        themes=themes,
        theme_id=theme_id,
        company_id=company_id,
        month=month,
        db=db
    )

    background_tasks.add_task(
        bot.send_theme_selection_and_wait,
        chat_id=chat_id,
        themes=themes,
        theme_id=theme_id,
        company_id=company_id
    )

    return {
        "success": True,
        "message": f"Theme selection sent to chat {chat_id}",
        "chat_id": chat_id,
        "company_id": company_id,
        "selection_key": selection_key or theme_id
    }


@router.get("/theme-selection-status", response_model=ThemeSelectionStatusResponse, tags=["telegram"])
async def get_theme_selection_status(
    company_id: str,
    theme_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Get the theme selection status for a specific theme_id and company_id."""
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    try:
        status_data = bot.get_theme_selection_status(company_id, theme_id, db=db)
        
        if status_data is None:
            raise error.NotFound(f"Theme selection not found for company_id: {company_id}, theme_id: {theme_id}")
        
        return {
            "success": True,
            "message": "Theme selection status fetched successfully",
            "company_id": status_data.get("company_id"),
            "theme_id": status_data.get("theme_id", theme_id),
            "status": status_data.get("status", "pending"),
            "selected_theme": status_data.get("selected_theme"),
            "selected_theme_title": status_data.get("selected_theme_title"),
            "chat_id": status_data.get("chat_id"),
            "themes": status_data.get("themes"),
            "created_at": status_data.get("created_at"),
            "responded_at": status_data.get("responded_at"),
            "message_id": status_data.get("message_id"),
            "month": status_data.get("month"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise error.InternalServerError(f"Failed to get theme selection status: {str(e)}")


@router.post("/webhook", tags=["telegram"])
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive updates from Telegram webhook."""
    if not TELEGRAM_WEBHOOK_SECRET:
        raise error.InternalServerError("Telegram webhook secret not configured")
    provided_secret = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
    if not provided_secret or not secrets.compare_digest(provided_secret, TELEGRAM_WEBHOOK_SECRET):
        raise error.PermissionDenied("Unauthorized: invalid or missing Telegram webhook secret")

    try:
        data = await request.json()
        
        if "callback_query" in data:
            bot._handle_callback_query(data["callback_query"], db=db)
            return {"ok": True}
        
        elif "message" in data:
            msg = data["message"]
            chat = msg["chat"]
            chat_id = str(chat["id"])
            text = msg.get("text", "").strip()
            
            if text.startswith("/start"):
                company_id = None
                parts = text.split(maxsplit=1)
                if len(parts) == 2:
                    company_id = parts[1].strip()
                
                chat_info = {
                    "first_name": chat.get("first_name", ""),
                    "username": chat.get("username", ""),
                    "last_name": chat.get("last_name", ""),
                }
                
                bot.register_chat_from_webhook(chat_id, chat_info, company_id, db=db)
            
            return {"ok": True}
        
        else:
            return {"ok": True, "message": "Update type not handled"}
            
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/set-webhook", tags=["telegram"])
def set_webhook(
    request: Request,
    user: dict = Depends(auth.get_admin_user),
    db: Session = Depends(get_db),
):
    """Set Telegram webhook URL."""
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL","https://appsdb.holdflight.se/telegram/webhook")
    
    if not webhook_url:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.hostname)
        if request.url.port and request.url.port not in [80, 443]:
            host = f"{host}:{request.url.port}"
        base_url = f"{scheme}://{host}"
        webhook_url = f"{base_url}/telegram/webhook"
    
    try:
        response = bot._session.post(
            f"{bot.base_url}/setWebhook",
            data={
                "url": webhook_url,
                "secret_token": TELEGRAM_WEBHOOK_SECRET,
            },
            timeout=10
        )
        data = response.json()
        if not data.get("ok"):
            error_code = data.get("error_code", 400)
            description = data.get("description", "Failed to set webhook")
            raise error.InternalServerError(f"Telegram error: {description}")
        return data
    except Exception as e:
        raise error.InternalServerError(f"Failed to set webhook: {str(e)}")


@router.get("/get-webhook-info", tags=["telegram"])
def get_webhook_info(user: dict = Depends(auth.get_admin_user), db: Session = Depends(get_db)):
    """Get current webhook configuration."""
    try:
        response = bot._session.get(f"{bot.base_url}/getWebhookInfo", timeout=10)
        data = response.json()
        if not data.get("ok"):
            error_code = data.get("error_code", 400)
            description = data.get("description", "Failed to get webhook info")
            raise error.InternalServerError(f"Telegram error: {description}")
        return data
    except Exception as e:
        raise error.InternalServerError(f"Failed to get webhook info: {str(e)}")
