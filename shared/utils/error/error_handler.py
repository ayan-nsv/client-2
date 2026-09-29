from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from core.repository.company_repo import CompanyRepository
from shared.logger.tables import log_tables 
from shared.logger.schema import log_schema 


def _error_text_includes_quota_or_rate_limit(error: Exception) -> bool:
    parts = [str(error)]
    cause = error.__cause__
    while cause is not None:
        parts.append(str(cause))
        cause = getattr(cause, "__cause__", None)
    combined = " ".join(parts).lower()
    return (
        "429" in combined
        or "resource_exhausted" in combined
        or "quota exceeded" in combined
        or "rate limit" in combined
    )


def handle_error(error: Exception):
    if _error_text_includes_quota_or_rate_limit(error):
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": (
                    "Image generation is unavailable due to Gemini API quota or rate limits. "
                    "Enable billing for your Google AI project, check model access for image generation, "
                    "or try again later."
                ),
            },
        )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(error)},
    )


def error_response(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": message,
            "data": []
        }
    )

def format_http_exception_content(detail) -> dict:
    """Normalize HTTPException.detail into the API's standard JSON error shape."""
    content = {
        "success": False,
        "message": "Request failed",
        "data": [],
    }
    if isinstance(detail, str):
        content["message"] = detail
    elif isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail")
        if message is not None:
            content["message"] = str(message)
        if detail.get("code"):
            content["code"] = detail["code"]
    elif isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict) and first.get("msg"):
            content["message"] = str(first["msg"])
        else:
            content["message"] = str(detail)
    return content

    

def record_log(log_request: log_schema.LogRequest, db: Session):
    if log_request.company_id:
        company_id_int = CompanyRepository(db).get_company_id_from_uuid(log_request.company_id)
    else:
        company_id_int = None
    log_record = log_tables.LogRecord(
        company_id=company_id_int,
        severity=log_request.severity,
        message=log_request.message,
        status=log_request.status,
        status_code=log_request.status_code,
        timestamp=log_request.timestamp
    )
    db.add(log_record)
    db.commit()
    db.refresh(log_record)


_EMAIL_FAILURE_LABELS = {
    "daily_summary": "Daily summary email failed",
    "after_call": "After-call email failed",
    "status_down": "Status email failed (service down)",
    "status_restored": "Service restored email failed",
}


def email_failure_message(
    email_type: str,
    *,
    detail: str,
    recipient: str | None = None,
 ) -> str:
    """Build a consistent log_records.message prefix for email send failures."""
    prefix = _EMAIL_FAILURE_LABELS.get(email_type, "Email failed")
    err = detail.removeprefix("Error: ").strip()
    if recipient:
        return f"{prefix} to {recipient}: {err}"
    return f"{prefix}: {err}"


def record_integration_error(db: Session, company_id: str | int | None, status: str, error_message: str, status_code: int = 500, timestamp=None):
    
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
        
    company_id_int = None
    if company_id:
        if isinstance(company_id, str):
            try:
                company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id)
            except Exception:
                if company_id.isdigit():
                    company_id_int = int(company_id)
                else:
                    company_id_int = None
        elif isinstance(company_id, int):
            company_id_int = company_id
            
    log_record = log_schema.LogRecord(
        company_id=company_id_int,
        severity="error",
        message=error_message,
        status=status,
        status_code=status_code,
        timestamp=timestamp
    )
    db.add(log_record)
    db.commit()
    db.refresh(log_record)



