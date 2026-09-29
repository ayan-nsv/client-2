from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPAuthorizationCredentials



from core.repository.billing_repo import BillingRepository
from shared.utils.constants import constants
from shared.utils.auth import auth


STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")
FREE_MINUTES_BY_TIER = {
    "FREE": 20,
    "PAID": 100,
}


class BillingService:
    def __init__(self, db: Session):
        self.repo = BillingRepository(db)

    def get_all_billing_usage(self):
        companies = self.repo.get_all_companies()

        return [
            self.get_billing_usage_for_company(
                company_int_id=company.id,
                tier=company.tier or "FREE",
                agent_category=company.agent_category,
                eco_id=company.uuid,
            )
            for company in companies
        ]

    def previous_calendar_month_stockholm(self, reference: datetime | None = None,) -> tuple[date, date, datetime, datetime]:
        """Return (period_start, period_end, start_dt_utc, end_dt_utc) for previous month in Stockholm."""
        now = reference or datetime.now(constants.STOCKHOLM_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=constants.STOCKHOLM_TZ)
        else:
            now = now.astimezone(constants.STOCKHOLM_TZ)

        first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_instant_previous = first_of_current - timedelta(microseconds=1)
        first_of_previous = last_instant_previous.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        period_start = first_of_previous.date()
        period_end = last_instant_previous.date()

        start_dt_utc = first_of_previous.astimezone(ZoneInfo("UTC"))
        end_dt_utc = last_instant_previous.astimezone(ZoneInfo("UTC"))
        return period_start, period_end, start_dt_utc, end_dt_utc
    

    def current_calendar_month_stockholm(
        self,
        reference: datetime | None = None,
    ) -> tuple[date, date, datetime, datetime]:
        """Return (period_start, period_end, start_dt_utc, end_dt_utc) for current month in Stockholm."""
        now = reference or datetime.now(STOCKHOLM_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=STOCKHOLM_TZ)
        else:
            now = now.astimezone(STOCKHOLM_TZ)

        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            first_of_next = first_of_month.replace(year=now.year + 1, month=1)
        else:
            first_of_next = first_of_month.replace(month=now.month + 1)
        last_instant = first_of_next - timedelta(microseconds=1)

        period_start = first_of_month.date()
        period_end = last_instant.date()
        start_dt_utc = first_of_month.astimezone(ZoneInfo("UTC"))
        end_dt_utc = last_instant.astimezone(ZoneInfo("UTC"))
        return period_start, period_end, start_dt_utc, end_dt_utc


    def stockholm_month_key(self, reference: datetime | None = None) -> str:
        """YYYY-MM for the current calendar month in Europe/Stockholm."""
        period_start, _, _, _ = self.current_calendar_month_stockholm(reference)
        return period_start.strftime("%Y-%m")


    def get_current_month_call_minutes(
        self,
        company_id: int,
        reference: datetime | None = None,
    ) -> tuple[int, date, date]:

        # Determine current Stockholm calendar month
        period_start, period_end, start_dt_utc, end_dt_utc = (
            self.current_calendar_month_stockholm(reference)
        )

        # Fetch total call duration from repository
        total_seconds = self.repo.get_total_call_seconds_for_period(
            company_id=company_id,
            start_dt_utc=start_dt_utc,
            end_dt_utc=end_dt_utc,
        )

        # Convert seconds to minutes
        total_minutes = round(total_seconds / 60.0)

        return (
            total_minutes,
            period_start,
            period_end,
        )



    def free_minutes_for_tier(self, tier: str | None) -> int:
        return constants.FREE_MINUTES_BY_TIER.get((tier or "FREE").upper(), constants.FREE_MINUTES_BY_TIER["FREE"])

    def get_billing_usage_for_company(
        self,
        company_int_id: int,
        tier: str | None,
        agent_category: str |None,
        eco_id: str,
        reference: datetime | None = None,
    ):
        period_start, period_end, start_dt_utc, end_dt_utc = (
            self.previous_calendar_month_stockholm(reference)
        )

        total_seconds, sms_sent = self.repo.get_billing_usage_metrics(
            company_int_id,
            start_dt_utc,
            end_dt_utc,
            period_start,
            period_end,
        )

        total_minutes = round(float(total_seconds) / 60)

        free_minutes = self.free_minutes_for_tier(tier)

        overage_minutes = max(
            0,
            total_minutes - free_minutes,
        )

        return {
            "ecoId": eco_id,
            "overage_minutes": overage_minutes,
            "sms_sent": sms_sent,
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "agentCategory": agent_category,
        }

    def get_billing_usage(self, eco_id):
        company = self.repo.get_company_by_uuid(eco_id)

        return self.get_billing_usage_for_company(
            company_int_id=company.id,
            tier=company.tier or "FREE",
            agent_category=company.agent_category,
            eco_id=eco_id,
        )
    
    @staticmethod
    def get_billing_api_user(
        credentials: HTTPAuthorizationCredentials = Depends(auth.security),
        admin_secret: str = Depends(auth.admin_secret_security),
    ):
        """
        Salesforce billing usage auth: Authorization Bearer <ADMIN_SECRET>
        or X-ADMIN-SECRET header (same value as ADMIN_SECRET env).
        """
        if constants.ADMIN_SECRET and admin_secret and admin_secret == constants.ADMIN_SECRET:
            return {
                "uid": constants.ADMIN_SECRET_UID,
                "role": "admin",
                "email": "admin@holdflight.se",
                "name": "Admin Secret User",
                "is_admin_secret": True,
            }

        if not constants.ADMIN_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ADMIN_SECRET is not configured",
            )
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header or X-ADMIN-SECRET",
            )
        if credentials.credentials != constants.ADMIN_SECRET:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return {
            "uid": constants.ADMIN_SECRET_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Admin Secret User",
            "is_admin_secret": True,
        }