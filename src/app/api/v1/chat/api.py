from collections.abc import AsyncIterator

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.api.v1.chat.schema import ChatRequest, ChatResponse
from app.infra.container import Container
from app.observability.langfuse_service import LangfuseService


router = APIRouter(prefix="/chat", tags=["chat"])


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
@inject
async def chat(
    payload: ChatRequest,
    graph: CompiledStateGraph = Depends(Provide[Container.graph]),
    langfuse_service: LangfuseService = Depends(Provide[Container.langfuse_service]),
) -> ChatResponse:
    try:
        with langfuse_service.propagate_thread_context(
            thread_id=payload.thread_id,
            trace_name="chat.sync",
        ):
            with langfuse_service.start_request(
                thread_id=payload.thread_id,
                message=payload.message,
                stream=False,
            ) as observation:
                try:
                    result = await graph.ainvoke(
                        {"messages": [HumanMessage(content=payload.message)]},
                        config=_build_config(payload.thread_id),
                    )
                except Exception as exc:
                    observation.update(level="ERROR", status_message=str(exc))
                    raise

                response_message = _extract_ai_text(result["messages"])
                observation.update(output={"message": response_message})
    finally:
        langfuse_service.flush()

    return ChatResponse(message=response_message)


async def _stream_response(graph, langfuse_service, payload: ChatRequest) -> AsyncIterator[str]:
    chunks: list[str] = []

    try:
        with langfuse_service.propagate_thread_context(
            thread_id=payload.thread_id,
            trace_name="chat.stream",
        ):
            with langfuse_service.start_request(
                thread_id=payload.thread_id,
                message=payload.message,
                stream=True,
            ) as observation:
                try:
                    async for chunk, _metadata in graph.astream(
                        {"messages": [HumanMessage(content=payload.message)]},
                        config=_build_config(payload.thread_id),
                        stream_mode="messages",
                    ):
                        if isinstance(chunk, AIMessageChunk):
                            text = chunk.text
                            if text:
                                chunks.append(text)
                                yield text
                except Exception as exc:
                    observation.update(level="ERROR", status_message=str(exc))
                    raise

                observation.update(output={"message": "".join(chunks)})
    finally:
        langfuse_service.flush()


@router.post("/stream")
@inject
async def stream_chat(
    payload: ChatRequest,
    graph: CompiledStateGraph = Depends(Provide[Container.graph]),
    langfuse_service: LangfuseService = Depends(Provide[Container.langfuse_service]),
) -> StreamingResponse:
    return StreamingResponse(
        _stream_response(graph, langfuse_service, payload),
        media_type="text/plain; charset=utf-8",
    )
