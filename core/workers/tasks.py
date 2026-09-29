import asyncio
from datetime import datetime, timezone

from celery import shared_task
from fastapi import HTTPException

from shared.database.postgres import serialization
from shared.database.postgres.database_config import get_db
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema
from shared.utils.email import emailconfig
from shared.utils.error import error_handler

logger = setup_logger("marketing-app")

@shared_task(name="core.send_email", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def send_email_task(recipient_email: str, template_id: str, dynamic_data: dict):
    """
    Send a SendGrid dynamic-template email.
    """
    if not recipient_email or not str(recipient_email).strip():
        raise ValueError("recipient_email is required")
    if not template_id or not str(template_id).strip():
        raise ValueError("template_id is required")

    logger.info(
        "send_email_task_started recipient=%s template_id=%s",
        recipient_email,
        template_id,
    )
    try:
        asyncio.run(emailconfig.send_template_email(recipient_email, template_id, dynamic_data or {}))
        logger.info(
            "send_email_task_ok recipient=%s template_id=%s",
            recipient_email,
            template_id,
        )
    except Exception:
        logger.exception(
            "send_email_task_failed recipient=%s template_id=%s",
            recipient_email,
            template_id,
        )
        raise


@shared_task(name="core.update_company", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def update_company_task(company_id: str, company_data: dict):
    from core.services.company_service import CompanyService

    db = next(get_db())
    try:
        logger.info(
            "update_company_task (celery) company_uuid=%s keys=%s",
            company_id,
            sorted(company_data.keys()),
        )
        company_record = CompanyService(db).mutate_company_from_payload(company_id, company_data)
        db.commit()
        db.refresh(company_record)
        logger.info("update_company_task done company_uuid=%s company_db_id=%s", company_id, company_record.id)
        return {
            "status": "success",
            "message": "Company updated successfully",
            "data": serialization.sqlalchemy_to_dict(company_record),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(company_id=company_id, severity="error", message=f"Failed to update company: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        logger.error(
            "update_company_task failed company_uuid=%s error=%s",
            company_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Failed to update company: {str(e)}") from e
    finally:
        db.close()
