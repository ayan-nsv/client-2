"""
Per-company cache for /chat/{company_id}/query responses.

- Exact match: normalized + case-folded text (same wording after whitespace/case).
- Semantic match: cosine similarity of query embeddings (same meaning, different wording),
  skipped when ``skip_semantic_cache`` is used (lexical-only chat retrieval).

Invalidated when PDFs are uploaded for that company (knowledge base changes).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import OpenAIEmbeddings

from shared.cache.redis import redis
from products.knowledge.rag.utils.rag_utils import normalize_text
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

CACHE_ENABLED = os.getenv("RAG_QUERY_CACHE_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SIMILARITY_THRESHOLD = float(os.getenv("RAG_QUERY_CACHE_SIMILARITY", "0.88"))
MAX_SEMANTIC = int(os.getenv("RAG_QUERY_CACHE_MAX_SEMANTIC", "100"))
MAX_EXACT = int(os.getenv("RAG_QUERY_CACHE_MAX_EXACT", "500"))
DEFAULT_TTL = int(os.getenv("RAG_QUERY_CACHE_TTL", "172800"))  # align with redis_config default (2d)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"


def _bucket_key(company_uuid: str) -> str:
    return f"rag_chat_cache:{company_uuid}"


def _normalized_fingerprint(query: str) -> tuple[str, str]:
    """Returns (normalized_text, sha256_hex) for exact-match keys."""
    norm = normalize_text(query).casefold()
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return norm, h


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _empty_bucket() -> Dict[str, Any]:
    return {"exact": {}, "semantic": []}


async def try_get_cached_answer(
    company_id: str,
    query: str,
    embeddings: OpenAIEmbeddings,
    skip_semantic_cache: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[List[float]]]:
    """
    Returns (cached_result, query_embedding).

    - Cache hit: (dict, None) for exact match; (dict, q_emb) if embedding was computed for semantic match.
    - Cache miss after embedding for semantic scan: (None, q_emb) — reuse q_emb for RAG to avoid a second API call.
    - No bucket / no semantic entries / disabled: (None, None) — caller should embed once.
    - skip_semantic_cache: only exact-match lookup (for lexical / non-embedding retrieval).
    """
    if not CACHE_ENABLED or not query or not query.strip():
        return None, None

    cid = str(company_id)
    raw = await redis.redis_get(_bucket_key(cid))
    if not raw or not isinstance(raw, dict):
        return None, None

    exact_map = raw.get("exact") or {}
    if not isinstance(exact_map, dict):
        exact_map = {}

    _, h = _normalized_fingerprint(query)
    hit = exact_map.get(h)
    if hit is not None and isinstance(hit, dict):
        logger.info(f"RAG query cache hit (exact) company={cid}")
        return copy.deepcopy(hit), None

    if skip_semantic_cache:
        return None, None

    semantic = raw.get("semantic") or []
    if not semantic or not isinstance(semantic, list):
        return None, None

    try:
        q_emb = await asyncio.to_thread(embeddings.embed_query, query)
    except Exception as e:
        logger.warning(f"RAG query cache: embedding for lookup failed: {e}")
        return None, None

    best: Optional[float] = None
    best_payload: Optional[Dict[str, Any]] = None
    for item in semantic:
        if not isinstance(item, dict):
            continue
        vec = item.get("v")
        payload = item.get("payload")
        if not isinstance(vec, list) or not isinstance(payload, dict):
            continue
        sim = _cosine_similarity(q_emb, vec)
        if sim >= SIMILARITY_THRESHOLD and (best is None or sim > best):
            best = sim
            best_payload = payload

    if best_payload is not None:
        logger.info(f"RAG query cache hit (semantic, sim≈{best:.3f}) company={cid}")
        return copy.deepcopy(best_payload), q_emb

    return None, q_emb


async def put_cached_answer(
    company_id: str,
    query: str,
    result: Dict[str, Any],
    embeddings: OpenAIEmbeddings,
    query_embedding: Optional[List[float]] = None,
    include_semantic_vector: bool = True,
) -> None:
    """Store a successful query result. No-op if disabled, Redis down, or result not successful."""
    if not CACHE_ENABLED or not result.get("success"):
        return

    ans = (result.get("data") or {}).get("answer")
    if ans is None or (isinstance(ans, str) and not ans.strip()):
        return

    cid = str(company_id)
    _, h = _normalized_fingerprint(query)

    q_emb: Optional[List[float]] = None
    if include_semantic_vector:
        q_emb = query_embedding
        if q_emb is None:
            try:
                q_emb = await asyncio.to_thread(embeddings.embed_query, query)
            except Exception as e:
                logger.warning(f"RAG query cache: embedding for store failed: {e}")
                return

    raw = await redis.redis_get(_bucket_key(cid))
    bucket = _empty_bucket()
    if raw and isinstance(raw, dict):
        if isinstance(raw.get("exact"), dict):
            bucket["exact"] = dict(raw["exact"])
        if isinstance(raw.get("semantic"), list):
            bucket["semantic"] = list(raw["semantic"])

    to_store = copy.deepcopy(result)
    bucket["exact"][h] = to_store

    # Trim exact map (FIFO by insertion order)
    while len(bucket["exact"]) > MAX_EXACT:
        bucket["exact"].pop(next(iter(bucket["exact"])))

    if include_semantic_vector and q_emb is not None:
        bucket["semantic"].append({"v": q_emb, "payload": to_store})
        while len(bucket["semantic"]) > MAX_SEMANTIC:
            bucket["semantic"].pop(0)

    ok = await redis.redis_set(_bucket_key(cid), bucket, ttl=DEFAULT_TTL)
    if not ok:
        logger.warning(f"RAG query cache: failed to SET bucket for company={cid}")


async def invalidate_company_cache(company_id: str) -> None:
    """Clear all cached answers for a company (e.g. after new PDFs)."""
    cid = str(company_id)
    deleted = await redis.redis_delete(_bucket_key(cid))
    if deleted:
        logger.info(f"RAG query cache invalidated for company={cid}")
