"""Generic SendGrid senders.

Product-neutral on purpose: this is the only email code in ``shared``. Everything that
knew about calls, agents, daily summaries or usage warnings moved to
``products/telephone_agent/vapi/emails.py``, because it was telephone_agent behaviour
that happened to live under ``shared`` and made the platform unable to run without
that product installed.

Credentials come straight from the environment. ``shared.utils.constants.constants``
looks like the natural home, but its key is misspelled ``SENDGRID_API_KEY``, so reading
from there raises AttributeError — see emailconfig.py, which does exactly that.
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from shared.utils.email.email_usage_service import log_email_sent


SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "").strip()
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "").strip()

_SWEDISH_LOCAL_TZ = ZoneInfo("Europe/Stockholm")


class EmailServiceError(Exception):
    """Custom exception for email service errors"""
    pass


class EmailServiceError(Exception):
    """Custom exception for email service errors"""
    pass

async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = None,
    company_id: Optional[str | int] = None,
) -> bool:
    """
    Send raw HTML/Text email using SendGrid (used by roles/invitations).
    """


    if not SENDGRID_API_KEY or not SENDGRID_FROM_EMAIL:
        # logger.error("app_sendgrid_send_email_config_missing")
        raise EmailServiceError("SendGrid configuration is missing in environment variables")

    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )
    # We can skip explicit plain text Content addition as SendGrid falls back cleanly, 
    # but could attach if needed. Mail() handles html_content natively.

    def _send():
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        # logger.info("app_sendgrid_send_email_sending subject=%s", subject)
        sg.send(message)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send)
        # logger.info("app_sendgrid_send_email_ok subject=%s", subject)
        if company_id:
            
            recipient_count = len([addr.strip() for addr in to_email.split(",") if addr.strip()])
            log_email_sent(company_id, count=max(recipient_count, 1))
        return True
    except Exception as e:
        # logger.exception("app_sendgrid_send_email_failed to=%s subject=%s error=%s", to_email, subject, e)
        raise EmailServiceError(f"Failed to send email via SendGrid: {str(e)}")

async def send_template_email(
    to_email: str,
    template_id: str,
    dynamic_data: dict,
) -> bool:
    """Send an email using a SendGrid dynamic template.

    ``to_email`` may be a single address or a comma-separated list. ``dynamic_data``
    keys map to the ``{{handlebars}}`` placeholders defined in the template.
    """
 
 

    if not SENDGRID_API_KEY or not SENDGRID_FROM_EMAIL or not template_id:
        # logger.error("app_sendgrid_template_config_missing")
        raise EmailServiceError("SendGrid configuration is missing")

    recipients = [addr.strip() for addr in str(to_email).split(",") if addr.strip()]
    if not recipients:
        raise EmailServiceError("No valid recipient email provided")

    message = Mail(from_email=SENDGRID_FROM_EMAIL, to_emails=recipients)
    message.template_id = template_id
    message.dynamic_template_data = dynamic_data

    def _send():
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        return sg.send(message)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send)
        # logger.info("app_sendgrid_template_email_ok template=%s", template_id)
        return True
    except Exception as e:
        # logger.exception(
        #     "app_sendgrid_template_email_failed to=%s template=%s error=%s",
        #     to_email,
        #     template_id,
        #     e,
        # )
        raise EmailServiceError(f"Failed to send email via SendGrid: {str(e)}")
