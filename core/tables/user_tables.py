import uuid
from sqlalchemy import (
    Column, 
    String, 
    Boolean, 
    Integer, 
    DateTime, 
    ForeignKey,
    Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import relationship


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "core"}
    
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

    # One-to-many relationship with CompanyUser
    company_users = relationship(
        "CompanyUser",
        back_populates="role",
        cascade="all"
    )

    name = Column(String(255), nullable=False, unique=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self): 
        return f"<Role(id={self.id}, name='{self.name}')>"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "core"}
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

    firebase_uid = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True
    )

    email = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True
    )

    name = Column(
        String(255),
        nullable=True
    )

    # User.telegram_chats and User.chat_bots are contributed by market_planner and
    # knowledge respectively, via backref on their own models. Core does not name
    # product classes.

    # One-to-many
    usage_metrics = relationship(
        "UsageMetric",
        back_populates="user",
        cascade="all"
    )

    is_admin = Column(
        Boolean,
        nullable=False,
        default=False
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True
    )
    is_fully_approved = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    has_created_company = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    profile_image = Column(
        Text,
        nullable=True
    )

    joined_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    last_login = Column(
        DateTime(timezone=True),
        nullable=True
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self): 
        return f"<User(id={self.id}, email='{self.email}')>"