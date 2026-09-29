from sqlalchemy.orm import Session

from products.market_planner.tables import newsletter_tables
from products.market_planner.schema import newsletter_schema


class NewsletterRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_newsletter(
        self,
        company_id: int,
        data,
     ):
        newsletter = newsletter_tables.NewsletterPost(
            company_id=company_id,
            **data.model_dump(),
        )

        self.db.add(newsletter)
        self.db.commit()
        self.db.refresh(newsletter)

        return newsletter

    def get_newsletters_by_company_id(self, company_id: int) -> list[dict]:
        newsletter_records = (
            self.db.query(newsletter_tables.NewsletterPost)
            .filter(newsletter_tables.NewsletterPost.company_id == company_id)
            .all()
        )
        return newsletter_records
        


    def get_newsletter_by_id(
        self,
        company_id: int,
        newsletter_id: str,
    ):
        return (
            self.db.query(newsletter_tables.NewsletterPost)
            .filter(
                newsletter_tables.NewsletterPost.company_id == company_id,
                newsletter_tables.NewsletterPost.uuid == newsletter_id,
            )
            .first()
        )


    def update_newsletter(
        self,
        newsletter_id: str,
        payload,
    ):
        newsletter = (
            self.db.query(newsletter_tables.NewsletterPost)
            .filter(newsletter_tables.NewsletterPost.uuid == newsletter_id)
            .first()
        )

        if not newsletter:
            return None

        newsletter.channel = payload.channel or newsletter.channel
        newsletter.subject_line = (
            payload.subject_line or newsletter.subject_line
        )
        newsletter.preheader = (
            payload.preheader or newsletter.preheader
        )
        newsletter.greeting = (
            payload.greeting or newsletter.greeting
        )
        newsletter.opening_paragraph = (
            payload.opening_paragraph or newsletter.opening_paragraph
        )
        newsletter.main_content = (
            payload.main_content or newsletter.main_content
        )
        newsletter.practical_tips_section = (
            payload.practical_tips_section
            or newsletter.practical_tips_section
        )
        newsletter.call_to_action = (
            payload.call_to_action or newsletter.call_to_action
        )
        newsletter.closing = (
            payload.closing or newsletter.closing
        )
        newsletter.scheduled_datetime = (
            payload.scheduled_datetime
            or newsletter.scheduled_datetime
        )
        newsletter.status = (
            payload.status or newsletter.status
        )
        newsletter.month_id = (
            payload.month_id or newsletter.month_id
        )

        try:
            self.db.commit()
            self.db.refresh(newsletter)
            return newsletter
        except Exception:
            self.db.rollback()
            raise

    
    def delete_newsletter(
        self,
        company_id: int,
        newsletter_id: str,
    ) -> bool:
        newsletter = (
            self.db.query(newsletter_tables.NewsletterPost)
            .filter(
                newsletter_tables.NewsletterPost.company_id == company_id,
                newsletter_tables.NewsletterPost.uuid == newsletter_id,
            )
            .first()
        )

        if not newsletter:
            return False

        self.db.delete(newsletter)
        self.db.commit()

        return True