from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.tables import company_tables, usage_tables
from core.services.usage_service import UsageService
from shared.utils.error import error

from products.market_planner.services.theme_service import ThemeService
from products.market_planner.tables import theme_tables
from core.repository.company_repo import CompanyRepository
class PlannerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_company(self, company_uuid):
        company = (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
        )

        if company is None:
            raise error.NotFound(f"Company {company_uuid} not found")

        return company

    def get_image_analysis(self, company_id):
        return (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company_id)
            .first()
        )

    def record_post_usage(self, company_id, user_id, channel):
        metric = (
            self.db.query(usage_tables.UsageMetric)
            .filter(
                usage_tables.UsageMetric.user_id == user_id,
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.channel == channel,
                usage_tables.UsageMetric.feature == "post",
                usage_tables.UsageMetric.date == datetime.now(timezone.utc).date(),
            )
            .first()
        )

        current = metric.count if metric else 0

        UsageService(self.db).record_usage(
            company_id=company_id,
            user_id=user_id,
            feature="post",
            action="generate",
            channel=channel,
            count=current + 1,
        )

        self.db.commit()


    def get_image_analysis_prompt_data(self, company_id):
        image = (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company_id)
            .first()
        )

        if not image:
            return {}

        return {
            "composition_and_style": image.composition_and_style or "",
            "environment_settings": image.environment_settings or "",
            "image_types_and_animation": image.image_types_and_animation or "",
            "keywords_for_ai_image_generation": image.keywords_for_ai_image_generation or "",
            "lighting_and_color_tone": image.lighting_and_color_tone or "",
            "subjects_and_people": image.subjects_and_people or "",
            "technology_elements": image.technology_elements or "",
            "theme_and_atmosphere": image.theme_and_atmosphere or "",
        }


    