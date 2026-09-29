from sqlalchemy.orm import Session
from core.tables import usage_tables
from datetime import datetime, timezone

class UsageRepository:
    def __init__(self, db: Session):
        self.db = db

    def record_usage(self, company_id, user_id, feature, action, channel, count):
        usage = usage_tables.UsageMetric(
            company_id=company_id,
            user_id=user_id,
            date=datetime.now(timezone.utc).date(),
            feature=feature,
            action=action,
            channel=channel,
            count=count
        )

        self.db.add(usage)
        self.db.commit()
        self.db.refresh(usage)

        return usage

    def increment_usage(
        self,
        company_id,
        user_id,
        feature,
        channel,
     ):
        metric = (
            self.db.query(usage_tables.UsageMetric)
            .filter(
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.user_id == user_id,
                usage_tables.UsageMetric.feature == feature,
                usage_tables.UsageMetric.channel == channel,
                usage_tables.UsageMetric.date == datetime.now(timezone.utc).date(),
            )
            .first()
        )

        current = metric.count if metric else 0

        self.record_usage(
            db=self.db,
            company_id=company_id,
            user_id=user_id,
            feature=feature,
            action="generate",
            channel=channel,
            count=current + 1,
        )

        self.db.commit()