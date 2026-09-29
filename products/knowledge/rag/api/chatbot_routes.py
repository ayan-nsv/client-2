import asyncio
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from shared.database.postgres.database_config import get_db
from products.knowledge.rag.utils.rag_utils import chatbot_retrieval_is_lexical
from products.knowledge.rag.services.rag_services import rag_service
from core.tables import user_tables 
from products.knowledge.rag.tables import chatbot_tables
from products.knowledge.rag.schema import chatbot_schema 
    
from products.knowledge.rag.services import chatbot_lead_service 
from shared.utils.email.email_service import send_template_email
from shared.utils.constants.constants import SENDGRID_CHATBOT_LEAD_TEMPLATE_ID
from products.knowledge.rag.services.chatbot_lead_service import get_chatbot
from shared.utils.auth import auth
from shared.utils.error  import error_handler, error
from shared.logger.log import setup_logger
from core.repository.company_repo import CompanyRepository
from core.repository.user_repo import UserRepository


logger = setup_logger("marketing-app")
router = APIRouter(prefix="/chatbots", tags=["chatbots"])

CHATBOT_WIDGET_URL = os.getenv(
    "CHATBOT_WIDGET_URL", "https://staging.d3pp510dzw74a7.amplifyapp.com/chat-widget-loader.js"
)
DEFAULT_TOP_K = 15


def _is_static_admin_user(user: dict) -> bool:
    return bool(user.get("is_static_admin"))


def _parse_uuid(raw_value: str, label: str) -> UUID:
    """Parse a UUID string, raising a 400 HTTPException with ``label`` on failure."""
    try:
        return UUID(str(raw_value).strip())
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {label}")


def _ensure_company_admin(user: dict, chatbot, db: Session) -> None:
    """Raise 403 unless ``user`` is a static admin or an admin of the chatbot's company."""
    if _is_static_admin_user(user):
        return
    if (
        chatbot is None
        or chatbot.company_id is None
        or not UserRepository(db).is_user_admin(user["uid"], chatbot.company_id)
    ):
        return error.PermissionDenied(message="Admin privileges required")


def _build_chatbot_script(chatbot_uuid: UUID) -> str:
    """Build the embeddable widget script tag for a chatbot."""
    return f'<script src="{CHATBOT_WIDGET_URL}" data-market-planner-chatbot-id="{chatbot_uuid}" async></script>'

#Create chatbot
@router.post(
    "",
    response_model=chatbot_schema.ChatBotResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_chatbot(
    payload: chatbot_schema.ChatBotCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Create a chatbot for a company.

    The caller must be a static admin or a company admin. ``company_id`` in the
    payload is the company UUID and is resolved to the internal integer id.
    """
    try:
        firebase_uid = user["uid"]

        try:
            company_int_id = CompanyRepository(db).get_company_id_from_uuid(payload.company_id)
        except HTTPException as exc:
            return error.InternalServerError(message=str(exc.detail))

        if not _is_static_admin_user(user) and not UserRepository(db).is_user_admin(firebase_uid, company_int_id):
            return error.PermissionDenied(message="Admin privileges required")

        existing_chatbot = (
            db.query(chatbot_tables.ChatBot).filter(chatbot_tables.ChatBot.company_id == company_int_id).first()
        )
        if existing_chatbot:
            return error.Conflict(message="A chatbot already exists for this company")
                
        created_by_id = None
        if not _is_static_admin_user(user):
            user_record = (
                db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
            )
            if not user_record:
                return error.NotFound(message=f"User with Firebase UID '{firebase_uid}' not found in database.")
                   
            created_by_id = user_record.id

        chatbot_uuid = uuid4()
        chatbot = chatbot_tables.ChatBot(
            uuid=chatbot_uuid,
            company_id=company_int_id,
            name=payload.name,
            is_enabled=payload.is_enabled,
            greeting_message=payload.greeting_message,
            primary_color=payload.primary_color,
            lead_collection_enabled=payload.lead_collection_enabled,
            lead_recipient_email=payload.lead_recipient_email,
            created_by_id=created_by_id,
            script=_build_chatbot_script(chatbot_uuid),
        )

        db.add(chatbot)
        db.commit()
        db.refresh(chatbot)

        return chatbot_schema.ChatBotResponse(
            success=True,
            message="Chatbot created successfully",
            data=chatbot_schema.ChatBotItem.model_validate(chatbot),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to create chatbot: {exc}")
        return error.InternalServerError(message="Failed to create chatbot")
            
#List chatbots for a company
@router.get(
    "/{company_id}/chatbots",
    response_model=chatbot_schema.ChatBotListResponse,
    response_model_exclude_none=True,
)
async def list_company_chatbots(
    company_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """List the chatbots owned by a company (without lead fields).

    ``company_id`` is the company UUID. The caller must be a static admin or a
    member of that company; cross-company access is denied.
    """
    try:
        company_int_id = CompanyRepository(db).get_company_id_from_uuid(company_id)

        chatbots = (
            db.query(chatbot_tables.ChatBot)
            .filter(chatbot_tables.ChatBot.company_id == company_int_id)
            .order_by(chatbot_tables.ChatBot.created_at.desc())
            .all()
        )

        return chatbot_schema.ChatBotListResponse(
            success=True,
            message="Chatbots retrieved successfully",
            data=[chatbot_schema.ChatBotItem.model_validate(c) for c in chatbots],
        )
    except HTTPException as exc:
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        logger.error(f"Failed to list chatbots: {exc}")
        return error.InternalServerError(message="Failed to list chatbots")


#Chatbot settings retrieval - used by the embedded widget
@router.get(
    "/{chatbot_id}/settings",
    response_model=chatbot_schema.ChatBotSettingsResponse,
    response_model_exclude_none=True,
)
async def get_chatbot_settings(
    chatbot_id: UUID,
    db: Session = Depends(get_db),
):
    """Return a chatbot's configuration, including its lead-collection fields.

    ``chatbot_id`` is the chatbot UUID. No authentication is required. Disabled
    chatbots return 403.
    """
    try:
        chatbot = get_chatbot(chatbot_id, db)

        if not chatbot.is_enabled:
            return error.PermissionDenied(message="This chatbot is not enabled")

        return chatbot_schema.ChatBotSettingsResponse(
            success=True,
            message="Chatbot settings retrieved successfully",
            data=chatbot_schema.ChatBotSettingsItem.model_validate(chatbot),
        )
    except HTTPException as exc:
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        logger.error(f"Failed to retrieve chatbot settings: {exc}")
        return error.InternalServerError(message="Failed to retrieve chatbot settings")

@router.post(
    "/{chatbot_id}/lead-fields",
    response_model=chatbot_schema.ChatbotLeadFieldListResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def add_chatbot_lead_fields(
    chatbot_id: str,
    payload: chatbot_schema.ChatbotLeadFieldsBulkAddRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Add one or more lead-collection fields to a chatbot in a single request.

    ``chatbot_id`` is the chatbot UUID. The caller must be a static admin or a
    company admin for the company that owns the chatbot. The whole batch is
    rejected if any field name is empty or duplicated (within the payload or
    against existing fields).
    """
    try:
        chatbot = get_chatbot(chatbot_id, db)

        _ensure_company_admin(user, chatbot, db)

        cleaned_fields: list[tuple[str, bool]] = []
        seen_names: set[str] = set()
        for field in payload.fields:
            field_name = field.field_name.strip()
            if not field_name:
                return error.BadRequest(message="Field name must not be empty")
            if field_name.lower() in seen_names:
                return error.BadRequest(message=f"Duplicate lead field name in request: '{field_name}'")
            seen_names.add(field_name.lower())
            cleaned_fields.append((field_name, field.is_required))

        existing_names = {
            name.lower()
            for (name,) in db.query(chatbot_tables.ChatbotLeadFields.field_name)
            .filter(chatbot_tables.ChatbotLeadFields.chatbot_id == chatbot.id)
            .all()
        }
        conflicts = [
            name for (name, _) in cleaned_fields if name.lower() in existing_names
        ]
        if conflicts:
            return error.BadRequest(message=f"Lead field(s) already exist for this chatbot: {', '.join(conflicts)}")

        lead_fields = [
            chatbot_tables.ChatbotLeadFields(
                chatbot_id=chatbot.id,
                field_name=name,
                is_required=is_required,
            )
            for (name, is_required) in cleaned_fields
        ]

        db.add_all(lead_fields)
        db.commit()
        for lead_field in lead_fields:
            db.refresh(lead_field)

        return chatbot_schema.ChatbotLeadFieldListResponse(
            success=True,
            message="Lead fields added successfully",
            data=[chatbot_schema.ChatbotLeadFieldItem.model_validate(lf) for lf in lead_fields],
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to add lead fields: {exc}")
        return error.InternalServerError(message="Failed to add lead fields")

@router.patch(
    "/lead-fields/{field_id}",
    response_model=chatbot_schema.ChatbotLeadFieldResponse,
    response_model_exclude_none=True,
)
async def update_chatbot_lead_field(
    field_id: str,
    payload: chatbot_schema.ChatbotLeadFieldUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Update a single lead-collection field.

    ``field_id`` is the lead field UUID. Only fields present in the payload are
    updated. The caller must be a static admin or a company admin for the
    company that owns the parent chatbot.
    """
    try:
        field_uuid = _parse_uuid(field_id, "lead field id")

        lead_field = (
            db.query(chatbot_tables.ChatbotLeadFields)
            .filter(chatbot_tables.ChatbotLeadFields.uuid == field_uuid)
            .first()
        )
        if not lead_field:
            return error.NotFound(message="Lead field not found")
        chatbot = lead_field.chatbot
        _ensure_company_admin(user, chatbot, db)

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return error.BadRequest(message="No fields provided to update")
        if "field_name" in updates:
            new_name = (updates["field_name"] or "").strip()
            if not new_name:
                return error.BadRequest(message="Field name must not be empty")
            duplicate = (
                db.query(chatbot_tables.ChatbotLeadFields)
                .filter(
                    chatbot_tables.ChatbotLeadFields.chatbot_id == lead_field.chatbot_id,
                    chatbot_tables.ChatbotLeadFields.field_name == new_name,
                    chatbot_tables.ChatbotLeadFields.id != lead_field.id,
                )
                .first()
            )
            if duplicate:
                return error.Conflict(message="A lead field with this name already exists for this chatbot")
            updates["field_name"] = new_name

        for field, value in updates.items():
            setattr(lead_field, field, value)

        db.commit()
        db.refresh(lead_field)

        return chatbot_schema.ChatbotLeadFieldResponse(
            success=True,
            message="Lead field updated successfully",
            data=chatbot_schema.ChatbotLeadFieldItem.model_validate(lead_field),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to update lead field: {exc}")
        return error.InternalServerError(message="Failed to update lead field")


@router.delete(
    "/lead-fields/{field_id}",
    response_model=chatbot_schema.ChatbotLeadFieldResponse,
    response_model_exclude_none=True,
)
async def delete_chatbot_lead_field(
    field_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Delete a single lead-collection field.

    ``field_id`` is the lead field UUID. The caller must be a static admin or a
    company admin for the company that owns the parent chatbot.
    """
    try:
        field_uuid = _parse_uuid(field_id, "lead field id")

        lead_field = (
            db.query(chatbot_tables.ChatbotLeadFields)
            .filter(chatbot_tables.ChatbotLeadFields.uuid == field_uuid)
            .first()
        )
        if not lead_field:
            return error.NotFound(message="Lead field not found")
        chatbot = lead_field.chatbot
        _ensure_company_admin(user, chatbot, db)

        db.delete(lead_field)
        db.commit()

        return chatbot_schema.ChatbotLeadFieldResponse(
            success=True,
            message="Lead field deleted successfully",
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to delete lead field: {exc}")
        return error.InternalServerError(message="Failed to delete lead field")


@router.patch(
    "/{chatbot_id}",
    response_model=chatbot_schema.ChatBotResponse,
    response_model_exclude_none=True,
)
async def update_chatbot(
    chatbot_id: str,
    payload: chatbot_schema.ChatBotUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Update a chatbot's configuration.

    ``chatbot_id`` is the chatbot UUID. Only fields present in the payload are
    updated. The caller must be a static admin or a company admin for the
    company that owns the chatbot.
    """
    try:
        chatbot = get_chatbot(chatbot_id, db)

        _ensure_company_admin(user, chatbot, db)

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return error.BadRequest(message="No fields provided to update")
        for field, value in updates.items():
            setattr(chatbot, field, value)

        db.commit()
        db.refresh(chatbot)

        return chatbot_schema.ChatBotResponse(
            success=True,
            message="Chatbot updated successfully",
            data=chatbot_schema.ChatBotItem.model_validate(chatbot),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to update chatbot: {exc}")
        return error.InternalServerError(message="Failed to update chatbot")

@router.delete(
    "/{chatbot_id}",
    response_model=chatbot_schema.ChatBotResponse,
    response_model_exclude_none=True,
)
async def delete_chatbot(
    chatbot_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
):
    """Delete a chatbot.

    ``chatbot_id`` is the chatbot UUID. The caller must be a static admin or a
    company admin for the company that owns the chatbot.
    """
    try:
        chatbot = get_chatbot(chatbot_id, db)

        _ensure_company_admin(user, chatbot, db)

        db.delete(chatbot)
        db.commit()

        return chatbot_schema.ChatBotResponse(
            success=True,
            message="Chatbot deleted successfully",
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to delete chatbot: {exc}")
        return error.InternalServerError(message="Failed to delete chatbot")

@router.post(
    "/{chatbot_id}/conversation",
    response_model=chatbot_schema.ChatbotConversationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def start_chatbot_conversation(
    chatbot_id: str,
    payload: chatbot_schema.ChatbotConversationStartRequest,                                                                          
    db: Session = Depends(get_db),
):
    """Start a new visitor conversation for a chatbot and return its identifier.

    ````chatbot_id`` is the chatbot UUID (from the URL). The optional visitor email
    and originating page URL are provided in the payload. Returns the created
    conversation, whose ``uuid`` is the conversation id used by the widget.
    """
    try:
        chatbot = get_chatbot(chatbot_id, db)

        if not chatbot.is_enabled:
            return error.PermissionDenied(message="This chatbot is not enabled")
        conversation = chatbot_tables.ChatbotConversations(
            chatbot_id=chatbot.id,
            visitor_email=payload.email_id,
            website_url=payload.website_url,
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        return chatbot_schema.ChatbotConversationResponse(
            success=True,
            message="Conversation started successfully",
            data=chatbot_schema.ChatbotConversationItem.model_validate(conversation),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to start chatbot conversation: {exc}")
        return error.InternalServerError(message="Failed to start chatbot conversation")


@router.post(
    "/conversations/{conversation_id}/chat",
    response_model=chatbot_schema.ChatbotTextChatResponse,
    response_model_exclude_none=True,
)
async def text_chat(
    conversation_id: str,
    payload: chatbot_schema.ChatbotTextChatRequest,
    db: Session = Depends(get_db),
):
    """Handle one text-chat turn within an existing conversation.

    ``conversation_id`` is the conversation UUID (from the URL) and ``query`` is
    the visitor's message. The answer is generated from the owning company's
    knowledge base via the RAG service. The visitor message and the bot reply
    are persisted to ``chatbot_messages`` and the answer is returned.

    Retrieval mode (env ``CHATBOT_RETRIEVAL_MODE``):

    - ``semantic`` (default): embedding + pgvector cosine distance.
    - ``lexical`` / ``similarity`` / ``trigram``: PostgreSQL ``pg_trgm`` text
      similarity (no query embedding for retrieval).
    """
    try:
        conv_uuid = _parse_uuid(conversation_id, "conversation id")

        conversation = (
            db.query(chatbot_tables.ChatbotConversations)
            .filter(chatbot_tables.ChatbotConversations.uuid == conv_uuid)
            .first()
        )
        if not conversation:
            return error.NotFound(message="Conversation not found")
        if conversation.ended_at is not None:
            return error.Conflict(message="This conversation has ended")
               

        chatbot = conversation.chatbot
        if chatbot is None or not chatbot.is_enabled:
            return error.PermissionDenied(message="This chatbot is not available")
        if chatbot.company_id is None:
            return error.Conflict(message="Chatbot is not linked to a company")

        # Lead fields
        lead_fields: list[dict] = []
        if chatbot.lead_collection_enabled:
            lead_fields = [
                {
                    "field_name": lf.field_name,
                    "is_required": bool(lf.is_required),
                }
                for lf in db.query(chatbot_tables.ChatbotLeadFields)
                .filter(chatbot_tables.ChatbotLeadFields.chatbot_id == chatbot.id)
                .order_by(chatbot_tables.ChatbotLeadFields.created_at.asc())
                .all()
            ]

        # Most recent prior turns (before this message) so the LLM knows what was
        # already collected. Capped to the last 15 messages to bound prompt size.
        recent_messages = (
            db.query(chatbot_tables.ChatbotMessages)
            .filter(chatbot_tables.ChatbotMessages.conversation_id == conversation.id)
            .order_by(chatbot_tables.ChatbotMessages.created_at.desc())
            .limit(15)
            .all()
        )
        history = [
            {"sender": m.sender, "message": m.message}
            for m in reversed(recent_messages)
        ]

        visitor_message = chatbot_tables.ChatbotMessages(
            conversation_id=conversation.id,
            sender="visitor",
            message=payload.query,
        )
        db.add(visitor_message)
        db.flush()

        # Generate the answer from the knowledge base, mirroring chat_query.
        lexical = chatbot_retrieval_is_lexical()

        query_emb = None
        if not lexical:
            query_emb = await asyncio.to_thread(
                rag_service.embeddings.embed_query, payload.query
            )

        result = await asyncio.to_thread(
            rag_service.query,
            payload.query,
            chatbot.company_id,
            DEFAULT_TOP_K,
            None if lexical else query_emb,
            lexical=lexical,
            used_for="chat",
            lead_fields=lead_fields,
            history=history,
        )

        answer = (result.get("data") or {}).get("answer")
        if not answer:
            answer = "I'm sorry, I couldn't find an answer to that right now."

        bot_message = chatbot_tables.ChatbotMessages(
            conversation_id=conversation.id,
            sender="bot",
            message=answer,
        )
        db.add(bot_message)
        db.commit()
        db.refresh(visitor_message)
        db.refresh(bot_message)

        return chatbot_schema.ChatbotTextChatResponse(
            success=True,
            message="Message processed successfully",
            data=chatbot_schema.ChatbotTextChatData(
                conversation_uuid=conversation.uuid,
                answer=answer,
                visitor_message=chatbot_schema.ChatbotMessageItem.model_validate(visitor_message),
                bot_message=chatbot_schema.ChatbotMessageItem.model_validate(bot_message),
            ),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to process text chat: {exc}")
        return error.InternalServerError(message="Failed to process text chat")


@router.post(
    "/conversations/{conversation_id}/close",
    response_model=chatbot_schema.ChatbotConversationCloseResponse,
    response_model_exclude_none=True,
)
async def close_chatbot_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    """Close a chatbot conversation and capture a lead if one was collected.

    ``conversation_id`` is the conversation UUID (from the URL). All messages in
    the conversation are inspected to decide whether the visitor actually
    provided the lead details the chatbot was configured to collect:

    - The conversation is always marked as ended (``ended_at`` is set).
    - If a lead was provided, ``chatbot_conversations.lead_created`` is set to
      ``True`` and a record is created/updated in ``chatbot_leads`` (with an AI
      summary and the conversation transcript).
    """
    try:
        conv_uuid = _parse_uuid(conversation_id, "conversation id")

        conversation = (
            db.query(chatbot_tables.ChatbotConversations)
            .filter(chatbot_tables.ChatbotConversations.uuid == conv_uuid)
            .first()
        )
        if not conversation:
            return error.NotFound(message="Conversation not found")
        # Idempotent: closing an already-closed conversation just returns state.
        if conversation.ended_at is not None:
            existing_lead = (
                db.query(chatbot_tables.ChatbotLeads)
                .filter(chatbot_tables.ChatbotLeads.conversation_id == conversation.id)
                .first()
            )
            return chatbot_schema.ChatbotConversationCloseResponse(
                success=True,
                message="Conversation already closed",
                data=chatbot_schema.ChatbotConversationCloseData(
                    conversation_uuid=conversation.uuid,
                    ended_at=conversation.ended_at,
                    lead_created=bool(conversation.lead_created),
                    lead=(
                        chatbot_schema.ChatbotLeadItem.model_validate(existing_lead)
                        if existing_lead
                        else None
                    ),
                ),
            )

        chatbot = conversation.chatbot

        # Configured lead fields for this chatbot drive lead detection.
        lead_fields: list[dict] = []
        if chatbot is not None and chatbot.lead_collection_enabled:
            lead_fields = [
                {
                    "field_name": lf.field_name,
                    "is_required": bool(lf.is_required),
                }
                for lf in db.query(chatbot_tables.ChatbotLeadFields)
                .filter(chatbot_tables.ChatbotLeadFields.chatbot_id == chatbot.id)
                .order_by(chatbot_tables.ChatbotLeadFields.created_at.asc())
                .all()
            ]

        messages = (
            db.query(chatbot_tables.ChatbotMessages)
            .filter(chatbot_tables.ChatbotMessages.conversation_id == conversation.id)
            .order_by(chatbot_tables.ChatbotMessages.created_at.asc())
            .all()
        )
        transcript = chatbot_lead_service.build_transcript(messages)

        detection = await asyncio.to_thread(
            chatbot_lead_service.extract_lead_details,
            transcript,
            lead_fields,
            messages=messages,
        )
        lead_created = bool(detection.get("lead_created"))
        captured_fields = detection.get("captured_fields") or {}

        conversation.ended_at = datetime.now(timezone.utc)
        conversation.lead_created = lead_created

        lead_record = None
        if lead_created and chatbot is not None:
            ai_summary = ""
            if transcript.strip():
                ai_summary = await asyncio.to_thread(
                    chatbot_lead_service.generate_lead_summary_en, transcript
                )

            lead_record = (
                db.query(chatbot_tables.ChatbotLeads)
                .filter(chatbot_tables.ChatbotLeads.conversation_id == conversation.id)
                .first()
            )
            if lead_record is None:
                lead_record = chatbot_tables.ChatbotLeads(
                    chatbot_id=chatbot.id,
                    conversation_id=conversation.id,
                    ai_summary=ai_summary or None,
                    transcript=transcript or None,
                    status="new",
                )
                db.add(lead_record)
            else:
                lead_record.ai_summary = ai_summary or lead_record.ai_summary
                lead_record.transcript = transcript or lead_record.transcript

        db.commit()
        db.refresh(conversation)
        if lead_record is not None:
            db.refresh(lead_record)

        # Notify the company of the new lead via SendGrid (best-effort: a failure
        # here must not fail the close, which is already committed).
        if (
            lead_record is not None
            and chatbot is not None
            and chatbot.lead_recipient_email
            and SENDGRID_CHATBOT_LEAD_TEMPLATE_ID
        ):
            try:
                dynamic_data = {
                    "fields": chatbot_lead_service.build_lead_email_fields(
                        conversation.visitor_email, captured_fields
                    ),
                    "created_at": (
                        conversation.ended_at.strftime("%Y-%m-%d %H:%M")
                        if conversation.ended_at
                        else ""
                    ),
                    "website": conversation.website_url or "",
                    "ai_summary": lead_record.ai_summary or "",
                    "transcript": lead_record.transcript or "",
                    "conversation_id": str(conversation.uuid),
                }
                await send_template_email(
                    chatbot.lead_recipient_email,
                    SENDGRID_CHATBOT_LEAD_TEMPLATE_ID,
                    dynamic_data,
                )
                lead_record.email_sent = True
                db.commit()
                db.refresh(lead_record)
            except Exception as email_exc:
                db.rollback()
                logger.error(f"Failed to send chatbot lead email: {email_exc}")

        return chatbot_schema.ChatbotConversationCloseResponse(
            success=True,
            message="Conversation closed successfully",
            data=chatbot_schema.ChatbotConversationCloseData(
                conversation_uuid=conversation.uuid,
                ended_at=conversation.ended_at,
                lead_created=lead_created,
                captured_fields=captured_fields,
                lead=(
                    chatbot_schema.ChatbotLeadItem.model_validate(lead_record)
                    if lead_record is not None
                    else None
                ),
            ),
        )
    except HTTPException as exc:
        db.rollback()
        return error.InternalServerError(message=str(exc.detail))
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to close chatbot conversation: {exc}")
        return error.InternalServerError(message="Failed to close chatbot conversation")
            