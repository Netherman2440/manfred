from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from app.api.v1.chat.schema import ChatRequest, ChatResponse
from app.container import Container
from app.services.chat_service import ChatService


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatResponse)
@inject
async def chat(
    payload: ChatRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    response = await chat_service.process_chat(payload.to_domain())
    return ChatResponse(
        userId=response.user_id,
        sessionId=response.session_id,
        agentId=response.agent_id,
        model=response.model,
        status=response.status,
        output=response.output,
        error=response.error,
    )
