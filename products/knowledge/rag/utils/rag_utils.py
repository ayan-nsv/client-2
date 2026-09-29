import hashlib
import os
import io
import re
import json
from typing import Dict, List, Literal, Tuple

from fastapi import HTTPException, status
from PIL import Image
import pytesseract
from openai import OpenAI
from sqlalchemy.orm import Session, sessionmaker
from products.knowledge.rag.tables.rag_tables import UploadMethod
# from utils.logger import setup_logger

# logger = setup_logger("marketing-app")

# OpenAI configuration for translation and language detection
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TRANSLATION_MODEL = os.getenv("OPENAI_TRANSLATION_MODEL") or "gpt-4o-mini"


def get_openai_api_base() -> str | None:
    """Proxy/base URL for OpenAI (same env vars as gpt_service, embedding_service, etc.)."""
    return os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL") or None


def openai_langchain_kwargs() -> dict:
    """Extra kwargs for LangChain OpenAI wrappers to route through the configured proxy."""
    base = get_openai_api_base()
    return {"openai_api_base": base} if base else {}

OPENAI_CLIENT = None
if OPENAI_API_KEY:
    try:
        base_url = get_openai_api_base()
        if base_url:
            OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY, base_url=base_url)
        else:
            OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        # logger.error(f"Failed to initialize OpenAI client for translation: {e}")
        pass

# Allowed image extensions and their content types
IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

def file_content_hash(file_bytes: bytes) -> str:
    """Generate SHA256 hash of file content."""
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    return hasher.hexdigest()


def _image_content_type(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    return IMAGE_CONTENT_TYPES.get(ext, "image/jpeg")


def _extract_text_from_image(image_bytes: bytes) -> list[str]:
    """Extract text from image via OCR and return list of chunk strings (by paragraph)."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    raw_text = pytesseract.image_to_string(img)
    if not raw_text or not raw_text.strip():
        return []
    # Split by paragraph (double newline) or single newline to get initial chunks
    chunks = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
    if not chunks:
        chunks = [raw_text.strip()]
    return chunks

# TEXT NORMALIZATION
def normalize_text(text: str) -> str:
    """
    Clean text before embedding:
    - Remove null bytes
    - Collapse multiple whitespace into single space
    - Strip leading/trailing spaces
    """
    text = text.replace("\x00", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# MERGE SMALL CHUNKS INTO NEXT LARGE CHUNK
def merge_small_chunks(chunks: list[str], min_words: int = 5) -> list[str]:
    """
    Merge small chunks into the next larger chunk.
    Prevents one-word or tiny chunks from being saved alone.
    """
    merged = []
    buffer = ""

    for chunk in chunks:
        words = chunk.split()

        if len(words) < min_words:
            # Store small chunk in buffer
            buffer = f"{buffer} {chunk}".strip() if buffer else chunk
        else:
            # Attach buffer before large chunk
            if buffer:
                chunk = f"{buffer} {chunk}"
                buffer = ""
            merged.append(chunk)

    # If leftover buffer exists, attach to last chunk
    if buffer:
        if merged:
            merged[-1] = f"{merged[-1]} {buffer}"
        else:
            merged.append(buffer)

    return merged


def _rag_chunk_params() -> Tuple[int, int, int]:
    """
    Chunk sizing for embedding + pgvector retrieval.

    - Smaller, bounded chunks → faster similarity scans and more precise top-k.
    - Overlap preserves context across page/sentence boundaries.

    Override with env: RAG_CHUNK_CHARS, RAG_CHUNK_OVERLAP, RAG_MIN_CHUNK_CHARS.
    """
    size = max(200, int(os.getenv("RAG_CHUNK_CHARS", "1200")))
    overlap = max(0, int(os.getenv("RAG_CHUNK_OVERLAP", "150")))
    if overlap >= size:
        overlap = max(0, size // 5)
    min_chars = max(1, int(os.getenv("RAG_MIN_CHUNK_CHARS", "80")))
    return size, overlap, min_chars


def split_text_for_rag(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> List[str]:
    """
    Split long text into overlapping chunks, preferring paragraph / line / sentence breaks
    inside the tail of each window (cheap alternative to full recursive splitting).
    """
    chunk_size = chunk_size if chunk_size is not None else _rag_chunk_params()[0]
    chunk_overlap = chunk_overlap if chunk_overlap is not None else _rag_chunk_params()[1]

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    n = len(text)
    min_advance = max(1, chunk_size - chunk_overlap)

    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = text[start:end]
            search_from = max(0, int(len(window) * 0.35))
            cut = window.rfind("\n\n", search_from)
            boundary_len = 0
            if cut != -1:
                boundary_len = 2
            else:
                cut = window.rfind("\n", search_from)
                if cut != -1:
                    boundary_len = 1
                else:
                    cut = window.rfind(". ", search_from)
                    if cut != -1:
                        boundary_len = 2
            if cut > 0 and boundary_len:
                end = start + cut + boundary_len

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= n:
            break
        next_start = end - chunk_overlap
        if next_start <= start:
            next_start = start + min_advance
        start = next_start

    return chunks


def finalize_rag_chunks(chunks: List[str], min_chars: int | None = None) -> List[str]:
    """Glue fragments shorter than min_chars onto the previous chunk (or keep if alone)."""
    _, _, default_min = _rag_chunk_params()
    min_chars = min_chars if min_chars is not None else default_min
    if not chunks:
        return []
    out: List[str] = []
    for c in chunks:
        c = (c or "").strip()
        if not c:
            continue
        if len(c) < min_chars and out:
            out[-1] = f"{out[-1]}\n\n{c}".strip()
        else:
            out.append(c)
    return out


def chunk_segments_for_rag(segments: List[str]) -> List[str]:
    """
    Turn page-level (or OCR paragraph) segments into bounded chunks for embedding.

    Call after normalize_text + merge_small_chunks so tiny pages are already merged.
    """
    size, overlap, _ = _rag_chunk_params()
    flat: List[str] = []
    for seg in segments:
        seg = (seg or "").strip()
        if not seg:
            continue
        flat.extend(split_text_for_rag(seg, chunk_size=size, chunk_overlap=overlap))
    return finalize_rag_chunks(flat)


def embed_documents_batched(embedder, texts: List[str]) -> List[List[float]]:
    """Embed in batches to avoid huge single API payloads on large PDFs."""
    if not texts:
        return []
    batch_size = max(1, int(os.getenv("RAG_EMBED_BATCH_SIZE", "100")))
    vectors: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        vectors.extend(embedder.embed_documents(texts[i : i + batch_size]))
    return vectors


def _detect_language_and_translate(question: str, answer: str) -> Dict[str, str]:
    """
    Detect whether the input is English or Swedish and return translations.

    Returns a dict with:
    - source_language: 'en', 'sv', or 'unknown'
    - target_language: 'sv' or 'en' (if source is supported)
    - translated_question
    - translated_answer
    """
    if not OPENAI_CLIENT:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OpenAI client not configured for translation.",
        )

    system_prompt = (
        "You are a strict language detector and translator for ONLY English and Swedish.\n"
        "Given a FAQ question and answer, you must:\n"
        "1) Detect if the text is primarily in English or Swedish.\n"
        "2) If English, set source_language='en' and target_language='sv' and translate both question and answer to Swedish.\n"
        "3) If Swedish, set source_language='sv' and target_language='en' and translate both question and answer to English.\n"
        "4) If it's any other language or heavily mixed, set source_language='unknown' and target_language='' and DO NOT translate.\n"
        "Always respond with a single JSON object with exactly these keys:\n"
        "source_language, target_language, translated_question, translated_answer.\n"
        "For unsupported languages, translated_question and translated_answer MUST be empty strings."
    )

    user_payload = {
        "question": question,
        "answer": answer,
    }

    response = OPENAI_CLIENT.chat.completions.create(
        model=OPENAI_TRANSLATION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=512,
        n=1,
    )

    content = response.choices[0].message.content or ""

    # Extract JSON object from the model response
    match = re.search(r"(\{[\s\S]*\})", content)
    json_text = match.group(1) if match else content

    try:
        data = json.loads(json_text)
    except Exception as e:
        # logger.error(f"Failed to parse translation JSON: {e} | Raw: {content[:500]}")
        pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse translation response from OpenAI.",
        )

    # Basic normalization and safety
    source_language = (data.get("source_language") or "").lower()
    target_language = (data.get("target_language") or "").lower()
    translated_question = (data.get("translated_question") or "").strip()
    translated_answer = (data.get("translated_answer") or "").strip()

    return {
        "source_language": source_language,
        "target_language": target_language,
        "translated_question": translated_question,
        "translated_answer": translated_answer,
    }

def upload_method_used_for_values(used_for: str) -> List[str]:
    """Map a channel filter to stored ``used_for`` values on upload_methods."""
    if used_for == "chat":
        return ["chat", "chat_and_voice_call"]
    if used_for == "voice_call":
        return ["voice_call", "chat_and_voice_call"]
    if used_for == "chat_and_voice_call":
        return ["chat_and_voice_call"]
    if used_for == "market_planner":
        return ["market_planner"]
    return [used_for]

def _selected_upload_method_ids(
    session: Session,
    company_id: int,
    used_for: Literal["chat", "voice_call"],
) -> List[int]:
    """Upload methods explicitly selected for RAG (excludes false and null).

    Filters by ``used_for`` channel ("chat" or "voice_call") and only
    returns methods where ``is_selected`` is True. Documents tagged
    ``chat_and_voice_call`` are included for both chat and voice retrieval.
    """
    rows = (
        session.query(UploadMethod.id)
        .filter(
            UploadMethod.company_id == company_id,
            UploadMethod.used_for.in_(upload_method_used_for_values(used_for)),
            UploadMethod.is_selected.is_(True),
        )
        .all()
    )
    return [row[0] for row in rows]

# For Voice call:
def chat_retrieval_is_lexical() -> bool:
    """
    When True, /chat/{company_id}/query uses PostgreSQL pg_trgm text similarity
    instead of embedding + pgvector (semantic) retrieval.

    Set CHAT_QUERY_RETRIEVAL_MODE=lexical (or similarity / trigram).
    Requires migration b3c4d5e6f7a8 (pg_trgm + indexes).
    """
    v = os.getenv("CHAT_QUERY_RETRIEVAL_MODE", "semantic").strip().lower()
    return v in ("lexical", "similarity", "trigram")

# For Text chat:
def chatbot_retrieval_is_lexical() -> bool:
    """
    When True, the chatbot text-chat endpoint
    (/chatbots/conversations/{conversation_id}/chat) uses PostgreSQL pg_trgm
    text similarity instead of embedding + pgvector (semantic) retrieval.

    Set CHATBOT_RETRIEVAL_MODE=lexical (or similarity / trigram).
    Requires migration b3c4d5e6f7a8 (pg_trgm + indexes).
    """
    v = os.getenv("CHATBOT_RETRIEVAL_MODE", "semantic").strip().lower()
    return v in ("lexical", "similarity", "trigram")