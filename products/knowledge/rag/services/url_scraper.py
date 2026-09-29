"""
Thin RAG wrapper around the project's existing Holdflight website scraper.
"""
import asyncio
import ipaddress
import os
import re
from typing import List
from urllib.parse import urlparse

from fastapi import HTTPException, status

from holdflight.src.scraping.scan import scrape_website_data
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

MAX_TEXT_CHARS = max(10_000, int(os.getenv("RAG_URL_MAX_TEXT_CHARS", "500000")))


def normalize_scrape_url(url: str) -> str:
    """Normalize a user-provided URL for scraping."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is required")

    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs are allowed")

    host = (parsed.hostname or "").strip()
    if not host:
        raise ValueError("URL hostname is required")

    if parsed.username or parsed.password:
        raise ValueError("URL must not contain credentials")

    return raw


def _validate_scrape_host(host: str) -> None:
    host_l = host.lower()
    if host_l in {"localhost", "127.0.0.1", "::1"} or host_l.endswith(".local"):
        raise ValueError("Local/internal hosts are not allowed")

    try:
        ip_obj = ipaddress.ip_address(host_l)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
        ):
            raise ValueError("Private/internal IPs are not allowed")
    except ValueError as exc:
        if "does not appear to be an IPv4 or IPv6 address" not in str(exc):
            raise


def validate_scrape_url(url: str) -> str:
    """Validate and normalize a URL before scraping."""
    normalized = normalize_scrape_url(url)
    parsed = urlparse(normalized)
    _validate_scrape_host(parsed.hostname or "")
    return normalized


def _display_filename(url: str, title: str) -> str:
    if title:
        safe = re.sub(r"[^\w\s\-.]", "", title).strip()
        if safe:
            return safe[:255]
    parsed = urlparse(url)
    path = (parsed.path or "/").strip("/") or parsed.netloc
    return path[:255]


def _text_to_segments(text: str) -> List[str]:
    cleaned = re.sub(r"[ \t]+", " ", (text or "").strip())
    if not cleaned:
        return []

    if len(cleaned) > MAX_TEXT_CHARS:
        cleaned = cleaned[:MAX_TEXT_CHARS]

    segments = [s.strip() for s in re.split(r"\n\s*\n", cleaned) if s.strip()]
    if segments:
        return segments

    # Fallback: split long single-line scrape text into sentence-ish chunks
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    return pieces or [cleaned]


def _scrape_url_for_rag_sync(url: str) -> dict:
    """
    Use holdflight ``scrape_website_data`` (requests + selenium fallbacks)
    and shape the result for the RAG chunking pipeline.
    """
    normalized = validate_scrape_url(url)

    scraped = scrape_website_data(normalized)
    if not scraped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to scrape URL: {normalized}",
        )
    if isinstance(scraped, list):
        scraped = scraped[0] if scraped and isinstance(scraped[0], dict) else {}
    if not isinstance(scraped, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unexpected scrape result for URL: {normalized}",
        )
    if scraped.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to scrape URL: {scraped.get('error')}",
        )

    title = (scraped.get("title") or "").strip()
    text_content = scraped.get("text_content") or ""
    if isinstance(text_content, dict):
        text_content = " ".join(
            f"{k}: {v}" for k, v in text_content.items() if v
        )
    text_content = str(text_content).strip()

    # Some blocked pages still return partial HTML; keep going if we have text.
    segments = _text_to_segments(text_content)
    if not segments:
        status_code = scraped.get("status_code")
        warning = scraped.get("scrape_warning")
        detail = f"No extractable text from this URL: {normalized}"
        if status_code:
            detail = f"{detail} (HTTP {status_code})"
        if warning:
            detail = f"{detail}. {warning}"
        raise ValueError(detail)

    final_url = (scraped.get("url") or normalized).strip() or normalized
    if scraped.get("scrape_warning"):
        logger.warning(
            "Partial scrape for %s: %s", final_url, scraped.get("scrape_warning")
        )

    return {
        "url": final_url,
        "title": title,
        "filename": _display_filename(final_url, title),
        "segments": segments,
    }


async def scrape_url_for_rag(url: str) -> dict:
    """Async wrapper around the existing Holdflight website scraper."""
    return await asyncio.to_thread(_scrape_url_for_rag_sync, url)
