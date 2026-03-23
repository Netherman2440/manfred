from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.v1.chat.schema import AttachmentPayload, AttachmentUploadResponse, ChatRequest, ChatResponse
from app.container import Container
from app.services.attachments import AttachmentService, AttachmentValidationError
from app.services.chat_service import ChatService
from app.services.chat_service import ChatValidationError
from app.services.conversation_context import ConversationContextService


router = APIRouter(prefix="/chat", tags=["chat"])
ATTACHMENT_SOURCES = {"file_picker", "voice_recording", "paste", "drag_drop"}


@router.post("/attachments", response_model=AttachmentUploadResponse)
@inject
async def upload_attachments(
    request: Request,
    attachment_service: AttachmentService = Depends(Provide[Container.attachment_service]),
    conversation_context: ConversationContextService = Depends(Provide[Container.conversation_context_service]),
) -> AttachmentUploadResponse:
    form = await request.form()
    session_id = form.get("sessionId")
    source = form.get("source")
    uploads = _get_uploads_from_form(form)

    if source is not None and source not in ATTACHMENT_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source must be one of: file_picker, voice_recording, paste, drag_drop",
        )
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one file must be uploaded.",
        )

    user = conversation_context.ensure_default_user()
    session = conversation_context.load_or_create_session(session_id, user)

    try:
        attachments = await attachment_service.ingest_uploads(
            session_id=session.id,
            uploads=uploads,
            source=source,
        )
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AttachmentUploadResponse(
        sessionId=session.id,
        attachments=[AttachmentPayload.from_domain(attachment) for attachment in attachments],
    )


@router.post("/completions", response_model=ChatResponse)
@inject
async def chat(
    payload: ChatRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    try:
        response = await chat_service.process_chat(payload.to_domain())
    except ChatValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ChatResponse(
        userId=response.user_id,
        sessionId=response.session_id,
        agentId=response.agent_id,
        model=response.model,
        status=response.status,
        output=response.output,
        attachments=[AttachmentPayload.from_domain(attachment) for attachment in response.attachments],
        error=response.error,
    )


def _get_uploads_from_form(form: object) -> list[StarletteUploadFile]:
    getlist = getattr(form, "getlist", None)
    if not callable(getlist):
        return []

    candidates = list(getlist("files"))
    if not candidates:
        candidates = list(getlist("files[]"))

    return [candidate for candidate in candidates if isinstance(candidate, StarletteUploadFile)]
