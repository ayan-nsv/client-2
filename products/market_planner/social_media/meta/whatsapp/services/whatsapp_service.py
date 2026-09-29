"""
WhatsApp business logic using PostgreSQL (whatsapp_tables). No Firestore.
"""
import calendar
import re
import os
import uuid as uuid_module
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from core.repository.company_repo import CompanyRepository
from products.market_planner.repository.theme_repo import ThemeRepository
from products.market_planner.tables import theme_tables
from products.market_planner.social_media.meta.whatsapp.tables import whatsapp_tables
from products.market_planner.social_media.meta.whatsapp.repository import whatsapp_repo

from shared.utils.error import error
from shared.utils.auth import auth

UTC = timezone.utc
_twilio_client = None

class WhatsAppService:
    def __init__(self, db: Session):
        self.db = db
        self.company_repo = CompanyRepository(self.db)
        self.theme_repo = ThemeRepository(self.db)
        self.whatsapp_account_repo = whatsapp_repo.WhatsAppAccountRepository(self.db)
        self.whatsapp_theme_delivery_repo = whatsapp_repo.WhatsAppThemeDeliveryRepository(self.db)
        self.whatsapp_post_delivery_repo = whatsapp_repo.WhatsAppPostDeliveryRepository(self.db)


    def get_twilio_client():
            """Return Twilio REST client (lazy init)."""
            global _twilio_client
            if _twilio_client is None:
                from twilio.rest import Client
                sid = os.getenv("TWILIO_ACCOUNT_SID", "")
                token = os.getenv("TWILIO_AUTH_TOKEN", "")
                _twilio_client = Client(sid, token)
            return _twilio_client


    def send_whatsapp_message(self, to: str, body: str, media_url: str | None = None) -> str:
        """Send a WhatsApp message via Twilio. Returns Twilio message SID."""
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        from_num = os.getenv("TWILIO_WHATSAPP_FROM")
        if not sid or not token or not from_num:
            raise ValueError(
                "Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env"
            )
        if not to.startswith("+"):
            to = f"+{to}"
        client = self.get_twilio_client()
        params = {"from_": from_num, "to": f"whatsapp:{to}", "body": body}
        if media_url:
            params["media_url"] = [media_url]
        msg = client.messages.create(**params)
        return msg.sid

    def get_company_phone(self, company_uuid: str) -> Optional[str]:
        """Return WhatsApp phone number for company (by UUID)."""
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            return None
        acc = self.whatsapp_account_repo.get_company_phone(company_id)
        return acc.phone_number if acc else None


    def get_or_create_whatsapp_account(self, company_uuid: str, phone_number: str) -> whatsapp_tables.WhatsAppAccount:
        """Get or create WhatsAppAccount for company. Uses company UUID."""
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            raise ValueError("Company not found")
        return self.whatsapp_account_repo.create_whatsapp_account(company_id, phone_number)
        

    def get_whatsapp_account(self, company_uuid: str) -> Optional[whatsapp_tables.WhatsAppAccount]:
        """Get WhatsAppAccount by company UUID."""
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            return None
        return self.whatsapp_account_repo.get_whatsapp_account(company_id)


    def resolve_theme_for_whatsapp_send(self, theme_id_param: str, company_uuid: str) -> Optional[theme_tables.Theme]:
        """
        Load a Theme row that belongs to the given company.

        Accepts path theme_id as integer primary key (e.g. "42") or Theme.uuid string.
        Returns None if not found, wrong company, or invalid id format.
        """
        company_id_int = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id_int:
            return None
        s = (theme_id_param or "").strip()
        theme: Optional[theme_tables.Theme] = None
        if s.isdigit():
            theme = self.theme_repo.get_theme_by_id(s)
        else:
            try:
                u = uuid_module.UUID(s)
                theme = self.theme_repo.get_theme_by_uuid(u)
            except (ValueError, TypeError):
                theme = None
        if not theme or theme.company_id != company_id_int:
            return None
        return theme


    def theme_whatsapp_options_from_db(self, theme: theme_tables.Theme) -> Tuple[str, str, str, str, str]:
        """
        Build WhatsApp copy from Theme.data JSONB (same shape as theme API), e.g.:

            {
            "month": "January",
            "month_id": 1,
            "themes": [
                {"title": "...", "description": "..."},
                {"title": "...", "description": "..."}
            ]
            }

        Returns (month, option1_title, option1_desc, option2_title, option2_desc).
        Raises ValueError if data is missing or does not contain two themes with titles.
        """
        raw: Any = theme.data
        if raw is None:
            raise ValueError('Theme has no data; generate or save themes first (expected JSON with "themes" array).')
        if not isinstance(raw, dict):
            raise ValueError("Theme data must be a JSON object")

        themes_list = raw.get("themes")
        if not isinstance(themes_list, list) or len(themes_list) < 2:
            raise ValueError('Theme data must include a "themes" array with at least 2 items')

        t1, t2 = themes_list[0], themes_list[1]
        if not isinstance(t1, dict) or not isinstance(t2, dict):
            raise ValueError('Each item in "themes" must be an object with title and description')

        def _title(t: dict) -> str:
            return (t.get("title") or "").strip()

        def _desc(t: dict) -> str:
            return (t.get("description") or t.get("desc") or "").strip()

        o1t, o1d = _title(t1), _desc(t1)
        o2t, o2d = _title(t2), _desc(t2)
        if not o1t or not o2t:
            raise ValueError("Both themes must have a non-empty title")

        month = (raw.get("month") or "").strip()
        if not month and theme.month:
            month = str(theme.month).strip()
        if not month:
            mid = raw.get("month_id")
            if isinstance(mid, int) and 1 <= mid <= 12:
                month = calendar.month_name[mid]
            elif isinstance(mid, str) and mid.isdigit():
                mi = int(mid)
                if 1 <= mi <= 12:
                    month = calendar.month_name[mi]
        if not month:
            month = "this month"

        return month, o1t, o1d, o2t, o2d


    def create_theme_delivery(
        self,
        company_uuid: str,
        message_token: str,
        recipient_phone: str,
        twilio_sid: str,
        month: str,
        option1_title: str,
        option1_desc: str,
        option2_title: str,
        option2_desc: str,
        theme_id: Optional[int] = None,
     ) -> whatsapp_tables.WhatsAppThemeDelivery:
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            raise ValueError("Company not found")
        delivery = self.whatsapp_theme_delivery_repo.create_theme_delivery(company_id, theme_id, recipient_phone, message_token, twilio_sid, month, option1_title, option1_desc, option2_title, option2_desc)
        if not delivery:
            raise ValueError("Failed to create theme delivery")
        return delivery

    def create_post_delivery(
        self,
        company_uuid: str,
        message_token: str,
        recipient_phone: str,
        twilio_sid: str,
        post_id: Optional[int] = None,
     ) -> whatsapp_tables.WhatsAppPostDelivery:
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            raise ValueError("Company not found")
        delivery = self.whatsapp_post_delivery_repo.create_post_delivery(company_id, message_token, recipient_phone, twilio_sid, post_id)
        if not delivery:
            raise ValueError("Failed to create post delivery")
        return delivery
        

    def supersede_pending_themes(self, company_id: int, except_message_token: str) -> None:
        """Set status=superseded for pending theme deliveries in company, except the given token."""
        return self.whatsapp_theme_delivery_repo.supersede_pending_themes(company_id, except_message_token)


    def get_theme_delivery_by_token(self, message_token: str) -> Optional[whatsapp_tables.WhatsAppThemeDelivery]:
        return self.whatsapp_theme_delivery_repo.get_theme_delivery_by_token(message_token)


    def get_theme_delivery_for_status(
        self,
        theme_id_param: str,
        company_uuid: Optional[str] = None,
     ) -> Tuple[Optional[whatsapp_tables.WhatsAppThemeDelivery], str]:
        """
        Resolve a WhatsAppThemeDelivery for GET .../whatsapp/themes/{id}/status.

        - If ``theme_id_param`` looks like a message token (starts with ``tp_``), match
        ``message_token`` exactly.
        - Otherwise treat as ``themes`` row: numeric ``themes.id`` or ``themes.uuid`` string.
        Returns the **latest** delivery for that theme (by ``created_at``), optionally
        scoped by ``company_uuid``.

        Returns ``(delivery, theme_id_for_json)`` where ``theme_id_for_json`` is the
        WhatsApp reply token when known (so clients always get ``tp_...`` in the payload).
        """
        s = (theme_id_param or "").strip()
        if not s:
            return None, ""

        company_id_int: Optional[int] = None
        if company_uuid:
            company_id_int = self.company_repo.get_company_id_from_uuid(company_uuid)

        # 1) WhatsApp message token
        if s.startswith("tp_"):
            d = self.get_theme_delivery_by_token(s)
            if not d:
                return None, s
            if company_id_int and d.company_id != company_id_int:
                return None, s
            return d, s

        # 2) themes.id (integer PK)
        theme_db_id: Optional[int] = None
        if s.isdigit():
            theme = self.theme_repo.get_theme_by_id(int(s))
            if not theme:
                return None, s
            if company_id_int and theme.company_id != company_id_int:
                return None, s
            theme_db_id = theme.id
        else:
            try:
                u = uuid_module.UUID(s)
            except (ValueError, TypeError):
                return None, s
            theme = self.theme_repo.get_theme_by_uuid(u)
            if not theme:
                return None, s
            if company_id_int and theme.company_id != company_id_int:
                return None, s
            theme_db_id = theme.id

        q = self.whatsapp_theme_delivery_repo.get_theme_delivery_by_theme_id(theme_db_id)
        if company_id_int:
            q = q.filter(whatsapp_tables.WhatsAppThemeDelivery.company_id == company_id_int)
        d = q.order_by(whatsapp_tables.WhatsAppThemeDelivery.created_at.desc()).first()
        if not d:
            return None, s
        out_id = d.message_token or s
        return d, out_id


    def get_post_delivery_by_token(self, message_token: str) -> Optional[whatsapp_tables.WhatsAppPostDelivery]:
        return self.whatsapp_post_delivery_repo.get_post_delivery_by_token(message_token)
        

    def update_theme_delivery_answered(
        self, delivery_id: int, selected_option: str, selected_option_title: Optional[str] = None, selected_option_desc: Optional[str] = None
     ) -> None:
        return self.whatsapp_theme_delivery_repo.update_theme_delivery_answered(delivery_id, selected_option, selected_option_title, selected_option_desc)
        

    def update_post_delivery_status(self, delivery_id: int, status: str) -> None:
        """status: 'approved' or 'needs_changes'."""
        return self.whatsapp_post_delivery_repo.update_post_delivery_status(delivery_id, status)
        


    def list_theme_deliveries(self, company_uuid: str, status: Optional[str] = None) -> list:
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            return []
        return self.whatsapp_theme_delivery_repo.list_theme_deliveries(company_id, status)
        


    def list_post_deliveries(self, company_uuid: str, status: Optional[str] = None) -> list:
        company_id = self.company_repo.get_company_id_from_uuid(company_uuid)
        if not company_id:
            return []
        
        return self.whatsapp_post_delivery_repo.list_post_deliveries(company_id, status)
        


    def theme_delivery_to_status_response(self, d: whatsapp_tables.WhatsAppThemeDelivery, theme_id: str) -> dict:
        return {
            "theme_id": theme_id,
            "theme_db_id": d.theme_id,
            "status": d.status,
            "selected_option": d.selected_option,
            "selected_option_title": d.selected_option_title,
            "selected_option_desc": d.selected_option_desc,
            "month": d.month,
            "option1_title": d.option1_title,
            "option1_desc": d.option1_desc,
            "option2_title": d.option2_title,
            "option2_desc": d.option2_desc,
            "sent_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "recipient": d.recipient_phone,
            "company_id": str(d.company.uuid) if d.company else None,
        }


    def post_delivery_to_status_response(self, d: whatsapp_tables.WhatsAppPostDelivery, post_id: str) -> dict:
        return {
            "post_id": post_id,
            "status": d.status,
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "rejected_at": d.rejected_at.isoformat() if d.rejected_at else None,
            "sent_at": d.created_at.isoformat() if d.created_at else None,
            "processed_at": d.updated_at.isoformat() if d.updated_at else None,
            "recipient": d.recipient_phone,
            "company_id": str(d.company.uuid) if d.company else None,
            "twilio_sid": d.twilio_message_sid,
        }


    def match_replies_impl(
        self,
        user_number: Optional[str],
        company_uuid: Optional[str],
        window_minutes: int = 1440,
        limit: int = 100,
     ) -> dict:
        """
        Match Twilio outbound messages (with token) to inbound replies and update delivery status in DB.
        Call with either user_number or company_uuid. Raises ValueError for invalid args or missing company.
        """

        if not user_number and not company_uuid:
            raise ValueError("Provide user_number or company_id")
        clean_user = None
        if company_uuid and not user_number:
            acc = self.get_whatsapp_account(company_uuid)
            if not acc:
                raise ValueError("Company not found")
            pn = acc.phone_number or ""
            if not pn:
                raise ValueError("Company has no phone number")
            clean_user = pn if pn.startswith("+") else f"+{pn}"
        else:
            clean_user = user_number if (user_number or "").startswith("+") else f"+{user_number or ''}"

        client = self.get_twilio_client()
        formatted_user = f"whatsapp:{clean_user}"
        outbound_msgs = list(client.messages.list(to=formatted_user, limit=limit))
        inbound_msgs = list(client.messages.list(from_=formatted_user, limit=limit))
        inbound_sorted = sorted(inbound_msgs, key=lambda m: m.date_created or datetime(1970, 1, 1, tzinfo=UTC))
        token_re = re.compile(r"\[#(tp_\w+|post_\w+)\]")
        theme_responses = {"1", "2"}
        post_approve = {"yes", "ja", "ok", "approve", "approved"}
        post_reject = {"no", "nej", "change", "changes", "reject", "rejected"}
        window = timedelta(minutes=window_minutes)
        used_inbound = set()
        matched = []
        updated = []

        for m in sorted(outbound_msgs, key=lambda x: x.date_created or datetime(1970, 1, 1, tzinfo=UTC), reverse=True):
            body = (m.body or "").strip()
            tmatch = token_re.search(body)
            if not tmatch:
                continue
            token = tmatch.group(1)
            sent_at = m.date_created or datetime(1970, 1, 1, tzinfo=UTC)
            reply = None
            for im in inbound_sorted:
                if not im.body or not im.date_created or im.sid in used_inbound or im.date_created <= sent_at:
                    continue
                if (im.date_created - sent_at) > window:
                    break
                text = (im.body or "").strip().lower()
                if token.startswith("tp_"):
                    if text in theme_responses:
                        reply = im
                        break
                elif token.startswith("post_"):
                    if text in post_approve or text in post_reject:
                        reply = im
                        break
            if not reply:
                continue
            used_inbound.add(reply.sid)
            reply_text = (reply.body or "").strip().lower()

            if token.startswith("tp_") and reply_text in theme_responses:
                d = self.get_theme_delivery_by_token(token)
                if d and d.status != "answered":
                    title = d.option1_title if reply_text == "1" else d.option2_title
                    desc = d.option1_desc if reply_text == "1" else d.option2_desc
                    self.update_theme_delivery_answered(d.id, reply_text, title, desc)
                    updated.append({"type": "theme", "id": token, "selection": reply_text, "reply_sid": reply.sid})
                matched.append({"out_sid": m.sid, "in_sid": reply.sid, "token": token})
            elif token.startswith("post_"):
                status = "approved" if reply_text in post_approve else ("needs_changes" if reply_text in post_reject else None)
                if status:
                    d = self.get_post_delivery_by_token(token)
                    if d and d.status not in ("approved", "needs_changes"):
                        self.update_post_delivery_status(d.id, status)
                        updated.append({"type": "post", "id": token, "status": status, "reply_sid": reply.sid})
                    matched.append({"out_sid": m.sid, "in_sid": reply.sid, "token": token})

        return {
            "user": clean_user,
            "matched": matched,
            "updated": updated,
            "outbound_checked": len(outbound_msgs),
            "inbound_checked": len(inbound_msgs),
        }

    def logout_company(self, company_id, user):
        try:
            company_int_id = auth.check_user_company_access(company_id, user["uid"], self.db)
        except ValueError as e:
            raise error.PermissionDenied(str(e))
        
        company = self.company_repo.get_company(company_id)
        if not company:
            raise error.NotFound("Company not found")

        success = self.whatsapp_account_repo.delete_whatsapp_account(company.id)
        if not success:
            raise error.InternalServerError("Failed to logout company")
        return {"message": "Company logged out successfully", "company_id": company_id}

        
    def send_reminders(self, hours, company_id, user):
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=hours)
        results = {"themes_reminded": [], "posts_reminded": [], "total_reminders": 0, "errors": []}

        if company_id:
            company_int_id = auth.check_user_company_access(company_id, user["uid"], self.db)
            company = self.company_repo.get_company(company_id)
            accs = self.whatsapp_account_repo.get_whatsapp_account(company.id)
        else:
            accs = self.whatsapp_account_repo.get_all_whatsapp_accounts()

        for acc in accs:
            if not acc.phone_number:
                continue
            cid = str(acc.company.uuid) if acc.company else None
            if company_id and cid != company_id:
                continue
            phone = acc.phone_number if acc.phone_number.startswith("+") else f"+{acc.phone_number}"

            themes = self.whatsapp_theme_delivery_repo.get_pending_theme_deliveries(acc.company_id, cutoff)

            for d in themes:
                try:
                    msg = f"⏰ Reminder: We're waiting for your theme selection for {d.month or 'this month'}! Reply with *1* or *2* to choose."
                    self.send_whatsapp_message(phone, msg, None)
                    results["themes_reminded"].append({"theme_id": d.message_token, "company_id": cid, "sent_at": d.created_at.isoformat() if d.created_at else None})
                    results["total_reminders"] += 1
                except Exception as e:
                    results["errors"].append({"theme_id": d.message_token, "error": str(e)})

            posts = self.whatsapp_post_delivery_repo.get_pending_post_deliveries(acc.company_id, cutoff)
            for d in posts:
                try:
                    msg = "⏰ Reminder: We're waiting for your approval. Reply *ja* to approve or *nej* for changes."
                    self.send_whatsapp_message(phone, msg, None)
                    results["posts_reminded"].append({"post_id": d.message_token, "company_id": cid, "sent_at": d.created_at.isoformat() if d.created_at else None})
                    results["total_reminders"] += 1
                except Exception as e:
                    results["errors"].append({"post_id": d.message_token, "error": str(e)})

        return {"success": True, "timestamp": now.isoformat(), "cutoff_hours": hours, "companies_processed": len(accs), **results}
