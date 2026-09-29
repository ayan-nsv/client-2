import asyncio
from fastapi import APIRouter, Depends, Response, status, HTTPException
from sqlalchemy.orm import Session
from shared.database.postgres.database_config import get_db
from products.knowledge.rag.schema.rag_schema import ChatQuery, WrappedChatResponse
from products.knowledge.rag.services.rag_services import chat_retrieval_is_lexical, rag_service
# from services.rag_query_cache import put_cached_answer, try_get_cached_answer
from core.repository.user_repo import UserRepository
from shared.utils.auth import auth 
from core.repository.company_repo import CompanyRepository

router = APIRouter(prefix="/chat", tags=["chat"])
DEFAULT_TOP_K = 3 #5


@router.post("/{company_id}/query", response_model=WrappedChatResponse)
async def chat_query(
    company_id: str,
    payload: ChatQuery,
    response: Response,
    db: Session = Depends(get_db),
    # user: dict = Depends(get_current_user),
    #api_key: str = Depends(api_key_security)

) -> WrappedChatResponse:
    """
    Query documents with RAG.

    Retrieval mode (env ``CHAT_QUERY_RETRIEVAL_MODE``):

    - ``semantic`` (default): embedding + pgvector cosine distance.
    - ``lexical`` / ``similarity`` / ``trigram``: PostgreSQL ``pg_trgm`` text similarity
      (no query embedding for retrieval).

    Redis RAG answer cache is disabled for this endpoint (see commented blocks below).
    """
    
    # if not api_key or api_key != STATIC_API_KEY:
    #     raise HTTPException(status_code=401, detail="Unauthorized: Invalid API Key")
    
    try:
        company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id)
    except HTTPException as exc:
        response.status_code = exc.status_code
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return {
            "success": False,
            "message": detail,
            "data": {"answer": None},
        }

    # try:
    #     company_id_int = check_user_company_access(company_id, user["uid"], db)
    # except HTTPException as exc:
    #     response.status_code = exc.status_code
    #     detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    #     return {
    #         "success": False,
    #         "message": detail,
    #         "data": {"answer": None},
    #     }

    lexical = chat_retrieval_is_lexical()

    # cached, query_emb = await try_get_cached_answer(
    #     company_id,
    #     payload.query,
    #     rag_service.embeddings,
    #     skip_semantic_cache=lexical,
    # )
    # if cached is not None:
    #     response.status_code = status.HTTP_200_OK if cached.get("success") else status.HTTP_404_NOT_FOUND
    #     out = {
    #         "success": cached.get("success", False),
    #         "message": cached.get("message", "Query failed"),
    #         "data": cached.get("data", {"answer": None}),
    #     }
    #     if out["success"]:
    #         out["message"] = "Query successful (from cache)"
    #     return out

    query_emb = None
    if not lexical:
        query_emb = await asyncio.to_thread(
            rag_service.embeddings.embed_query, payload.query
        )

    result = await asyncio.to_thread(
        rag_service.query,
        payload.query,
        company_id_int,
        DEFAULT_TOP_K,
        None if lexical else query_emb,
        lexical=lexical,
        used_for="voice_call",
    )
    # if result.get("success"):
    #     await put_cached_answer(
    #         company_id,
    #         payload.query,
    #         result,
    #         rag_service.embeddings,
    #         query_embedding=None if lexical else query_emb,
    #         include_semantic_vector=not lexical,
    #     )

    response.status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_404_NOT_FOUND
    return {
        "success": result.get("success", False),
        "message": result.get("message", "Query failed"),
        "data": result.get("data", {"answer": None})
    }