from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.v1.chat.schema import (
    AgentStateResponse,
    AttachmentPayload,
    AttachmentUploadResponse,
    ChatRequest,
    ChatResponse,
    DeliverRequest,
    WaitingForPayload,
)
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
    http_response: Response,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    try:
        chat_response = await chat_service.process_chat(payload.to_domain())
    except ChatValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if chat_response.status == "waiting":
        http_response.status_code = status.HTTP_202_ACCEPTED

    return ChatResponse(
        userId=chat_response.user_id,
        sessionId=chat_response.session_id,
        agentId=chat_response.agent_id,
        model=chat_response.model,
        status=chat_response.status,
        output=chat_response.output,
        waitingFor=[WaitingForPayload.from_domain(wait) for wait in chat_response.waiting_for],
        attachments=[AttachmentPayload.from_domain(attachment) for attachment in chat_response.attachments],
        error=chat_response.error,
    )


@router.get("/agents/{agent_id}", response_model=AgentStateResponse)
@inject
async def get_agent(
    agent_id: str,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> AgentStateResponse:
    try:
        agent = chat_service.get_agent_state(agent_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return AgentStateResponse(
        agentId=agent.agent_id,
        sessionId=agent.session_id,
        rootAgentId=agent.root_agent_id,
        parentId=agent.parent_id,
        sourceCallId=agent.source_call_id,
        model=agent.model,
        status=agent.status,
        depth=agent.depth,
        turnCount=agent.turn_count,
        waitingFor=[WaitingForPayload.from_domain(wait) for wait in agent.waiting_for],
        result=agent.result,
        error=agent.error,
    )


@router.post("/agents/{agent_id}/deliver", response_model=AgentStateResponse)
@inject
async def deliver(
    agent_id: str,
    payload: DeliverRequest,
    http_response: Response,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> AgentStateResponse:
    try:
        agent = await chat_service.deliver_result(
            agent_id=agent_id,
            call_id=payload.call_id,
            output=payload.output,
            is_error=payload.is_error,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if agent.status == "waiting":
        http_response.status_code = status.HTTP_202_ACCEPTED

    return AgentStateResponse(
        agentId=agent.agent_id,
        sessionId=agent.session_id,
        rootAgentId=agent.root_agent_id,
        parentId=agent.parent_id,
        sourceCallId=agent.source_call_id,
        model=agent.model,
        status=agent.status,
        depth=agent.depth,
        turnCount=agent.turn_count,
        waitingFor=[WaitingForPayload.from_domain(wait) for wait in agent.waiting_for],
        result=agent.result,
        error=agent.error,
    )


def _get_uploads_from_form(form: object) -> list[StarletteUploadFile]:
    getlist = getattr(form, "getlist", None)
    if not callable(getlist):
        return []

    candidates = list(getlist("files"))
    if not candidates:
        candidates = list(getlist("files[]"))

    return [candidate for candidate in candidates if isinstance(candidate, StarletteUploadFile)]
