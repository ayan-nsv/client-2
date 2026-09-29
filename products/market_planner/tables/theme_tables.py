import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import backref, relationship
from sqlalchemy import Date


class Theme(Base):
    __tablename__ = "themes"
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
        backref=backref("themes", cascade="all")
    )

    month_id = Column(Integer, nullable=True)
    
    
    data = Column(JSONB, nullable=True)

    month = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
