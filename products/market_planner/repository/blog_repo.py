from sqlalchemy.orm import Session
from products.market_planner.tables import blog_tables
from core.tables import company_tables
from shared.utils.error import error



class BlogRepository:
    def __init__(self, db:Session):
        self.db = db


    def create_blog_post(
        self,
        company_id: int,
        title: str,
        meta_description: str,
        introduction: str,
        sections: list,
        conclusion: str,
        call_to_action: str,
        theme_index: int = 0,
        scheduled_datetime=None,
        status: str = "draft",
        month_id: int | None = None,
     ):
        try:
            blog = blog_tables.BlogPost(
                company_id=company_id,
                title=title or "",
                meta_description=meta_description or "",
                introduction=introduction or "",
                sections=sections,
                conclusion=conclusion or "",
                call_to_action=call_to_action or "",
                theme_index=theme_index or 0,
                scheduled_datetime=scheduled_datetime,
                status=status or "draft",
                month_id=month_id,
            )

            self.db.add(blog)
            self.db.commit()
            self.db.refresh(blog)

            return blog

        except Exception:
            self.db.rollback()
            raise



    def get_blogs_by_company_id(self, company_id: int):
        return (
            self.db.query(blog_tables.BlogPost)
            .filter(blog_tables.BlogPost.company_id == company_id)
            .all()
        )

    def get_blog_by_id(
        self,
        company_id: int,
        blog_id: str,
     ):
        return (
            self.db.query(blog_tables.BlogPost)
            .filter(
                blog_tables.BlogPost.company_id == company_id,
                blog_tables.BlogPost.uuid == blog_id,
            )
            .first()
        )


    def update_blog(
        self,
        company_id: int,
        blog_id: str,
        title=None,
        meta_description=None,
        introduction=None,
        sections=None,
        conclusion=None,
        call_to_action=None,
        theme_index=None,
        scheduled_datetime=None,
        status=None,
        month_id=None,
     ):
        try:
            blog = (
                self.db.query(blog_tables.BlogPost)
                .filter(
                    blog_tables.BlogPost.company_id == company_id,
                    blog_tables.BlogPost.uuid == blog_id,
                )
                .first()
            )

            if not blog:
                return None

            if title is not None:
                blog.title = title

            if meta_description is not None:
                blog.meta_description = meta_description

            if introduction is not None:
                blog.introduction = introduction

            if sections is not None:
                blog.sections = sections

            if conclusion is not None:
                blog.conclusion = conclusion

            if call_to_action is not None:
                blog.call_to_action = call_to_action

            if theme_index is not None:
                blog.theme_index = theme_index

            if scheduled_datetime is not None:
                blog.scheduled_datetime = scheduled_datetime

            if status is not None:
                blog.status = status

            if month_id is not None:
                blog.month_id = month_id

            self.db.commit()
            self.db.refresh(blog)

            return blog

        except Exception:
            self.db.rollback()
            raise


    def delete_blog(
        self,
        company_id: int,
        blog_id: str,
    ) -> bool:
        try:
            blog = (
                self.db.query(blog_tables.BlogPost)
                .filter(
                    blog_tables.BlogPost.company_id == company_id,
                    blog_tables.BlogPost.uuid == blog_id,
                )
                .first()
            )

            if not blog:
                return False

            self.db.delete(blog)
            self.db.commit()

            return True

        except Exception:
            self.db.rollback()
            raise



















