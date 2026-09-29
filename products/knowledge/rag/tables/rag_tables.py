import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ARRAY,
    ForeignKey,
    Boolean,
    text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from shared.database.postgres.database_config import Base
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from sqlalchemy import UniqueConstraint



class UploadMethod(Base):
    __tablename__ = "upload_methods"
    __table_args__ = {"schema": "knowledge"}
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

    
    uploaded_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        index=True
    )

    uploaded_by = relationship(
        "User"
    )
    # options: chat, voice_call
    used_for = Column(
        String(255),
        nullable=True
    )
    
    company_id = Column(
        Integer,
        ForeignKey("core.companies.id", ondelete="SET NULL"),
        index=True
    )
    company = relationship("Company")
    
    extracted_data = relationship(
        "ExtractedData",
        back_populates="upload_method",
        cascade="all, delete-orphan"
    )


    #attachment, url
    method_type = Column(String(50), nullable=False)
    
    filename = Column(String(255), index=True)
    file_path = Column(String(1024), nullable=False)
    
    url = Column(String(1024), nullable=True)

    # is selected
    is_selected = Column(Boolean, nullable=True, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    def __str__(self):
        return f"UploadMethod(id={self.id}, method_type='{self.method_type}', filename='{self.filename}')"



class ExtractedData(Base):
    __tablename__ = "extracted_data"
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
        ForeignKey("core.companies.id", ondelete="SET NULL"),
        index=True
    )
    company = relationship("Company")

    
    upload_method_id = Column(
        Integer,
        ForeignKey("knowledge.upload_methods.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    upload_method = relationship(
        "UploadMethod",
        back_populates="extracted_data"
    )

    chunk_index = Column(Integer, nullable=False)
    chunk_content = Column(String)
    content_hash = Column(String, nullable=False)

    embedding = Column(Vector(1536), nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint("upload_method_id", "chunk_index", name="uix_method_chunk"),
        {"schema": "knowledge"},
    )
    
    def __str__(self):
        return f"ExtractedData(id={self.id}, upload_method_id={self.upload_method_id}, chunk_index={self.chunk_index})"


class CompanyFAQ(Base):
    """FAQ entries per company: question + answer with embedding for similarity search."""

    __tablename__ = "company_faqs"
    __table_args__ = {"schema": "knowledge"}
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
    company = relationship("Company")

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    
    # Language to track which language the FAQ is in, useful for multilingual support and filtering
    language = Column(String(10), nullable=False)
    category = Column(String(50), nullable=True, default="faq")
    
    # Used to link the original and translated version of the same FAQ
    question_id = Column(String(50), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __str__(self):
        return f"CompanyFAQ(id={self.id}, company_id={self.company_id})"



class KnowledgeBaseSummary(Base):
    """Persisted LLM summary of a company's RAG knowledge base."""

    __tablename__ = "knowledge_base_summaries"

    __table_args__ = {"schema": "knowledge"}
    id = Column(Integer, primary_key=True, index=True)
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

    summary_text = Column(Text, nullable=False)
    covered_topics = Column(ARRAY(String), nullable=True)
    source_chunk_count = Column(Integer, nullable=False, default=0)
    used_for = Column(String(15), nullable=True)

    created_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    gaps = relationship(
        "KnowledgeBaseGap",
        back_populates="summary",
        cascade="all, delete-orphan",
    )
    surveys = relationship(
        "KnowledgeBaseSurvey",
        back_populates="summary",
        cascade="all, delete-orphan",
    )

    def __str__(self):
        return f"KnowledgeBaseSummary(id={self.id}, company_id={self.company_id})"


class KnowledgeBaseGap(Base):
    """Missing information detected from a knowledge base summary."""

    __tablename__ = "knowledge_base_gaps"

    __table_args__ = {"schema": "knowledge"}
    id = Column(Integer, primary_key=True, index=True)
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

    summary_id = Column(
        Integer,
        ForeignKey("knowledge.knowledge_base_summaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary = relationship("KnowledgeBaseSummary", back_populates="gaps")

    topic = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(20), nullable=False, default="medium")
    status = Column(String(20), nullable=False, default="open")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __str__(self):
        return f"KnowledgeBaseGap(id={self.id}, topic='{self.topic}')"


class KnowledgeBaseSurvey(Base):
    """Survey generated from knowledge base gaps to collect missing info."""

    __tablename__ = "knowledge_base_surveys"

    __table_args__ = {"schema": "knowledge"}
    id = Column(Integer, primary_key=True, index=True)
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

    summary_id = Column(
        Integer,
        ForeignKey("knowledge.knowledge_base_summaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary = relationship("KnowledgeBaseSummary", back_populates="surveys")

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    survey_category = Column(String(64), nullable=False, index=True)
    language = Column(String(10), nullable=False, server_default="en", default="en")
    generated_from = Column(
        JSONB,
        nullable=False,
        server_default=text(
            '\'{"website": false, "documents": false, "knowledge_base": true}\'::jsonb'
        ),
        default=lambda: {
            "website": False,
            "documents": False,
            "knowledge_base": True,
        },
    )
    version = Column(Integer, nullable=False, server_default="1", default=1)
    previous_version_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # Spec: {question_id, type, question, options?, knowledge_base_category, allowed_channels}
    questions = Column(JSONB, nullable=False, default=list, server_default="[]")
    status = Column(String(20), nullable=False, server_default="available", default="available")

    created_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    responses = relationship(
        "KnowledgeBaseSurveyResponse",
        back_populates="survey",
        cascade="all, delete-orphan",
    )

    def __str__(self):
        return f"KnowledgeBaseSurvey(id={self.id}, title='{self.title}')"


class KnowledgeBaseSurveyResponse(Base):
    """Saved draft or submitted answers for a knowledge base survey."""

    __tablename__ = "knowledge_base_survey_responses"

    __table_args__ = {"schema": "knowledge"}
    id = Column(Integer, primary_key=True, index=True)
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

    survey_id = Column(
        Integer,
        ForeignKey("knowledge.knowledge_base_surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    survey = relationship("KnowledgeBaseSurvey", back_populates="responses")

    status = Column(String(20), nullable=False, server_default="draft", default="draft")
    submission_channel = Column(String(32), nullable=False, server_default="web_form", default="web_form")
    # [{question_id, answer}] — answer may be string, bool, number, or list of strings
    answers = Column(JSONB, nullable=False, default=list, server_default="[]")
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    created_by_id = Column(
        Integer,
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __str__(self):
        return f"KnowledgeBaseSurveyResponse(id={self.id}, status='{self.status}')"