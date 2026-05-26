from __future__ import annotations

import logging

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.chat.schema import (
    ChatAgentConfigInput,
    ChatRequest,
    ChatResponse,
    MessageInputItem,
    TextOutputItem,
)
from app.api.v1.negotiations.schema import AgentOutputResponse, AgentParamsRequest
from app.container import Container
from app.services.chat_service import ChatService, ChatServiceValidationError

router = APIRouter(prefix="/negotiations", tags=["negotiations"])

logger = logging.getLogger("app.api.v1.negotiations")

_FALLBACK_OUTPUT = "Brak odpowiedzi agenta."


def _extract_final_text(response: ChatResponse) -> str:
    text_outputs = [item.text for item in response.output if isinstance(item, TextOutputItem) and item.text]
    if not text_outputs:
        return _FALLBACK_OUTPUT
    return text_outputs[-1].strip() or _FALLBACK_OUTPUT


async def _run_agent(
    chat_service: ChatService,
    *,
    agent_name: str,
    params: str,
) -> AgentOutputResponse:
    chat_request = ChatRequest(
        input=[MessageInputItem(role="user", content=params)],
        agent_config=ChatAgentConfigInput(agent_name=agent_name),
    )
    try:
        response = await chat_service.process_chat(chat_request)
    except ChatServiceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Negotiations agent run failed agent=%s", agent_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Negotiations agent execution failed.",
        ) from exc
    finally:
        chat_service.close()

    if response.status != "completed":
        return AgentOutputResponse(output=_FALLBACK_OUTPUT)

    return AgentOutputResponse(output=_extract_final_text(response))


@router.post("/cities-for-item", response_model=AgentOutputResponse)
@inject
async def cities_for_item(
    payload: AgentParamsRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> AgentOutputResponse:
    return await _run_agent(
        chat_service,
        agent_name="negotiations_cities",
        params=payload.params,
    )


@router.post("/items-for-city", response_model=AgentOutputResponse)
@inject
async def items_for_city(
    payload: AgentParamsRequest,
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> AgentOutputResponse:
    return await _run_agent(
        chat_service,
        agent_name="negotiations_items",
        params=payload.params,
    )
