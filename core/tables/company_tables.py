from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    Text, 
    DateTime, 
    Time,
    ARRAY, 
    JSON,
    text,
    Boolean,
    ForeignKey,
    UniqueConstraint
)
from sqlalchemy.sql import func
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import relationship
from sqlalchemy.types import Time

class Company(Base):
    __tablename__ = "companies"
    __table_args__ = {"schema": "core"}
    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    uuid = Column(
        String,
        nullable=False,
        unique=True,
        index=True
    )


    # One-to-one
    image_analysis = relationship(
        "ImageAnalysis",
        back_populates="company",
        uselist=False,
        cascade="all"
    )


    # One-to-many
    usage_metrics = relationship(
        "UsageMetric",
        back_populates="company",
        cascade="all"
    )


    # Basic company information
    company_name = Column(
        String(255),
        nullable=False,
        index=True,
        server_default=text("''")
    )


    url = Column(String(500), nullable=True)
    address = Column(Text, nullable=True)
    company_info = Column(Text, nullable=True)
    industry = Column(String(100), nullable=True)
    target_group = Column(Text, nullable=True)
    tone_analysis = Column(Text, nullable=True)

    # Branding
    logo_url = Column(String(500), nullable=True)
    favicon_url = Column(String(500), nullable=True)
    theme_colors = Column(ARRAY(String), nullable=True)

    # Products and categories
    products = Column(ARRAY(String), nullable=True)
    keywords = Column(ARRAY(String), nullable=True)
    fonts_typography = Column(ARRAY(String), nullable=True)

    # Complex nested data stored as JSON
    matched_fonts = Column(JSON, nullable=True)
    product_categories = Column(JSON, nullable=True)

    # Billing (Salesforce / batman)
    tier = Column(String(10), nullable=True, server_default=text("'FREE'"))
    agent_category = Column(String(100), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


    def __repr__(self):
        return f"<Company(id={self.id}, company_name='{self.company_name}')>"


class CompanyUser(Base):
    __tablename__ = "company_users"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_user_company"),
        {"schema": "core"},
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

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False
    )
    company = relationship("Company")

    user_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="CASCADE"),
        nullable=False
    )
    user = relationship("User")

    role_id = Column(
        Integer,
        ForeignKey("core.roles.id", ondelete="CASCADE"),
        nullable=False
    )

    # Many-to-one relationship with Role
    role = relationship(
        "Role",
        back_populates="company_users"
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<CompanyUser(user_id={self.user_id}, company_id={self.company_id}, role_id={self.role_id})>"


class ImageAnalysis(Base):
    __tablename__ = "image_analysis"
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

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # One-to-one
    company = relationship(
        "Company",
        back_populates="image_analysis",
        uselist=False
    )

    composition_and_style = Column(Text, nullable=True)
    environment_settings = Column(Text, nullable=True)
    image_types_and_animation = Column(Text, nullable=True)
    keywords_for_ai_image_generation = Column(Text, nullable=True)
    lighting_and_color_tone = Column(Text, nullable=True)
    subjects_and_people = Column(Text, nullable=True)
    technology_elements = Column(Text, nullable=True)
    theme_and_atmosphere = Column(Text, nullable=True)

    analyzed_images_urls = Column(ARRAY(String), nullable=True)

    image_urls = Column(ARRAY(String), nullable=True)

    # Timestamps    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


    def __repr__(self):
        return f"<ImageAnalysis(id={self.id}, analyzed_images_urls='{self.analyzed_images_urls}')>"


# Company configuration
class CompanyConfig(Base):
    __tablename__ = "company_configs"
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
    
    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company = relationship("Company")
    
    # Supported languages
    supported_languages = Column(
        ARRAY(String),
        nullable=False,
        default=list
    )

    # Primary language
    default_language = Column(
        String,
        nullable=False
    )

    # Location mode (on_site / digital / both)
    location_mode = Column(
        String,
        nullable=False
    )

    # Required if location_mode is on_site or both
    company_address = Column(
        String,
        nullable=True
    )

    # Business hours per weekday
    # Example:
    # {
    #   "monday": {"enabled": True, "from": "09:00", "to": "17:00"},
    #   "tuesday": {"enabled": False}
    # }
    business_hours = Column(
        JSONB,
        nullable=True
    )

    # Exception hours
    # [
    #   {"date": "2026-03-01", "closed_all_day": True, "label": "Holiday"},
    #   {"date": "2026-03-02", "from": "13:00", "to": "15:00", "label": "Maintenance"}
    # ]
    exception_hours = Column(
        JSONB,
        nullable=True
    )

    # Notification recipients (generic / callback notifications)
    notification_email_recipients = Column(
        ARRAY(String),
        nullable=True
    )

    # Global booking switch
    bookings_enabled = Column(
        Boolean,
        nullable=False,
        default=True
    )

    # Caller data collection rules
    # Example:
    # {
    #   "collect_name": "required",
    #   "collect_phone_number": "required",
    #   "collect_reason_for_call": "optional",
    #   "collect_preferred_callback_time": True
    # }
    caller_data_collection = Column(
        JSONB,
        nullable=True
    )

    # Callback settings
    # {
    #   "callback_message": {
    #       "sv-SE": "Vi ringer dig snart.",
    #       "en-US": "We will call you back shortly."
    #   },
    #   "callback_email_recipients": ["support@company.com"]
    # }
    callback_settings = Column(
        JSONB,
        nullable=True
    )
    
    # New Fields
    phone_no = Column(String(20), nullable=True)
    phone_summary = Column(Boolean, nullable=True)
    email_summary = Column(Boolean, nullable=True)
    daily_summary = Column(Boolean, nullable=True, default=False)
    customer_sms_enabled = Column(Boolean, nullable=True, default=False)
    sms_email = Column(String(255), nullable=True)
    
    scheduled_email_time = Column(Time(timezone=True), nullable=True)
    scheduled_timezone = Column(String(128), nullable=True)

    # Free-minute usage warning email (once per calendar month, Europe/Stockholm)
    usage_warning_sent_month = Column(String(7), nullable=True)
    usage_warning_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)





class Feature(Base):
    __tablename__ = "features"
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
        index=True,
    )

    name = Column(
        String,
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<Feature(id={self.id}, name='{self.name}')>"

class CompanyFeature(Base):
    __tablename__ = "company_features"
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
        index=True,
    )

    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company = relationship("Company")

    # Many-to-one relationship with Feature
    feature_id = Column(
        Integer,
        ForeignKey("core.features.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature = relationship("Feature")

    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<CompanyFeature(id={self.id}, company_id={self.company_id}, feature_id={self.feature_id}, enabled={self.enabled})>"