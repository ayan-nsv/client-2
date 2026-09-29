from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, ARRAY
from sqlalchemy.orm import backref, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from shared.database.postgres.database_config import Base

class BlogPost(Base):
    __tablename__ = "blog_posts"
    __table_args__ = {"schema": "market_planner"}
    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    uuid = Column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
        unique=True,
        index=True
    )

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # One-to-one
    company = relationship(
        "Company",
        backref=backref("blog_posts", cascade="all")
    )

    title = Column(String(255), nullable=False)
    meta_description = Column(String(255), nullable=False)
    introduction = Column(Text, nullable=False)
    sections = Column(ARRAY(JSONB), nullable=False)
    conclusion = Column(Text, nullable=False)
    call_to_action = Column(Text, nullable=False)

    theme_index = Column(Integer, nullable=True)
    scheduled_datetime = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="draft")
    month_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<BlogPost(id={self.id}, company_id='{self.company_id}')>"


