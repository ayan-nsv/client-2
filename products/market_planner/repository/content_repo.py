from sqlalchemy.orm import Session
from datetime import datetime, timezone

from core.tables import usage_tables, company_tables
from core.services.usage_service import UsageService
from products.market_planner.tables import content_tables
from products.market_planner.tables import newsletter_tables, blog_tables
from shared.utils.error import error
from core.repository.company_repo import CompanyRepository



class ContentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_image_generation_count(self, company_id, user_id, channel):
        return (
            self.db.query(usage_tables.UsageMetric)
            .filter(
                usage_tables.UsageMetric.user_id == user_id,
                usage_tables.UsageMetric.company_id == company_id,
                usage_tables.UsageMetric.channel == channel,
                usage_tables.UsageMetric.feature == "image",
                usage_tables.UsageMetric.date == datetime.now(timezone.utc).date(),
            )
            .first()
        )

    def increment_image_generation(self, company_id, user_id, channel):
        metric = self.get_image_generation_count(company_id, user_id, channel)

        current_count = metric.count if metric else 0

        UsageService(self.db).record_usage(
            company_id=company_id,
            user_id=user_id,
            feature="image",
            action="generate",
            channel=channel,
            count=current_count + 1,
        )

        self.db.commit()

    def get_company_with_image_analysis(self, company_uuid):
        company = (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
        )

        if not company:
            raise error.NotFound("Company not found")

        image_analysis = (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company.id)
            .first()
        )

        if not image_analysis:
            raise error.NotFound("No image analysis found")

        return company, image_analysis

    def get_image_analysis_prompt_data(self, image_analysis):
        return {
            "composition_and_style": image_analysis.composition_and_style or "",
            "environment_settings": image_analysis.environment_settings or "",
            "image_types_and_animation": image_analysis.image_types_and_animation or "",
            "keywords_for_ai_image_generation": image_analysis.keywords_for_ai_image_generation or "",
            "lighting_and_color_tone": image_analysis.lighting_and_color_tone or "",
            "subjects_and_people": image_analysis.subjects_and_people or "",
            "technology_elements": image_analysis.technology_elements or "",
            "theme_and_atmosphere": image_analysis.theme_and_atmosphere or "",
        }

    def get_company_with_image_analysis(self, company_uuid):
        company = (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
        )

        if not company:
            raise error.NotFound("Company not found")

        image_analysis = (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company.id)
            .first()
        )

        if not image_analysis:
            raise error.NotFound("No image analysis found")

        return company, image_analysis

    def get_post(self, company_uuid, post_id):
        company_id = CompanyRepository(self.db).get_company_id_from_uuid(company_uuid)

        query = self.db.query(content_tables.Post).filter(
            content_tables.Post.company_id == company_id
        )

        try:
            post = query.filter(
                content_tables.Post.id == int(post_id)
            ).first()
        except ValueError:
            post = query.filter(
                content_tables.Post.uuid == post_id
            ).first()

        if not post:
            raise error.NotFound(f"Post {post_id} not found")

        return post

    def get_posts_by_theme(
        self,
        company_id: int,
        month_id: int,
        theme_index: int,
    ):
        return (
            self.db.query(content_tables.Post)
            .filter(
                content_tables.Post.company_id == company_id,
                content_tables.Post.month_id == month_id,
                content_tables.Post.theme_index == theme_index,
            )
            .all()
        )

    def get_posts_by_channel(
        self,
        company_id: int,
        channel: str,
    ):
        return (
            self.db.query(content_tables.Post)
            .filter(
                content_tables.Post.company_id == company_id,
                content_tables.Post.channel == channel,
            )
            .all()
        )

    def get_posts_by_company_id_and_month_id_and_theme_index(self, company_id: int, month_id: int, theme_index: int):
        return list(
            self.db.query(content_tables.Post)
            .filter(
                content_tables.Post.company_id == company_id,
                content_tables.Post.month_id == month_id,
                content_tables.Post.theme_index == theme_index,
            )
            .all()
        )

    def create_post(self, **post_data):
        post = content_tables.Post(**post_data)
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        return post


    def get_post_by_uuid(
        self,
        post_id: str,
        company_id: int,
        channel_name: str,
    ):
        if channel_name == "newsletter":
            return (
                self.db.query(newsletter_tables.NewsletterPost)
                .filter(
                    newsletter_tables.NewsletterPost.uuid == post_id,
                    newsletter_tables.NewsletterPost.company_id == company_id,
                )
                .first()
            )

        if channel_name == "blog":
            return (
                self.db.query(blog_tables.BlogPost)
                .filter(
                    blog_tables.BlogPost.uuid == post_id,
                    blog_tables.BlogPost.company_id == company_id,
                )
                .first()
            )

        # Instagram, Facebook, LinkedIn
        return (
            self.db.query(content_tables.Post)
            .filter(
                content_tables.Post.uuid == post_id,
                content_tables.Post.company_id == company_id,
            )
            .first()
        )

    def update_scheduled_datetime(
        self,
        post_record,
        scheduled_datetime: datetime,
    ):
        post_record.scheduled_datetime = scheduled_datetime

        self.db.commit()
        self.db.refresh(post_record)

        return post_record       