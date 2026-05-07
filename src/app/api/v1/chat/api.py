from dependency_injector.wiring import Provide, inject
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.datastructures import FormData, UploadFile

from app.api.v1.chat.schema import (
    ChatEditRequest,
    ChatQueueRequest,
    ChatQueueResponse,
    ChatRequest,
    ChatResponse,
    ChatStreamSessionEvent,
    DeliverRequest,
    MessageInputItem,
)
from app.container import Container
from app.providers import ProviderStreamEvent, serialize_provider_stream_event
from app.services.chat_attachments import IncomingAttachment
from app.services.chat_service import ChatService, ChatServiceNotFoundError, ChatServiceValidationError


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatResponse)
@inject
async def chat(
    request: Request,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse | StreamingResponse:
    try:
        payload, attachments = await _parse_chat_request(request)
    except ChatServiceValidationError as exc:
        chat_service.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.stream:
        async def stream() -> object:
            try:
                async for event in chat_service.process_chat_stream(payload, attachments=attachments):
                    yield _serialize_sse_event(event)
            finally:
                chat_service.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    try:
        return await chat_service.process_chat(payload, attachments=attachments)
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()


@router.patch("/sessions/{session_id}/items/{item_id}", response_model=ChatResponse)
@inject
async def edit_message(
    session_id: str,
    item_id: str,
    request: Request,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse | StreamingResponse:
    try:
        payload, attachments = await _parse_edit_request(request)
    except ChatServiceValidationError as exc:
        chat_service.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.stream:
        async def stream() -> object:
            try:
                async for event in chat_service.process_edit_stream(
                    session_id,
                    item_id,
                    payload,
                    attachments=attachments,
                ):
                    yield _serialize_sse_event(event)
            finally:
                chat_service.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    try:
        return await chat_service.process_edit(
            session_id,
            item_id,
            payload,
            attachments=attachments,
        )
    except ChatServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()


@router.post("/sessions/{session_id}/queue", response_model=ChatQueueResponse)
@inject
async def queue_message(
    session_id: str,
    request: Request,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatQueueResponse:
    try:
        payload, attachments = await _parse_queue_request(request)
    except ChatServiceValidationError as exc:
        chat_service.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        return await chat_service.process_queue(
            session_id,
            payload,
            attachments=attachments,
        )
    except ChatServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()


@router.post("/agents/{agent_id}/deliver", response_model=ChatResponse)
@inject
async def deliver(
    agent_id: str,
    payload: DeliverRequest,
    include_tool_result: bool = False,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    try:
        return await chat_service.process_delivery(
            agent_id,
            payload,
            include_tool_result=include_tool_result,
        )
    except ChatServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()


@router.post("/sessions/{session_id}/cancel", response_model=ChatResponse)
@inject
async def cancel(
    session_id: str,
    include_tool_result: bool = False,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    try:
        return await chat_service.process_cancel(
            session_id,
            include_tool_result=include_tool_result,
        )
    except ChatServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()


def _serialize_sse_event(event: ProviderStreamEvent | ChatStreamSessionEvent) -> str:
    if isinstance(event, ChatStreamSessionEvent):
        payload = json.dumps(
            {
                "type": event.type,
                "session_id": event.session_id,
                "agent_id": event.agent_id,
            },
            ensure_ascii=True,
        )
        return f"event: {event.type}\ndata: {payload}\n\n"

    payload = json.dumps(serialize_provider_stream_event(event), ensure_ascii=True)
    return f"event: {event.type}\ndata: {payload}\n\n"


async def _parse_chat_request(request: Request) -> tuple[ChatRequest, list[IncomingAttachment]]:
    if _is_multipart_request(request):
        form = await request.form()
        attachments = await _parse_form_attachments(form)
        return (
            ChatRequest(
                input=[MessageInputItem(role="user", content=_require_form_string(form, "message"))],
                session_id=_optional_form_string(form, "session_id"),
                stream=_parse_bool(_optional_form_string(form, "stream")),
                include_tool_result=_parse_bool(_optional_form_string(form, "include_tool_result")),
            ),
            attachments,
        )

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ChatServiceValidationError(f"Invalid JSON body: {exc}") from exc
    return ChatRequest.model_validate(body), []


async def _parse_edit_request(request: Request) -> tuple[ChatEditRequest, list[IncomingAttachment]]:
    if _is_multipart_request(request):
        form = await request.form()
        return (
            ChatEditRequest(
                message=_require_form_string(form, "message"),
                stream=_parse_bool(_optional_form_string(form, "stream")),
                retain_attachment_ids=_list_form_strings(form, "retain_attachment_ids"),
            ),
            await _parse_form_attachments(form),
        )

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ChatServiceValidationError(f"Invalid JSON body: {exc}") from exc
    return ChatEditRequest.model_validate(body), []


async def _parse_queue_request(request: Request) -> tuple[ChatQueueRequest, list[IncomingAttachment]]:
    if _is_multipart_request(request):
        form = await request.form()
        return (
            ChatQueueRequest(message=_require_form_string(form, "message")),
            await _parse_form_attachments(form),
        )

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ChatServiceValidationError(f"Invalid JSON body: {exc}") from exc
    return ChatQueueRequest.model_validate(body), []


def _is_multipart_request(request: Request) -> bool:
    content_type = request.headers.get("content-type", "")
    return content_type.startswith("multipart/form-data")


async def _parse_form_attachments(form: FormData) -> list[IncomingAttachment]:
    uploads = [
        value
        for key in ("attachments", "attachments[]")
        for value in form.getlist(key)
        if isinstance(value, UploadFile)
    ]
    attachments: list[IncomingAttachment] = []
    for upload in uploads:
        content = await upload.read()
        attachments.append(
            IncomingAttachment(
                file_name=upload.filename or "attachment",
                media_type=upload.content_type or "application/octet-stream",
                content=content,
            )
        )
    return attachments


def _optional_form_string(form: FormData, key: str) -> str | None:
    value = form.get(key)
    if value is None:
        return None
    if isinstance(value, UploadFile):
        raise ChatServiceValidationError(f"Expected text field for '{key}'.")
    text = str(value).strip()
    return text or None


def _require_form_string(form: FormData, key: str) -> str:
    value = _optional_form_string(form, key)
    if value is None:
        raise ChatServiceValidationError(f"Missing required field: {key}")
    return value


def _list_form_strings(form: FormData, key: str) -> list[str]:
    values = form.getlist(key)
    alias_values = form.getlist(f"{key}[]")
    resolved: list[str] = []
    for value in [*values, *alias_values]:
        if isinstance(value, UploadFile):
            raise ChatServiceValidationError(f"Expected text values for '{key}'.")
        text = str(value).strip()
        if text:
            resolved.append(text)
    return resolved


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}
