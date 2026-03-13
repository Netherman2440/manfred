from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.chat.state import GraphState
from app.observability.langfuse_service import LangfuseService


class ChatNode:
    def __init__(
        self,
        llm: BaseChatModel,
        tools: list,
        langfuse_service: LangfuseService,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._langfuse_service = langfuse_service

    async def __call__(self, state: GraphState, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
        messages = state["messages"]
        session_id = self._get_session_id(config)
        model_name = self._langfuse_service.get_model_name(self._llm)

        with self._langfuse_service.start_generation(
            session_id=session_id,
            model_name=model_name,
            messages=messages,
        ) as generation:
            try:
                response = await self._llm.bind_tools(self._tools).ainvoke(messages)
            except Exception as exc:
                generation.update(level="ERROR", status_message=str(exc))
                raise

            generation.update(
                output=self._serialize_message(response),
                usage_details=self._get_usage_details(response),
            )
        return {"messages": [response]}

    def _get_session_id(self, config: RunnableConfig) -> str:
        configurable = config.get("configurable", {})
        if not isinstance(configurable, dict):
            return "unknown_session"

        session_id = configurable.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id

        return "unknown_session"

    def _get_usage_details(self, message: AIMessage) -> dict[str, Any] | None:
        usage_details = getattr(message, "usage_metadata", None)
        if isinstance(usage_details, dict):
            return usage_details
        return None

    def _serialize_message(self, message: BaseMessage) -> dict[str, Any]:
        return {
            "type": message.type,
            "content": self._serialize_content(message.content),
        }

    def _serialize_content(self, content: Any) -> Any:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return [self._serialize_content(item) for item in content]
        if isinstance(content, dict):
            return {key: self._serialize_content(value) for key, value in content.items()}
        return str(content)
