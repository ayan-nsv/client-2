import enum
from uuid import UUID
from pydantic import BaseModel, Field
from typing import List, Optional
from fastapi import Form
from datetime import datetime


class UploadUsedFor(str, enum.Enum):
    chat = "chat"
    voice_call = "voice_call"
    chat_and_voice_call = "chat_and_voice_call"
    market_planner = "market_planner"

# Upload documents:

class UploadedFileResponse(BaseModel):
    file_path: str

class UploadFilesData(BaseModel):
    uploaded_files: List[UploadedFileResponse]

class UploadFilesResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[UploadFilesData] = None

class UploadUrlsPayload(BaseModel):
    company_id: str
    urls: List[str] = Field(..., min_length=1)
    user_id: Optional[str] = None
    used_for: Optional[UploadUsedFor] = None


class UploadedUrlResponse(BaseModel):
    """One URL outcome from upload-urls (created / updated / skipped / failed)."""
    url: str
    status: str
    uuid: Optional[UUID] = None
    user_id: Optional[str] = None
    error: Optional[str] = None


class UploadUrlsData(BaseModel):
    uploaded_urls: List[UploadedUrlResponse]


class UploadUrlsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[UploadUrlsData] = None


class UploadPdfPayload(BaseModel):
    company_id: str
    user_id: Optional[str] = None
    used_for: Optional[UploadUsedFor] = None

    @classmethod
    def as_form(
        cls,
        company_id: str = Form(...),
        user_id: Optional[str] = Form(None),
        used_for: Optional[str] = Form(None),
    ) -> "UploadPdfPayload":
        normalized_used_for: Optional[UploadUsedFor] = None
        if used_for is not None and str(used_for).strip():
            normalized_used_for = UploadUsedFor(str(used_for).strip())
        return cls(user_id=user_id, company_id=company_id, used_for=normalized_used_for)


class UploadImagePayload(BaseModel):
    """Form payload for image uploads; matches UploadPdfPayload shape."""
    user_id: Optional[str] = None
    company_id: str

    @classmethod
    def as_form(
        cls,
        company_id: str = Form(...),
        user_id: Optional[str] = Form(None)
    ) -> "UploadImagePayload":
        return cls(user_id=user_id, company_id=company_id)

class ChatQuery(BaseModel):
    query: str = Field(..., min_length=1)

class ChatData(BaseModel):
    answer: Optional[str]

class WrappedChatResponse(BaseModel):
    success: bool
    message: str
    data: ChatData

# Retrieve Documents from DB:

class DocumentItem(BaseModel):
    uuid: UUID
    filename: Optional[str]
    file_path: str
    is_selected: Optional[bool] = None
    used_for: Optional[str] = None
    uploaded_at: datetime

class PaginationMeta(BaseModel):
    number_of_pages: int    
    current_page: int
    next: Optional[str] = None
    previous: Optional[str] = None

class DocumentsData(BaseModel):
    documents: List[DocumentItem]
    pagination: PaginationMeta

class DocumentsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[DocumentsData] = None

class UrlItem(BaseModel):
    uuid: UUID
    url: str
    filename: Optional[str] = None
    is_selected: Optional[bool] = None
    used_for: Optional[str] = None
    user_id: Optional[str] = None
    uploaded_at: datetime


class UrlsData(BaseModel):
    urls: List[UrlItem]
    pagination: PaginationMeta


class UrlsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[UrlsData] = None


class UploadMethodSelectionPayload(BaseModel):
    is_selected: bool


class UploadMethodSelectionData(BaseModel):
    id: int
    uuid: UUID
    is_selected: bool


class UploadMethodSelectionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[UploadMethodSelectionData] = None
    error: Optional[str] = None


# FAQ (Frequently Asked Questions)

class FAQItem(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)


class FAQUploadPayload(BaseModel):
    company_id: str
    category: Optional[str] = "faq"
    faqs: List[FAQItem] = Field(..., min_length=1)

class FAQUpdatePayload(BaseModel):
    company_id: str
    user_id: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None

class FAQDeletePayload(BaseModel):
    company_id: str
    user_id: Optional[str] = None

class FAQDetailData(BaseModel):
    uuid: UUID
    question: str
    answer: str
    category: str
    language: str

class FAQDetailResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[FAQDetailData] = None
    error: Optional[str] = None

class FAQListData(BaseModel):
    faqs: List[FAQDetailData]
    pagination: PaginationMeta

class FAQListResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[FAQListData] = None
    error: Optional[str] = None


class FAQUploadData(BaseModel):
    saved_count: int


class FAQUploadResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[FAQUploadData] = None
