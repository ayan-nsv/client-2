import uuid
from sqlalchemy import (
    Column, 
    String, 
    Integer, 
    DateTime, 
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base

class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        {"schema": "core"}
    )

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

    # Public token (serves as the invite link ID)
    token = Column(
        String(255),
        default=lambda: uuid.uuid4().hex,
        nullable=False,
        unique=True,
        index=True
    )

    email = Column(
        String(255),
        nullable=False,
        index=True
    )

    role_id = Column(
        Integer,
        ForeignKey("core.roles.id", ondelete="CASCADE"),
        nullable=False
    )
    role = relationship("Role")

    status = Column(
        String(20),
        default="pending",
        nullable=False,
        index=True
    )

    # User requested company_id as String (UUID) and company_name as FK
    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company = relationship("Company")

    
    inviter_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    inviter = relationship(
        "User",
        foreign_keys=[inviter_id],
        primaryjoin="Invitation.inviter_id == User.id",
    )

    accepted_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    accepted_by = relationship(
        "User",
        foreign_keys=[accepted_by_id],
    )

    email_status = Column(
        String(50),
        nullable=True
    )


    expires_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    accepted_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    email_sent_at = Column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    def __repr__(self):
        return f"<Invitation(id={self.id}, email='{self.email}', status='{self.status}')>"
