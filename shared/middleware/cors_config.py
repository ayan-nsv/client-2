"""CORS configuration loaded from environment."""

import os
from typing import List


def get_cors_allow_credentials() -> bool:
    """
    Return whether credentialed CORS requests are allowed.

    Disabled by default: authentication uses Authorization headers / API keys,
    not browser cookies. Set CORS_ALLOW_CREDENTIALS=true only if cookie-based
    auth is introduced.
    """
    raw = os.getenv("CORS_ALLOW_CREDENTIALS", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _normalize_origin(origin: str) -> str:
    """Normalize a configured origin (strip whitespace and trailing slash)."""
    normalized = origin.strip().rstrip("/")
    return normalized


def get_cors_allowed_origins() -> List[str]:
    """
    Return the CORS origin allowlist from CORS_ALLOWED_ORIGINS.

    Optional env var — comma-separated origins, e.g.:
    CORS_ALLOWED_ORIGINS=https://apps.domain.se,http://localhost:3000

    When unset or empty, returns an empty list (no cross-origin browser
    access until explicitly configured). This avoids breaking startup in
    environments that do not need CORS.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS")
    if raw is None or not raw.strip():
        return []

    origins = [_normalize_origin(part) for part in raw.split(",")]
    return [origin for origin in origins if origin]
