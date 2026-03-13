from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.api.v1.chat.schema import ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


def _get_graph(request: Request):
    return request.app.container.graph()


def _get_langfuse_service(request: Request):
    return request.app.container.langfuse_service()


def _build_config(session_id: str) -> RunnableConfig:
    return {"configurable": {"session_id": session_id}}


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
    langfuse_service = _get_langfuse_service(request)

    try:
        with langfuse_service.propagate_session_context(
            session_id=payload.session_id,
            trace_name="chat.sync",
        ):
            with langfuse_service.start_request(
                session_id=payload.session_id,
                message=payload.message,
                stream=False,
            ) as observation:
                try:
                    result = await graph.ainvoke(
                        {"messages": [HumanMessage(content=payload.message)]},
                        config=_build_config(payload.session_id),
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
        with langfuse_service.propagate_session_context(
            session_id=payload.session_id,
            trace_name="chat.stream",
        ):
            with langfuse_service.start_request(
                session_id=payload.session_id,
                message=payload.message,
                stream=True,
            ) as observation:
                try:
                    async for chunk, _metadata in graph.astream(
                        {"messages": [HumanMessage(content=payload.message)]},
                        config=_build_config(payload.session_id),
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
async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    graph = _get_graph(request)
    langfuse_service = _get_langfuse_service(request)
    return StreamingResponse(
        _stream_response(graph, langfuse_service, payload),
        media_type="text/plain; charset=utf-8",
    )
