from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.repository.company_repo import CompanyRepository
from core.tables import usage_tables
from products.market_planner.tables import theme_tables

from shared.utils.error import error
from shared.database.postgres import serialization

from products.market_planner.integrations.openai.gpt_service import GPTservice


class ThemeRepository:
    def __init__(self, db: Session):
        self.db = db
        self.company_repo = CompanyRepository(db)



    def get_theme_by_id(self, id):
        return self.db.query(theme_tables.Theme).filter(theme_tables.Theme.id == int(id)).first()
    def get_theme_by_uuid(self, uuid):
        return self.db.query(theme_tables.Theme).filter(theme_tables.Theme.uuid == uuid).first()

    def get_theme(self, company_id, month_id):

        theme = (
            self.db.query(theme_tables.Theme)
            .filter(
                theme_tables.Theme.company_id == company_id,
                theme_tables.Theme.month_id == month_id,
            )
            .first()
        )

        if theme is None:
            raise error.NotFound(
                f"Theme for month {month_id} not found"
            )

        return theme

    def regenerate_month_theme(self, company_uuid, month_id):
        months = {
            1: "January",
            2: "February",
            3: "March",
            4: "April",
            5: "May",
            6: "June",
            7: "July",
            8: "August",
            9: "September",
            10: "October",
            11: "November",
            12: "December",
        }

        month_name = months[month_id]

        company = self.company_repo.get_company(company_uuid)

        company_data = serialization.sqlalchemy_to_dict(company)

        theme = (
            self.db.query(theme_tables.Theme)
            .filter(
                theme_tables.Theme.company_id == company.id,
                theme_tables.Theme.month_id == month_id,
            )
            .first()
        )

        existing = (
            serialization.sqlalchemy_to_dict(theme)
            if theme
            else None
        )

        generated = GPTservice().generate_theme(
            company_data,
            month_name,
            existing,
        )

        month_data = {
            "month_id": month_id,
            "month": month_name,
            "themes": generated["themes"],
        }

        if theme:
            theme.data = month_data
        else:
            theme = theme_tables.Theme(
                company_id=company.id,
                month_id=month_id,
                data=month_data,
            )
            self.db.add(theme)

        self.db.commit()
        self.db.refresh(theme)

        return month_data, company


    
    def record_theme_usage(self, company_id, user_id):
        metric = (
            self.db.query(usage_tables.UsageMetric)
            .filter(
                usage_tables.UsageMetric.user_id == user_id,
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.channel == "theme",
                usage_tables.UsageMetric.feature == "theme",
                usage_tables.UsageMetric.date == datetime.now().date(),
            )
            .first()
        )

        current = metric.count if metric else 0

        # Deferred: usage_service imports theme_service, which imports this module, so a
        # module-level import here would close an import cycle.
        from core.services.usage_service import UsageService

        UsageService(self.db).record_usage(
            company_id=company_id,
            user_id=user_id,
            feature="theme",
            action="regenerate",
            channel=None,
            count=current + 1,
        )

        self.db.commit()

    def save_all_themes(self, company_id, themes):
        existing = (
            self.db.query(theme_tables.Theme)
            .filter(theme_tables.Theme.company_id == company_id)
            .all()
        )

        existing_map = {
            theme.month_id: theme
            for theme in existing
        }

        for month in themes:
            record = existing_map.get(month["month_id"])

            if record:
                record.data = month
            else:
                self.db.add(
                    theme_tables.Theme(
                        company_id=company_id,
                        month_id=month["month_id"],
                        data=month,
                    )
                )

        self.db.commit()

        records = (
            self.db.query(theme_tables.Theme)
            .filter(theme_tables.Theme.company_id == company_id)
            .order_by(theme_tables.Theme.month_id)
            .all()
        )

        return [
            serialization.sqlalchemy_to_dict(record)
            for record in records
        ]

    def record_theme_generation_usage(
        self,
        company_id,
        user_id,
    ):
        metric = (
            self.db.query(usage_tables.UsageMetric)
            .filter(
                usage_tables.UsageMetric.user_id == user_id,
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.channel.is_(None),
                usage_tables.UsageMetric.feature == "theme",
                usage_tables.UsageMetric.date == datetime.now(timezone.utc).date(),
            )
            .first()
        )

        current = metric.count if metric else 0

        # Deferred: usage_service imports theme_service, which imports this module, so a
        # module-level import here would close an import cycle.
        from core.services.usage_service import UsageService

        UsageService(self.db).record_usage(
            company_id=company_id,
            user_id=user_id,
            feature="theme",
            action="generate",
            channel=None,
            count=current + 1,
        )

        self.db.commit()

    def get_all_themes(self, company_id):
        themes = (
            self.db.query(theme_tables.Theme)
            .filter(theme_tables.Theme.company_id == company_id)
            .order_by(theme_tables.Theme.month_id)
            .all()
        )

        if not themes:
            raise error.NotFound(
                "No themes found for this company"
            )

        return [
            serialization.sqlalchemy_to_dict(theme)
            for theme in themes
        ]