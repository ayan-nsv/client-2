"""Lead detection / extraction for chatbot conversations.

When a chatbot conversation is closed, we inspect its messages to decide whether
the visitor actually provided the lead details the chatbot was configured to
collect. If so, the conversation is flagged as a lead and a record is managed in
``chatbot_leads``.
"""

import json
import re
from typing import Iterable, List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException
import uuid

from products.market_planner.integrations.openai.gpt_service import get_openai_client
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def build_transcript(messages: Iterable) -> str:
    """Render conversation messages as a readable transcript.

    ``messages`` must be ordered oldest-first. Each item is expected to expose
    ``sender`` and ``message`` attributes (``ChatbotMessages`` rows).
    """
    blocks: List[str] = []
    for msg in messages:
        sender = (getattr(msg, "sender", "") or "").strip().lower()
        text = (getattr(msg, "message", "") or "").strip()
        if not text:
            continue
        label = "Visitor" if sender == "visitor" else "Chatbot"
        blocks.append(f"{label}:\n{text}")
    return "\n\n".join(blocks)


def _visitor_text(messages: Iterable) -> str:
    parts = []
    for msg in messages:
        if (getattr(msg, "sender", "") or "").strip().lower() == "visitor":
            text = (getattr(msg, "message", "") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def extract_lead_details(
    transcript: str,
    lead_fields: List[dict],
    *,
    messages: Optional[Iterable] = None,
) -> dict:
    """Decide whether the visitor supplied the configured lead fields.

    ``lead_fields`` is a list of ``{"field_name": str, "is_required": bool}``.

    Returns a dict::

        {
            "lead_created": bool,
            "captured_fields": {field_name: value, ...},  # only provided ones
        }

    A lead is considered created when every *required* field has a value. If no
    field is marked required, a lead is created as soon as any configured field
    has a value.
    """
    field_names = [
        (f.get("field_name") or "").strip()
        for f in (lead_fields or [])
        if (f.get("field_name") or "").strip()
    ]
    if not field_names:
        return {"lead_created": False, "captured_fields": {}}

    required_names = [
        (f.get("field_name") or "").strip()
        for f in (lead_fields or [])
        if (f.get("field_name") or "").strip() and f.get("is_required")
    ]

    captured = _extract_with_llm(transcript, field_names)
    if captured is None:
        # LLM unavailable - fall back to a lightweight heuristic so we don't
        # silently drop genuine leads.
        captured = _extract_with_heuristics(
            transcript if messages is None else _visitor_text(messages),
            field_names,
        )

    captured = {k: v for k, v in captured.items() if v and str(v).strip()}

    if required_names:
        lead_created = all(name in captured for name in required_names)
    else:
        lead_created = len(captured) > 0

    return {"lead_created": lead_created, "captured_fields": captured}


def _extract_with_llm(transcript: str, field_names: List[str]) -> Optional[dict]:
    """Ask the LLM to pull each configured field's value from the transcript.

    Returns a mapping ``{field_name: value_or_empty}`` or ``None`` on failure.
    """
    if not transcript.strip():
        return {name: "" for name in field_names}

    try:
        fields_list = ", ".join(field_names)
        system_content = (
            "You extract lead/contact details from a chatbot conversation "
            "transcript. Only return a value for a field when the VISITOR "
            "explicitly provided it during the conversation. If a field was not "
            "provided, return an empty string for it. Never invent values."
        )
        user_content = (
            f"Fields to extract: {fields_list}\n\n"
            "Return ONLY a JSON object whose keys are exactly the field names "
            "above and whose values are the visitor-provided values (empty "
            "string if not provided).\n\n"
            f"Transcript:\n{transcript}"
        )
        response = get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=400,
        )
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {name: "" for name in field_names}
        # Match keys case-insensitively back to the configured field names.
        lowered = {str(k).strip().lower(): v for k, v in data.items()}
        return {
            name: (lowered.get(name.strip().lower()) or "")
            for name in field_names
        }
    except Exception as exc:
        logger.warning("chatbot_lead_extract_llm_failed error=%s", exc)
        return None


def generate_lead_summary_en(transcript: str) -> str:
    """Summarize a chatbot conversation in ENGLISH only.

    Regardless of the conversation's original language, the returned summary is
    always written in English. Returns an empty string when there is nothing to
    summarize, and falls back to a truncated transcript if the LLM is unavailable.
    """
    if not transcript or not transcript.strip():
        return ""

    try:
        response = get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional assistant that summarizes chatbot "
                        "conversations between a website visitor and a bot. "
                        "STRICT RULE: Always write the summary in ENGLISH ONLY, "
                        "even if the conversation is in another language. "
                        "When the visitor asks to be contacted, phrase it as the "
                        "visitor requesting to be reached out to (by the team/company) "
                        "- do NOT say the visitor asked the chatbot/bot to reach out, "
                        "since the bot itself does not contact anyone. "
                        "Provide only the summary text, with no prefix."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Summarize this chatbot conversation in 3-5 professional "
                        "sentences, in English only. No prefix like 'Summary:'.\n\n"
                        f"{transcript}"
                    ),
                },
            ],
            max_tokens=200,
            temperature=0.5,
        )
        summary = (response.choices[0].message.content or "").strip()
        for prefix in ("summary:", "summary"):
            if summary.lower().startswith(prefix):
                summary = summary[len(prefix):].strip().lstrip(":").strip()
                break
        return summary
    except Exception as exc:
        logger.warning("chatbot_lead_summary_failed error=%s", exc)
        cleaned = transcript.strip().replace("\n", " ")
        return cleaned[:300] if len(cleaned) > 300 else cleaned


def build_lead_email_fields(
    visitor_email: Optional[str],
    captured_fields: dict,
) -> List[dict]:
    """Build the ordered ``fields`` list (``[{"label", "value"}, ...]``) for the
    lead notification email.

    Configured lead fields the visitor provided are listed in their captured
    order. The conversation's visitor email is always included (deduped against
    any captured email field).
    """
    rows: List[dict] = []
    has_email = False
    for label, value in (captured_fields or {}).items():
        if value is None or not str(value).strip():
            continue
        label_str = str(label).strip()
        value_str = str(value).strip()
        if "mail" in label_str.lower() or _EMAIL_RE.fullmatch(value_str):
            has_email = True
        rows.append({"label": label_str, "value": value_str})

    if not has_email and visitor_email and str(visitor_email).strip():
        rows.insert(0, {"label": "Email", "value": str(visitor_email).strip()})

    return rows


def _extract_with_heuristics(text: str, field_names: List[str]) -> dict:
    """Best-effort, dependency-free extraction used when the LLM is unavailable."""
    captured = {name: "" for name in field_names}
    if not text:
        return captured

    email_match = _EMAIL_RE.search(text)
    for name in field_names:
        lname = name.lower()
        if email_match and ("email" in lname or "e-mail" in lname or "mail" in lname):
            captured[name] = email_match.group(0)
    return captured


def get_chatbot(chatbot_id: str, db: Session):
    """Resolve a chatbot by its UUID string (with integer id fallback).

    Raises 404 if no matching chatbot exists.
    """
    from products.knowledge.rag.tables.chatbot_tables import ChatBot

    raw = str(chatbot_id).strip()

    try:
        chatbot_uuid = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        chatbot_uuid = None

    if chatbot_uuid is not None:
        chatbot = db.query(ChatBot).filter(ChatBot.uuid == chatbot_uuid).first()
        if chatbot:
            return chatbot

    if raw.isdigit():
        chatbot = db.query(ChatBot).filter(ChatBot.id == int(raw)).first()
        if chatbot:
            return chatbot

    raise HTTPException(status_code=404, detail="Chatbot not found")
