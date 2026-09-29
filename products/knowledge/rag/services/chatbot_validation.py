"""Shared email/URL validation for chatbot conversation fields."""
import re
from typing import Optional

from pydantic import EmailStr, HttpUrl, TypeAdapter, ValidationError

_email_adapter = TypeAdapter(EmailStr)
_url_adapter = TypeAdapter(HttpUrl)
_HEX_RGB_RE = re.compile(r"^#([0-9A-Fa-f]{3})$")
_HEX_RRGGBB_RE = re.compile(r"^#([0-9A-Fa-f]{6})$")
DEFAULT_CHATBOT_PRIMARY_COLOR = "#2563EB"

ALLOWED_MESSAGE_SENDERS = ("visitor", "bot")
ALLOWED_LEAD_STATUSES = (
    "new",
    "contacted",
    "qualified",
    "converted",
    "closed",
    "spam",
)


class ChatbotFieldValidationError(ValueError):
    """Raised when a chatbot field fails validation."""


def validate_visitor_email(value: Optional[str]) -> Optional[str]:
    """Normalize an email address when provided; empty values become None."""
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip().lower()
    try:
        return str(_email_adapter.validate_python(normalized))
    except ValidationError as exc:
        raise ChatbotFieldValidationError("Invalid email address") from exc


def validate_primary_color(value: Optional[str]) -> Optional[str]:
    """Normalize a widget hex color to #RRGGBB. Empty values become None."""
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip()
    rgb_match = _HEX_RGB_RE.fullmatch(normalized)
    if rgb_match:
        digits = rgb_match.group(1)
        return f"#{''.join(ch * 2 for ch in digits)}".upper()

    rrggbb_match = _HEX_RRGGBB_RE.fullmatch(normalized)
    if rrggbb_match:
        return f"#{rrggbb_match.group(1)}".upper()

    raise ChatbotFieldValidationError(
        "primary_color must be a hex color such as #2563EB or #FFF"
    )


def validate_website_url(value: Optional[str]) -> Optional[str]:
    """Normalize and validate an http(s) website URL. Empty values become None."""
    if value is None:
        return None

    clean = str(value).strip()
    if not clean:
        return None

    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"

    try:
        return str(_url_adapter.validate_python(clean)).rstrip("/")
    except ValidationError as exc:
        raise ChatbotFieldValidationError("Invalid website URL") from exc


def validate_message_sender(value: str) -> str:
    """Validate a chatbot message sender. Only 'visitor' or 'bot' are allowed."""
    if value is None or not str(value).strip():
        raise ChatbotFieldValidationError("sender is required")

    normalized = str(value).strip().lower()
    if normalized not in ALLOWED_MESSAGE_SENDERS:
        allowed = ", ".join(ALLOWED_MESSAGE_SENDERS)
        raise ChatbotFieldValidationError(f"sender must be one of: {allowed}")
    return normalized


def validate_lead_status(value: Optional[str]) -> Optional[str]:
    """Validate a chatbot lead status. None falls back to the column default."""
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip().lower()






    

    if normalized not in ALLOWED_LEAD_STATUSES:
        allowed = ", ".join(ALLOWED_LEAD_STATUSES)
        raise ChatbotFieldValidationError(f"status must be one of: {allowed}")
    return normalized
