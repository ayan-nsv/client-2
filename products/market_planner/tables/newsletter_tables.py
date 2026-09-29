from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import backref, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from shared.database.postgres.database_config import Base

class NewsletterPost(Base):
    __tablename__ = "newsletter_posts"
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

    # Many-to-one
    company = relationship(
        "Company",
        backref=backref("newsletter_posts", cascade="all")
    )

    channel = Column(String(50), nullable=True)
    subject_line = Column(String(255), nullable=True)
    preheader = Column(String(255), nullable=True)
    greeting = Column(String(255), nullable=True)
    opening_paragraph = Column(Text, nullable=True)
    main_content = Column(Text, nullable=True)
    practical_tips_section = Column(Text, nullable=True)
    call_to_action = Column(Text, nullable=True)
    closing = Column(Text, nullable=True)

    theme_index = Column(Integer, nullable=True)
    scheduled_datetime = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="draft")
    month_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<NewsletterPost(id={self.id}, company_id='{self.company_id}')>"

