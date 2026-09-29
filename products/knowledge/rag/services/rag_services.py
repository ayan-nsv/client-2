# rag_service.py
import os
from typing import List, Literal, Optional
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from sqlalchemy import bindparam, text
from sqlalchemy.orm import sessionmaker
from shared.database.postgres.database_config import get_engine
# Re-exported for the route modules (chat_routes / chatbot_routes import these from here).
from products.knowledge.rag.utils.rag_utils import (
    openai_langchain_kwargs,
    _selected_upload_method_ids,
    chat_retrieval_is_lexical,
    chatbot_retrieval_is_lexical,
)

# Cosine distance threshold for FAQ match (<=> in pgvector). Lower = stricter.
FAQ_SIMILARITY_THRESHOLD = float(os.getenv("FAQ_SIMILARITY_THRESHOLD", "0.35"))
# Trigram similarity(question, faq_question). Higher = stricter. Range ~0..1.
FAQ_LEXICAL_SIMILARITY_THRESHOLD = float(os.getenv("FAQ_LEXICAL_SIMILARITY_THRESHOLD", "0.35"))


def _embedding_to_vector_literal(embedding: List[float]) -> str:
    """Convert a Python float list to a PostgreSQL pgvector literal for casting."""
    return f"[{','.join(map(str, embedding))}]"


def _ok(message: str, answer: str) -> dict:
    """Build a successful RAG response payload."""
    return {"success": True, "message": message, "data": {"answer": answer}}


def _fail(message: str, answer: str) -> dict:
    """Build a failed RAG response payload."""
    return {"success": False, "message": message, "data": {"answer": answer}}

class PGVectorRetriever:
    """Optimized Retriever for extracted_data embeddings scoped by company."""

    def __init__(self, embeddings: OpenAIEmbeddings, k: int = 20):
        self.embeddings = embeddings
        self.k = k
        self.engine = get_engine()
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _get_relevant_documents(
        self,
        query: str,
        company_id: int,
        k: Optional[int] = None,
        query_embedding: Optional[List[float]] = None,
        *,
        used_for: Literal["chat", "voice_call"],
    ) -> List[Document]:
        limit = k or self.k
        if query_embedding is None:
            query_embedding = self.embeddings.embed_query(query)
        vector_literal = _embedding_to_vector_literal(query_embedding)

        session = self.SessionLocal()
        try:
            selected_ids = _selected_upload_method_ids(session, company_id, used_for)
            if not selected_ids:
                return []

            sql = text(
                f"""
                SELECT ed.chunk_content,
                    ed.embedding <=> '{vector_literal}'::vector AS distance
                FROM extracted_data ed
                WHERE ed.company_id = :company_id
                AND ed.chunk_content IS NOT NULL
                AND ed.upload_method_id IN :selected_ids
                ORDER BY ed.embedding <=> '{vector_literal}'::vector
                LIMIT :k
                """
            ).bindparams(bindparam("selected_ids", expanding=True))

            result = session.execute(
                sql,
                {"company_id": company_id, "k": limit, "selected_ids": selected_ids},
            )
            docs: List[Document] = []
            for row in result:
                chunk_content = (row.chunk_content or "").strip()
                if not chunk_content:
                    continue
                docs.append(Document(
                    page_content=chunk_content,
                    metadata={
                        "distance": float(row.distance)
                    }
                ))
            return docs
        finally:
            session.close()

    def invoke(
        self,
        query: str,
        company_id: int,
        k: Optional[int] = None,
        query_embedding: Optional[List[float]] = None,
        *,
        used_for: Literal["chat", "voice_call"],
    ) -> List[Document]:
        return self._get_relevant_documents(
            query, company_id, k=k, query_embedding=query_embedding, used_for=used_for
        )


class LexicalTrigramRetriever:
    """Retrieve chunks by PostgreSQL pg_trgm word_similarity (query vs chunk text)."""

    def __init__(self, k: int = 20):
        self.k = k
        self.engine = get_engine()
        self.SessionLocal = sessionmaker(bind=self.engine)

    def invoke(
        self,
        query: str,
        company_id: int,
        k: Optional[int] = None,
        *,
        used_for: Literal["chat", "voice_call"],
    ) -> List[Document]:
        limit = k or self.k
        q = (query or "").strip()
        if not q:
            return []

        session = self.SessionLocal()
        try:
            selected_ids = _selected_upload_method_ids(session, company_id, used_for)
            if not selected_ids:
                return []

            sql = text(
                """
                SELECT ed.chunk_content,
                       word_similarity(:query, ed.chunk_content::text) AS score
                FROM extracted_data ed
                WHERE ed.company_id = :company_id
                  AND ed.chunk_content IS NOT NULL
                  AND btrim(ed.chunk_content::text) <> ''
                  AND ed.upload_method_id IN :selected_ids
                ORDER BY score DESC NULLS LAST
                LIMIT :k
                """
            ).bindparams(bindparam("selected_ids", expanding=True))

            result = session.execute(
                sql,
                {
                    "query": q,
                    "company_id": company_id,
                    "k": limit,
                    "selected_ids": selected_ids,
                },
            )
            docs: List[Document] = []
            for row in result:
                chunk_content = (row.chunk_content or "").strip()
                if not chunk_content:
                    continue
                sc = row.score
                docs.append(
                    Document(
                        page_content=chunk_content,
                        metadata={"score": float(sc) if sc is not None else 0.0},
                    )
                )
            return docs
        finally:
            session.close()


class RAGService:
    """RAG service with PostgreSQL vector search, optimized for speed."""

    def __init__(self, k: int = 100, max_chunks: int = 100, max_context_chars: int = 3000):
        openai_api_key = os.getenv("OPENAI_API_KEY")
        embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
        langchain_openai = openai_langchain_kwargs()
        self.embeddings = OpenAIEmbeddings(
            api_key=openai_api_key,
            model=embedding_model,
            **langchain_openai,
        )
        self.retriever = PGVectorRetriever(self.embeddings, k=k)
        self.lexical_retriever = LexicalTrigramRetriever(k=k)
        self.llm = ChatOpenAI(
            api_key=openai_api_key,
            model="gpt-4o-mini", #gpt-4-turbo
            temperature=0,
            max_tokens=300,
            timeout=200,
            **langchain_openai,
        )
        self.max_chunks = max_chunks
        self.max_context_chars = max_context_chars
        self._faq_engine = get_engine()
        self._faq_session = sessionmaker(bind=self._faq_engine)
        self._setup_chain()

    def get_faq_answer(
        self,
        question: str,
        company_id: int,
        query_embedding: Optional[List[float]] = None,
    ) -> Optional[str]:
        """
        Search company FAQs by similarity. If the best match is within threshold, return its answer; else None.
        """
        try:
            if query_embedding is None:
                query_embedding = self.embeddings.embed_query(question)
            vector_literal = _embedding_to_vector_literal(query_embedding)

            sql_str = f"""
            SELECT cf.answer, cf.embedding <=> '{vector_literal}'::vector AS distance
            FROM company_faqs cf
            WHERE cf.company_id = :company_id
            ORDER BY cf.embedding <=> '{vector_literal}'::vector
            LIMIT 1
            """
            session = self._faq_session()
            try:
                result = session.execute(text(sql_str), {"company_id": company_id})
                row = result.fetchone()
                if row and row.distance is not None and float(row.distance) <= FAQ_SIMILARITY_THRESHOLD:
                    return (row.answer or "").strip()
                return None
            finally:
                session.close()
        except Exception:
            return None

    def get_faq_answer_lexical(self, question: str, company_id: int) -> Optional[str]:
        """Match FAQ rows by trigram similarity on question text (no embeddings)."""
        q = (question or "").strip()
        if not q:
            return None
        sql = text(
            """
            SELECT cf.answer,
                   similarity(:query, cf.question::text) AS score
            FROM company_faqs cf
            WHERE cf.company_id = :company_id
            ORDER BY score DESC NULLS LAST
            LIMIT 1
            """
        )
        session = self._faq_session()
        try:
            result = session.execute(sql, {"query": q, "company_id": company_id})
            row = result.fetchone()
            if (
                row
                and row.score is not None
                and float(row.score) >= FAQ_LEXICAL_SIMILARITY_THRESHOLD
            ):
                return (row.answer or "").strip()
            return None
        except Exception:
            return None
        finally:
            session.close()

    def _setup_chain(self) -> None:
        self.prompt = ChatPromptTemplate.from_template(
            """
                IMPORTANT: Answer the question using the provided context as the primary source. You may ALSO use facts the visitor stated earlier in the conversation history (provided in a preceding system message) to answer personal or contextual questions — for example their name, their company, or other details they shared during the chat.

                CRITICAL RULES:
                1. If the question is in English → answer in English.
                2. If the question is in Swedish → answer in Swedish.
                3. NEVER mix languages in your response.
                4. Only if NEITHER the context NOR the conversation history contains enough information to answer, reply **EXACTLY**:
                    - English: "I dont know based on the provided information."
                    - Swedish: "Jag vet inte baserat på den information som lämnats."

                GENERAL GREETINGS AND INTERACTIONS:
                
                - If the question is a greeting like "Hello", "Hi", "What's up?", "Hey", or similar:
                    - English: "Hello! How can I assist you today?"
                    - Swedish: "Hej! Hur kan jag hjälpa dig idag??"

                - If the question is "Who are you?":
                    - English: "I'm a helper here to assist you, Feel free to ask."
                    - Swedish: "Jag är en hjälpare här för att hjälpa dig, tveka inte att fråga."

                - If the question is "Thanks" or "Thank you":
                    - English: "You're welcome! Let me know if you need anything else."
                    - Swedish: "Varsågod! Hör av dig om du behöver något mer."

                - If the question is "Goodbye", "Bye", "See you", or "Take care":
                    - English: "Goodbye! Take care, and feel free to reach out if you need help later."
                    - Swedish: "Hej då! Ta hand om dig, och hör gärna av dig om du behöver hjälp senare."

                - If the question is "How are you?":
                    - English: "I'm doing great, thank you! How about you?"
                    - Swedish: "Jag mår jättebra, tack! Hur är det med dig?"

                - If the question is "What’s your name?":
                    - English: "I don't have a name, but you can call me virtual Assistant!"
                    - Swedish: "I don't have a name, but you can call me Virtual Assistant!"

                - If the question is "What can I ask you about?":
                    - English: "You can ask me about company commands, setup instructions, troubleshooting, features, and automation routines."
                    - Swedish: "Du kan fråga mig om företagskommandon, installationsanvisningar, felsökning, funktioner och automatiseringsrutiner."

                - If the question is "Can you help me with something?":
                    - English: "Of course! What do you need help with?"
                    - Swedish: "Självklart! Vad behöver du hjälp med?"

                - If the question is "What time is it?" or "Do you know the time?":
                    - English: "I’m afraid I don’t have access to the current time, but you can easily check on your device."
                    - Swedish: "Jag har tyvärr inte tillgång till aktuell tid, men du kan enkelt kontrollera det på din enhet."

                - If the question is "I am fine" or "I am ok" or similar:
                    - English: "Glad to hear that! How can I assist you?"
                    - Swedish: "Kul att höra det! Hur kan jag hjälpa dig?"

                Context:
                {context}

                Question:
                {question}

                Answer (only based on context, but you may summarize or rephrase as needed):
            """
        )

    def _format_lead_fields(self, lead_fields: List[dict]) -> str:
        """Render configured lead fields as a bullet list for the LLM prompt."""
        lines = []
        for field in lead_fields or []:
            name = (field.get("field_name") or "").strip()
            if not name:
                continue
            requirement = "required" if field.get("is_required") else "optional"
            lines.append(f"- {name} ({requirement})")
        return "\n".join(lines)

    def _format_history(self, history: Optional[List[dict]]) -> str:
        """Render the prior conversation turns so the LLM knows what was already collected."""
        if not history:
            return ""
        lines = []
        for turn in history:
            message = (turn.get("message") or "").strip()
            if not message:
                continue
            sender = (turn.get("sender") or "").strip().lower()
            role = "Visitor" if sender == "visitor" else "Assistant"
            lines.append(f"{role}: {message}")
        return "\n".join(lines)

    def _build_history_message(self, history: Optional[List[dict]]):
        """Build a system message with recent conversation history, or None if empty."""
        history_block = self._format_history(history)
        if not history_block:
            return None
        content = (
            "Use the following recent conversation history to understand the "
            "visitor's current message (e.g. follow-up questions or references to "
            "earlier turns). You may answer using facts the visitor explicitly "
            "stated earlier in this history (such as their name or the company they "
            "work at), even if those facts are not in the knowledge-base context. "
            "Reply in the same language as the visitor.\n\n"
            f"Conversation so far:\n{history_block}\n"
        )
        return SystemMessage(content=content)

    def _contextualize_question(
        self,
        question: str,
        history: Optional[List[dict]],
    ) -> str:
        """Rewrite a follow-up question into a standalone search query.

        Retrieval (embeddings / lexical / FAQ lookup) is context-blind: it only
        sees the literal new message. A follow-up such as "components of that"
        therefore retrieves poorly because "that" is unresolved. Using the recent
        conversation history, this produces a self-contained query (e.g.
        "components of RAG") that the retriever can match against.

        Returns the original ``question`` unchanged when there is no history, the
        message is empty, or rewriting fails for any reason.
        """
        original = (question or "").strip()
        if not original:
            return original

        history_block = self._format_history(history)
        if not history_block:
            return original

        try:
            system = SystemMessage(
                content=(
                    "You rewrite a visitor's latest message into a standalone "
                    "search query for a knowledge base. Use the conversation "
                    "history ONLY to resolve references (pronouns like 'it', "
                    "'that', 'those', or implicit subjects) so the query makes "
                    "sense on its own.\n\n"
                    "Rules:\n"
                    "- Output ONLY the rewritten query, with no quotes or extra "
                    "text.\n"
                    "- Keep it in the same language as the visitor's message.\n"
                    "- If the message is already standalone, a greeting, or small "
                    "talk, return it unchanged.\n"
                    "- Do not answer the question; only rewrite it.\n"
                    "- Keep it concise (one sentence)."
                )
            )
            human = HumanMessage(
                content=(
                    f"Conversation so far:\n{history_block}\n\n"
                    f"Latest visitor message:\n{original}\n\n"
                    "Standalone query:"
                )
            )
            response = self.llm.invoke([system, human])
            rewritten = (response.content or "").strip().strip('"').strip()
            return rewritten or original
        except Exception:
            return original

    def _build_context(self, docs: List[Document]) -> str:
        """Join retrieved chunks into a single context string, capped at max_context_chars."""
        context_parts: List[str] = []
        current_len = 0
        for doc in docs:
            chunk = doc.page_content.strip()
            if not chunk:
                continue
            if current_len + len(chunk) > self.max_context_chars:
                break
            context_parts.append(chunk)
            current_len += len(chunk)
        return "\n\n".join(context_parts)

    def _build_lead_messages(
        self,
        context: str,
        question: str,
        lead_fields: List[dict],
        history: Optional[List[dict]],
    ) -> List:
        """Build a coherent lead-aware prompt (answering + lead collection).

        Unlike the base RAG prompt, the "I don't know" fallback here is scoped to
        informational questions only, so the bot never replies "I don't know" when
        the visitor is sharing contact details or asking to be contacted.
        """
        fields_block = self._format_lead_fields(lead_fields)
        history_block = self._format_history(history)

        system_content = (
            "You are a helpful assistant for a business. You answer visitor questions "
            "using the provided context, and you also collect the visitor's contact / "
            "lead details when there is a need.\n\n"
            "LANGUAGE RULES:\n"
            "- If the visitor writes in English, reply in English.\n"
            "- If the visitor writes in Swedish, reply in Swedish.\n"
            "- Never mix languages.\n\n"
            "LEAD COLLECTION:\n"
            "Lead fields to collect when there is a need:\n"
            f"{fields_block}\n\n"
            "Rules:\n"
            "1. Answer the visitor's informational question first. Never ask for a "
            "name, email address, phone number, or other personal details merely to "
            "start or continue the chat.\n"
            "2. Ask for lead details only after the visitor clearly requests an action "
            "that requires them, such as a booking, callback, quote, demo, follow-up, "
            "or being contacted. A greeting, general question, product question, or "
            "request for information does not activate lead collection.\n"
            "3. The word REQUIRED describes which fields are needed to complete an "
            "active lead/contact flow. Missing required fields alone are never a reason "
            "to start collecting personal information.\n"
            "4. During an active lead/contact flow, ask only for the missing details "
            "needed to complete that request (at most one or two at a time). Never "
            "re-ask for information already provided earlier in the conversation.\n"
            "5. If the visitor voluntarily shares lead details, acknowledge what they "
            "shared, but do not assume they want a callback or end the conversation. "
            "Continue helping with their current request. NEVER reply 'I don't know' "
            "when the visitor is sharing contact details.\n"
            "6. Once an active booking/contact request has the required details, "
            "confirm the request and the captured details. Say that the team will "
            "follow up only when follow-up was actually requested or is necessary. "
            "Do not close the conversation solely because contact details were "
            "collected.\n\n"
            "ANSWERING QUESTIONS:\n"
            "- Use the context to answer informational questions.\n"
            "- Only if the visitor asks an informational question that the context "
            "does not cover AND that is unrelated to lead details / contact / booking, "
            "reply EXACTLY:\n"
            '    - English: "Unfortunately, I do not have that information."\n'
            '    - Swedish: "Jag har tyvärr inte den informationen."\n'
        )
        if history_block:
            system_content += f"\nConversation so far:\n{history_block}\n"

        human_content = (
            f"Context:\n{context}\n\n"
            f"Visitor message:\n{question}\n\n"
            "Your reply:"
        )
        return [
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ]

    def query(
        self,
        question: str,
        company_id: int,
        top_k: Optional[int] = None,
        query_embedding: Optional[List[float]] = None,
        *,
        lexical: Optional[bool] = None,
        used_for: Literal["chat", "voice_call"],
        lead_fields: Optional[List[dict]] = None,
        history: Optional[List[dict]] = None,
    ) -> dict:
        try:
            use_lexical = chat_retrieval_is_lexical() if lexical is None else lexical
            collect_leads = bool(lead_fields)

            # Resolve follow-up references against the conversation history so
            # retrieval is no longer context-blind (e.g. "components of that" ->
            # "components of RAG"). The original ``question`` is still used for
            # answer generation so the LLM replies to the visitor's actual wording.
            search_question = self._contextualize_question(question, history)
            
            if search_question != question:
                # The passed-in embedding (if any) was computed from the original
                # message, so it no longer matches the rewritten query.
                query_embedding = None

            if use_lexical:
                # Skip the FAQ shortcut when collecting leads so the LLM manages the turn.
                if not collect_leads:
                    faq_answer = self.get_faq_answer_lexical(search_question, company_id)
                    if faq_answer is not None:
                        return _ok("Query successful (from FAQ, lexical match)", faq_answer)
                docs = self.lexical_retriever.invoke(
                    search_question,
                    company_id,
                    k=top_k or self.max_chunks,
                    used_for=used_for,
                )
            else:
                if query_embedding is None:
                    query_embedding = self.embeddings.embed_query(search_question)

                if not collect_leads:
                    faq_answer = self.get_faq_answer(
                        search_question, company_id, query_embedding=query_embedding
                    )
                    if faq_answer is not None:
                        return _ok("Query successful (from FAQ)", faq_answer)

                docs = self.retriever.invoke(
                    search_question,
                    company_id,
                    k=top_k or self.max_chunks,
                    query_embedding=query_embedding,
                    used_for=used_for,
                )

            # When collecting leads, proceed to the LLM even without context so it can
            # still ask for / acknowledge lead details. Also proceed when there is
            # prior conversation history, so the LLM can answer questions that refer
            # back to facts the visitor stated earlier (e.g. their name / company).
            has_history = bool(self._format_history(history))
            if not docs and not collect_leads and not has_history:
                return _fail(
                    "No relevant information found.",
                    "I don't know based on the provided information.",
                )

            context = self._build_context(docs)

            if collect_leads:
                messages = self._build_lead_messages(
                    context, question, lead_fields, history
                )
            else:
                messages = self.prompt.format_messages(
                    context=context, question=question
                )
                history_message = self._build_history_message(history)
                if history_message is not None:
                    messages = [history_message] + messages

            response = self.llm.invoke(messages)
            answer = response.content.strip()
            msg = (
                "Query successful (lexical similarity)"
                if use_lexical
                else "Query successful"
            )
            return _ok(msg, answer)
        except Exception as e:
            return _fail(f"Error: {str(e)}", "Error processing query.")


# Initialize the service:
# DEFAULT_TOP_K: default number of top similar documents to retrieve per query.
# k: number of nearest neighbor embeddings to fetch in a retrieval call.
# max_chunks: maximum number of document chunks to include in context for the LLM.
# max_context_chars: maximum total characters from retrieved chunks to pass as context to the LLM.
rag_service = RAGService(k=20, max_chunks=5, max_context_chars=8000) #1600
