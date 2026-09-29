from sqlalchemy import func
from datetime import date, datetime
from shared.utils.error import error
from sqlalchemy.orm import Session

from shared.database.postgres.database_config import get_db
from core.product_hooks import collect_billing_usage
from core.tables import company_tables
from core.tables import usage_tables

# Metric key products report call time under. Core defines the billing contract;
# products supply the numbers (see core.product_hooks.collect_billing_usage).
CALL_SECONDS = "call_seconds"



class BillingRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_all_companies(self):
        return (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid.isnot(None))
            .all()
        )
    def get_billing_usage_metrics(
        self,
        company_id: int,
        start_dt_utc: datetime,
        end_dt_utc: datetime,
        period_start: date,
        period_end: date,
    ):
        total_seconds = self.get_total_call_seconds_for_period(
            company_id,
            start_dt_utc,
            end_dt_utc,
        )

        sms_sent = (
            self.db.query(
                func.coalesce(
                    func.sum(usage_tables.UsageMetric.count),
                    0,
                )
            )
            .filter(
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.feature == "sms_sent",
                usage_tables.UsageMetric.date >= period_start,
                usage_tables.UsageMetric.date <= period_end,
            )
            .scalar()
        )

        return (
            float(total_seconds or 0),
            int(sms_sent or 0),
        )

    def get_company_by_uuid(self, company_uuid):
        company = (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
        )

        if company is None:
            raise error.NotFound(f"Company {company_uuid} not found")

        return company

    def get_total_call_seconds_for_period(
        self,
        company_id: int,
        start_dt_utc: datetime,
        end_dt_utc: datetime,
    ) -> float:
        usage = collect_billing_usage(
            self.db,
            company_id,
            start_dt_utc,
            end_dt_utc,
        )

        return float(usage.get(CALL_SECONDS, 0.0))