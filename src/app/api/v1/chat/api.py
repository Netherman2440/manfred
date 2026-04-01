from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.chat.schema import ChatRequest, ChatResponse
from app.container import Container
from app.services.chat_service import ChatService, ChatServiceValidationError


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatResponse)
@inject
async def chat(
    payload: ChatRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    try:
        if payload.stream:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Streaming is not implemented yet.",
            )

        return await chat_service.process_chat(payload)
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        chat_service.close()
