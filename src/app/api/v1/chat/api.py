from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.api.v1.chat.schema import ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


def _get_graph(request: Request):
    return request.app.container.graph()


def _build_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _extract_ai_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.text
            if content:
                return content
    return ""


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    graph = _get_graph(request)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=payload.message)]},
        config=_build_config(payload.thread_id),
    )
    return ChatResponse(message=_extract_ai_text(result["messages"]))


async def _stream_response(graph, payload: ChatRequest) -> AsyncIterator[str]:
    async for chunk, _metadata in graph.astream(
        {"messages": [HumanMessage(content=payload.message)]},
        config=_build_config(payload.thread_id),
        stream_mode="messages",
    ):
        if isinstance(chunk, AIMessageChunk):
            text = chunk.text
            if text:
                yield text


@router.post("/stream")
async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    graph = _get_graph(request)
    return StreamingResponse(
        _stream_response(graph, payload),
        media_type="text/plain; charset=utf-8",
    )
