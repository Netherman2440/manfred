from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import Settings
from app.domain import Item, ItemType
from app.services.observability.base import ObservabilityService


logger = logging.getLogger(__name__)


class LangfuseObservabilityService(ObservabilityService):
    def __init__(
        self,
        *,
        client: Any,
        propagate_attributes: Any,
        environment: str,
        app_name: str,
    ) -> None:
        self._client = client
        self._propagate_attributes = propagate_attributes
        self._environment = environment
        self._app_name = app_name

    @contextmanager
    def start_chat_turn(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> Iterator[Any]:
        with self._propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            trace_name="chat.session",
            metadata={
                "agent_id": agent_id,
                "app_name": self._app_name,
                "environment": self._environment,
                "attachments": attachments or [],
            },
        ):
            with self._client.start_as_current_observation(
                name="chat.turn",
                as_type="span",
                trace_context={"trace_id": trace_id},
                input={"message": message, "attachments": attachments or []},
                metadata={
                    "agent_id": agent_id,
                    "app_name": self._app_name,
                    "environment": self._environment,
                    "attachments": attachments or [],
                },
            ):
                yield

    def start_generation(
        self,
        *,
        model: str,
        input_payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self._client.start_as_current_observation(
            name="llm.generate",
            as_type="generation",
            model=model,
            input=input_payload,
            metadata=metadata,
        )

    def start_tool_execution(
        self,
        *,
        name: str,
        call_id: str,
        input_payload: dict[str, Any],
    ) -> Any:
        return self._client.start_as_current_observation(
            name=name,
            as_type="tool",
            input=input_payload,
            metadata={"call_id": call_id},
        )

    def update_current_span(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        self._client.update_current_span(
            output=output,
            metadata=metadata,
            level=level,
            status_message=status_message,
        )

    def update_current_generation(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        self._client.update_current_generation(
            output=output,
            metadata=metadata,
            level=level,
            status_message=status_message,
        )

    def record_item(self, item: Item) -> None:
        event_name, input_payload, output_payload = self._serialize_item_event(item)
        self._client.create_event(
            name=event_name,
            input=input_payload,
            output=output_payload,
            metadata={
                "item_id": item.id,
                "session_id": item.session_id,
                "agent_id": item.agent_id,
                "sequence": item.sequence,
                "type": item.type.value,
                "role": item.role.value if item.role else None,
                "call_id": item.call_id,
                "name": item.name,
                "is_error": item.is_error,
            },
        )

    def record_error(
        self,
        *,
        name: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._client.create_event(
            name=name,
            output={"error": error},
            metadata=metadata,
            level="ERROR",
            status_message=error,
        )

    def flush(self) -> None:
        flush = getattr(self._client, "flush", None)
        if callable(flush):
            flush()

    def shutdown(self) -> None:
        shutdown = getattr(self._client, "shutdown", None)
        if callable(shutdown):
            shutdown()
            return
        self.flush()

    @staticmethod
    def _serialize_item_event(item: Item) -> tuple[str, Any | None, Any | None]:
        if item.type == ItemType.MESSAGE:
            payload = item.content
            if item.role and item.role.value == "assistant":
                return ("message.assistant", None, payload)
            return ("message.user", payload, None)

        if item.type == ItemType.FUNCTION_CALL:
            return (
                "tool.call",
                LangfuseObservabilityService._parse_json_value(item.arguments_json),
                None,
            )

        if item.type == ItemType.FUNCTION_CALL_OUTPUT:
            return ("tool.result", None, LangfuseObservabilityService._parse_json_value(item.output))

        return ("conversation.item", None, None)

    @staticmethod
    def _parse_json_value(value: str | None) -> Any:
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value


def build_observability_service(settings: Settings) -> ObservabilityService:
    if not settings.LANGFUSE_ENABLED:
        return ObservabilityService()

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse is enabled but credentials are missing. Falling back to no-op observability.")
        return ObservabilityService()

    try:
        from langfuse import Langfuse, propagate_attributes
    except ImportError:
        logger.warning("Langfuse SDK is not installed. Falling back to no-op observability.")
        return ObservabilityService()

    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.LANGFUSE_ENVIRONMENT,
    )
    return LangfuseObservabilityService(
        client=client,
        propagate_attributes=propagate_attributes,
        environment=settings.LANGFUSE_ENVIRONMENT,
        app_name=settings.PROJECT_NAME,
    )
