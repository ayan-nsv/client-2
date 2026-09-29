"""
WhatsApp API routes. Uses PostgreSQL (whatsapp_tables) and Twilio only — no Firestore.
"""
import os
import re
import uuid
from datetime import timezone

from sqlalchemy.orm import Session
from fastapi.responses import Response
from fastapi import APIRouter, Form, HTTPException, Depends

from products.market_planner.social_media.meta.whatsapp.schemas import whatsapp_schema 
from products.market_planner.social_media.meta.whatsapp.services.whatsapp_service import WhatsAppService

from shared.utils.auth import auth
from shared.utils.error import error
from shared.database.postgres.database_config import get_db


router = APIRouter()
UTC = timezone.utc



@router.get("/whatsapp/check-twilio", tags=["whatsapp"])
def check_twilio(user: dict = Depends(auth.get_current_user)):
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_WHATSAPP_FROM")
    return {
        "twilio_sid_loaded": bool(sid),
        "twilio_token_loaded": bool(token),
        "twilio_from_loaded": bool(from_num),
        "twilio_sid_preview": (sid[:5] + "...") if sid else None,
        "twilio_from": from_num,
    }


@router.get("/whatsapp/test/{phone_number}", tags=["whatsapp"])
def test_whatsapp(phone_number: str, user: dict = Depends(auth.get_current_user)):
    try:
        sid = WhatsAppService.send_whatsapp_message(phone_number, "Test message from Marketing Planner API.", None)
        return {"success": True, "message_sid": sid, "phone_number": phone_number}
    except Exception as e:
        return {"success": False, "error": str(e), "phone_number": phone_number}


# ---------- Company WhatsApp config (PostgreSQL) ----------


@router.get("/whatsapp/company/{company_id}", tags=["whatsapp"])
def get_whatsapp_number(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    svc = WhatsAppService(db)
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    acc = svc.get_whatsapp_account(company_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Company WhatsApp number not found")
    return {
        "company_id": company_id,
        "phone_number": acc.phone_number,
        "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
    }


@router.put("/whatsapp/company/{company_id}", tags=["whatsapp"])
def update_whatsapp_number(company_id: str, data: whatsapp_schema.WhatsAppNumberBody, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    try:
        company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    except ValueError as e:
        raise error.PermissionDenied(str(e))

    svc = WhatsAppService(db)
    try:
        acc = svc.get_or_create_whatsapp_account(company_id, data.phone_number)
        return {
            "message": "WhatsApp number updated successfully",
            "company_id": company_id,
            "phone_number": acc.phone_number,
        }
    except ValueError as e:
        raise error.NotFound(str(e))


@router.delete("/whatsapp/company/{company_id}/logout", tags=["whatsapp"])
def logout_company(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):

    service = WhatsAppService(db)
    return service.logout_company(company_id, user)

    


# ---------- Theme / Post status (by message_token) ----------


@router.get("/whatsapp/themes/{theme_id}/status", tags=["whatsapp"])
def get_theme_status(theme_id: str, company_id: str | None = None, db: Session = Depends(get_db)):
    """
    ``theme_id`` may be:

    - WhatsApp reply token: ``tp_<themes.id>_<suffix>`` (exact ``message_token``), or
    - ``themes`` table primary key (e.g. ``2``), or
    - ``themes.uuid`` string.

    Use ``company_id`` (query) to scope access when passing numeric/theme UUID.
    """
    service = WhatsAppService(db)
    d, json_theme_id = service.get_theme_delivery_for_status( theme_id, company_id)
    if not d:
        raise error.NotFound(
           "Theme delivery not found (unknown token, theme id, or wrong company).",
        )
    return service.theme_delivery_to_status_response(d, json_theme_id)


@router.get("/whatsapp/posts/{post_id}/status", tags=["whatsapp"])
def get_post_status(post_id: str, company_id: str | None = None, db: Session = Depends(get_db)):
    service = WhatsAppService(db)
    d = service.get_post_delivery_by_token(post_id)
    if not d:
        raise error.NotFound("Post not found")
    if company_id and str(d.company.uuid) != company_id:
        raise error.NotFound("Post not found for this company")
    return service.post_delivery_to_status_response(d, post_id)


@router.get("/whatsapp/company/{company_id}/themes", tags=["whatsapp"])
def get_company_themes(company_id: str, status: str | None = None, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = WhatsAppService(db)
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    themes = service.list_theme_deliveries(company_id, status)
    return {"company_id": company_id, "total_themes": len(themes), "themes": themes}


@router.get("/whatsapp/company/{company_id}/posts", tags=["whatsapp"])
def get_company_posts(company_id: str, status: str | None = None, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = WhatsAppService(db)
    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    posts = service.list_post_deliveries(company_id, status)
    return {"company_id": company_id, "total_posts": len(posts), "posts": posts}


# ---------- Send post ----------


@router.post("/whatsapp/posts/send/{post_id}", tags=["whatsapp"])
def send_post(post_id: str, data: whatsapp_schema.PostSendRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = WhatsAppService(db)
    company_id_int = auth.check_user_company_access(data.company_id, user["uid"], db)
    phone_number = service.get_company_phone(data.company_id)
    if not phone_number:
        raise error.NotFound("Company WhatsApp number not found")
    message_token = post_id if post_id.startswith("post_") else f"post_{post_id}"
    body = f"""{data.caption}
[#{message_token}]
Reply *ja* to approve or *nej* for changes.
"""
    sid = service.send_whatsapp_message(phone_number, body, data.media_url)
    service.create_post_delivery(
        db, data.company_id, message_token, phone_number, sid, post_id=None
    )
    return {"post_id": message_token, "twilio_message_sid": sid, "status": "sent"}


# ---------- Send theme ----------


@router.post("/whatsapp/themes/send/{theme_id}", tags=["whatsapp"])
def send_theme(theme_id: str, data: whatsapp_schema.ThemeSendRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = WhatsAppService(db)
    company_id_int = auth.check_user_company_access(data.company_id, user["uid"], db)
    phone_number = service.get_company_phone(data.company_id)
    if not phone_number:
        raise error.NotFound("Company WhatsApp number not found")
    theme_row = service.resolve_theme_for_whatsapp_send(theme_id, data.company_id)
    if not theme_row:
        raise error.NotFound("Theme not found for this company. Use the theme's numeric id or UUID from your themes data.")
    try:
        month, o1t, o1d, o2t, o2d = service.theme_whatsapp_options_from_db(theme_row)
    except ValueError as e:
        raise error.BadRequest(str(e))
    if data.month is not None:
        month = data.month
    if data.option1_title is not None:
        o1t = data.option1_title
    if data.option1_desc is not None:
        o1d = data.option1_desc
    if data.option2_title is not None:
        o2t = data.option2_title
    if data.option2_desc is not None:
        o2d = data.option2_desc

    # Token includes DB theme id for traceability; suffix keeps message_token unique per send.
    message_token = f"tp_{theme_row.id}_{uuid.uuid4().hex[:12]}"
    body = f"""Hi! 👋 Here are your themes for {month}:

1️⃣ {o1t}
{o1d}

2️⃣ {o2t}
{o2d}

Reply with *1* or *2* to choose your theme.
[#{message_token}]
"""
    sid = service.send_whatsapp_message(phone_number, body, None)
    company_id_int = service.company_repo.get_company_id_from_uuid(data.company_id)
    if company_id_int:
        service.supersede_pending_themes(company_id_int, message_token)
    service.create_theme_delivery(
        data.company_id,
        message_token,
        phone_number,
        sid,
        month,
        o1t,
        o1d,
        o2t,
        o2d,
        theme_id=theme_row.id,
    )
    return {
        "theme_id": message_token,
        "theme_db_id": theme_row.id,
        "twilio_message_sid": sid,
        "status": "pending",
    }


# ---------- Webhook (Twilio WhatsApp) — update delivery status only, no message storage ----------


@router.post("/webhooks/twilio/whatsapp", tags=["whatsapp"])
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(...),
    db: Session = Depends(get_db),
):
    body_raw = (Body or "").strip()
    body = body_raw.lower()
    token_match = re.search(r"\[#(tp_\w+|post_\w+)\]", Body)
    token = token_match.group(1) if token_match else None
    reply_message = "Sorry, I didn't understand that. Please check your recent message for instructions."
    service = WhatsAppService(db)
    if token:
        if token.startswith("tp_"):
            d = service.get_theme_delivery_by_token(token)
            if not d:
                reply_message = "Theme not found. Please check the message again."
            elif d.status == "answered":
                reply_message = "✅ You already selected a theme. Thank you!"
            elif body in ("1", "2"):
                opt = body
                title = d.option1_title if opt == "1" else d.option2_title
                desc = d.option1_desc if opt == "1" else d.option2_desc
                service.update_theme_delivery_answered(d.id, opt, title, desc)
                reply_message = f"✅ Perfect! You selected theme {opt}. Thank you!"
            else:
                reply_message = f"❌ Please reply with *1* or *2* to select your theme."
        elif token.startswith("post_"):
            d = service.get_post_delivery_by_token(token)
            if not d:
                reply_message = "Post not found. Please check the message again."
            elif d.status in ("approved", "needs_changes"):
                reply_message = "✅ You already replied to this post. Thank you!"
            elif body in ("ja", "nej"):
                status = "approved" if body == "ja" else "needs_changes"
                service.update_post_delivery_status(d.id, status)
                reply_message = "✅ Post approved! Thank you!" if body == "ja" else "📝 Got it! We'll make the changes you requested."
            else:
                reply_message = "❌ Please reply with *ja* to approve or *nej* if you need changes."

    xml = f"<Response><Message>{reply_message}</Message></Response>"
    return Response(content=xml, media_type="application/xml")


# ---------- Match replies (Twilio API + PostgreSQL delivery updates) ----------


@router.get("/whatsapp/match-replies", tags=["whatsapp"])
def match_replies(
    user_number: str | None = None,
    company_id: str | None = None,
    window_minutes: int = 1440,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    if company_id:
        service = WhatsAppService(db)
        company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    try:
        return service.match_replies_impl(user_number, company_id, window_minutes, limit)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower() or "no phone" in msg.lower():
            raise error.NotFound(msg)
        raise error.BadRequest(msg)


@router.get("/whatsapp/match-replies-batch", tags=["whatsapp"])
def match_replies_batch(
    company_ids: str | None = None,
    window_minutes: int = 1440,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    from products.market_planner.social_media.meta.whatsapp.tables.whatsapp_tables import WhatsAppAccount
    service = WhatsAppService(db)
    if company_ids:
        uuids = [c.strip() for c in company_ids.split(",") if c.strip()]
        for company_uuid in uuids:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], db)
    else:
        if not auth.has_privileged_access(user):
            raise error.Forbidden("company_ids is required")
        accs = db.query(WhatsAppAccount).all()
        uuids = [str(a.company.uuid) for a in accs if a.company]
    results = []
    total_matched = total_updated = 0
    for cid in uuids:
        try:
            res = service.match_replies_impl(None, cid, window_minutes, limit)
            total_matched += len(res.get("matched", []))
            total_updated += len(res.get("updated", []))
            results.append({"company_id": cid, "ok": True, "matched": len(res.get("matched", [])), "updated": len(res.get("updated", []))})
        except ValueError as e:
            results.append({"company_id": cid, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"company_id": cid, "ok": False, "error": str(e)})
    return {"companies_processed": len(uuids), "total_matched": total_matched, "total_updated": total_updated, "details": results, "window_minutes": window_minutes, "limit": limit}


@router.get("/whatsapp/match-replies-global", tags=["whatsapp"])
def match_replies_global(
    window_minutes: int = 1440,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    service = WhatsAppService(db)
    client = service.get_twilio_client()
    msgs = list(client.messages.list(limit=limit))
    senders = []
    seen = set()
    for m in msgs:
        if getattr(m, "direction", None) == "inbound" and getattr(m, "from_", None):
            num = m.from_.replace("whatsapp:", "")
            if num not in seen:
                seen.add(num)
                senders.append(num)
    details = []
    total_matched = total_updated = 0
    for num in senders:
        try:
            res = service.match_replies_impl(num, None, window_minutes, limit)
            total_matched += len(res.get("matched", []))
            total_updated += len(res.get("updated", []))
            details.append({"user": num, "matched": len(res.get("matched", [])), "updated": len(res.get("updated", []))})
        except ValueError as e:
            details.append({"user": num, "ok": False, "error": str(e)})
        except Exception as e:
            details.append({"user": num, "ok": False, "error": str(e)})
    return {"senders_processed": len(senders), "total_matched": total_matched, "total_updated": total_updated, "details": details, "window_minutes": window_minutes, "limit": limit}


# ---------- Send reminders ----------


@router.post("/whatsapp/send-reminders", tags=["whatsapp"])
def send_reminders(hours: int = 6, company_id: str | None = None, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):

    service = WhatsAppService(db)
    return service.send_reminders(hours, company_id, user)
   