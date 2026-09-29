import logging
from datetime import datetime

from shared.database.postgres.database_config import get_session_local

from core.tables import usage_tables 
from core.repository.company_repo import CompanyRepository

# logger = logging.getLogger(__name__)


def log_email_sent(company_id: str | int | None, *, count: int = 1) -> None:
    """Record successful email delivery in UsageMetric (mirrors SMS usage logging)."""
    if not company_id:
        return

    try:

        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            company_id_int = CompanyRepository(db).get_company_id_from_uuid(str(company_id))
            metric = usage_tables.UsageMetric(
                company_id=company_id_int,
                date=datetime.now().date(),
                feature="email_sent",
                action="send",
                count=count,
            )
            db.add(metric)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        pass
        # logger.error("Failed to log email usage metric: %s", e)
