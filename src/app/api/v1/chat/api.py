from dependency_injector.wiring import Provide, inject
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.v1.chat.schema import ChatRequest, ChatResponse, ChatStreamSessionEvent, DeliverRequest
from app.container import Container
from app.providers import ProviderStreamEvent, serialize_provider_stream_event
from app.services.chat_service import ChatService, ChatServiceNotFoundError, ChatServiceValidationError


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatResponse)
@inject
async def chat(
    payload: ChatRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse | StreamingResponse:
    if payload.stream:
        async def stream() -> object:
            try:
                async for event in chat_service.process_chat_stream(payload):
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
        return await chat_service.process_chat(payload)
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
