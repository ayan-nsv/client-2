import os
from sqlalchemy.orm import Session

from shared.utils.constants.constants import (
    ONBOARDING_ADMIN_EMAIL_RECIPIENTS,
    SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID
)
from shared.logger.log import setup_logger
from core.workers.tasks import send_email_task

logger = setup_logger("marketing-app")

_DEFAULT_APP_ORIGIN = "https://apps.holdflight.se"


def app_origin() -> str:
    raw = (os.getenv("FRONTEND_URL") or _DEFAULT_APP_ORIGIN).strip().rstrip("/")
    if raw and not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return raw or _DEFAULT_APP_ORIGIN


def resolve_onboarding_admin_recipients(db: Session) -> str:
    """Return comma-separated admin inboxes for onboarding approval alerts."""
    del db
    return ONBOARDING_ADMIN_EMAIL_RECIPIENTS


def enqueue_onboarding_admin_approval_email(
    db: Session,
    *,
    user_email: str,
    user_name: str | None,
    user_uuid: str,
    company_name: str,
    company_uuid: str,
) -> None:
    """Notify platform admins that a new user needs one-time onboarding approval."""
    recipients = resolve_onboarding_admin_recipients(db)
    if not recipients:
        logger.warning("onboarding_admin_email_skipped reason=no_recipients user_uuid=%s", user_uuid)
        return
    if not SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID:
        logger.error(
            "onboarding_admin_email_skipped reason=missing_template_id user_uuid=%s",
            user_uuid,
        )
        return

    display_name = (user_name or "").strip() or user_email
    safe_company_name = (company_name or "").strip() or "New company"
    origin = app_origin()

    dynamic_data = {
        "email_subject": f"Action required: approve {display_name}",
        "user_email": user_email,
        "user_name": display_name,
        "user_uuid": user_uuid,
        "company_name": safe_company_name,
        "company_uuid": company_uuid,
        "action_url": f"{origin}/",
    }

    try:
        send_email_task.delay(
            recipient_email=recipients,
            template_id=SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID,
            dynamic_data=dynamic_data,
        )
        logger.info(
            "onboarding_admin_email_enqueued user_uuid=%s company_uuid=%s recipients=%s template_id=%s",
            user_uuid,
            company_uuid,
            recipients,
            SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID,
        )
    except Exception:
        logger.exception(
            "onboarding_admin_email_enqueue_failed user_uuid=%s company_uuid=%s",
            user_uuid,
            company_uuid,
        )
