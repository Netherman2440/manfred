from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.v1.chat.schema import ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/competions", response_model=ChatResponse)
@inject
async def chat(
    payload: ChatRequest,
    #chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatResponse:
    pass

