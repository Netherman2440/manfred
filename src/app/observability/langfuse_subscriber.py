from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from typing import Any

from app.config import Settings
from app.events import (
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentStartedEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
)
from app.providers import (
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderTextOutputItem,
    ProviderUsage,
)

logger = logging.getLogger("app.observability.langfuse")


class LangfuseSubscriber:
    def __init__(self, *, client: Any, propagate_attributes_fn: Callable[..., Any] | None = None) -> None:
        self.client = client
        self.propagate_attributes_fn = propagate_attributes_fn
        self._agent_observations: dict[str, Any] = {}
        self._agent_observation_ids: dict[str, str] = {}
        self._trace_attributes: dict[str, dict[str, str | None]] = {}

    def subscribe(self, event_bus: EventBus) -> Callable[[], None]:
        unsubscribes = [
            event_bus.subscribe("agent.started", self._handle_agent_started),
            event_bus.subscribe("agent.completed", self._handle_agent_completed),
            event_bus.subscribe("agent.failed", self._handle_agent_failed),
            event_bus.subscribe("generation.completed", self._handle_generation_completed),
            event_bus.subscribe("tool.completed", self._handle_tool_completed),
            event_bus.subscribe("tool.failed", self._handle_tool_failed),
        ]

        def unsubscribe() -> None:
            for stop in unsubscribes:
                stop()

        return unsubscribe

    def flush(self) -> None:
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            flush()

    def shutdown(self) -> None:
        self.flush()
        shutdown = getattr(self.client, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _handle_agent_started(self, event: AgentStartedEvent) -> None:
        trace_input = event.user_input or event.task
        trace_name = None
        if event.ctx.depth == 0:
            trace_name = event.agent_name or event.ctx.agent_name or "agent"
        trace_attributes = {
            "user_id": event.user_id,
            "session_id": event.ctx.session_id,
            "trace_name": trace_name,
        }
        self._trace_attributes[event.ctx.agent_id] = trace_attributes

        with self._propagate_trace_attributes(event.ctx.agent_id):
            observation = self.client.start_observation(
                trace_context=self._build_agent_trace_context(event),
                name=event.agent_name or event.ctx.agent_name or "agent",
                as_type="agent",
                input=trace_input,
                metadata={
                    "agent_id": event.ctx.agent_id,
                    "session_id": event.ctx.session_id,
                    "depth": event.ctx.depth,
                    "model": event.model,
                    "user_id": event.user_id,
                },
            )
        if event.ctx.depth == 0:
            observation.set_trace_io(input=trace_input)
        self._agent_observations[event.ctx.agent_id] = observation

        observation_id = _extract_observation_id(observation)
        if observation_id:
            self._agent_observation_ids[event.ctx.agent_id] = observation_id

    def _handle_agent_completed(self, event: AgentCompletedEvent) -> None:
        observation = self._agent_observations.pop(event.ctx.agent_id, None)
        self._agent_observation_ids.pop(event.ctx.agent_id, None)
        self._trace_attributes.pop(event.ctx.agent_id, None)
        if observation is None:
            return

        observation.update(
            output=event.result or "Completed",
            metadata={"usage": _usage_to_dict(event.usage)},
        )
        if event.ctx.depth == 0:
            observation.set_trace_io(output=event.result or "Completed")
        observation.end()

    def _handle_agent_failed(self, event: AgentFailedEvent) -> None:
        observation = self._agent_observations.pop(event.ctx.agent_id, None)
        self._agent_observation_ids.pop(event.ctx.agent_id, None)
        self._trace_attributes.pop(event.ctx.agent_id, None)
        if observation is None:
            return

        observation.update(level="ERROR", status_message=event.error)
        if event.ctx.depth == 0:
            observation.set_trace_io(output=event.error)
        observation.end()

    def _handle_generation_completed(self, event: GenerationCompletedEvent) -> None:
        with self._propagate_trace_attributes(event.ctx.agent_id):
            observation = self.client.start_observation(
                trace_context=self._build_trace_context(event.ctx.trace_id, event.ctx.agent_id),
                name="generation",
                as_type="generation",
                input=_extract_generation_input(event.input),
                output=_extract_generation_output(event.output),
                metadata={
                    "agent_id": event.ctx.agent_id,
                    "session_id": event.ctx.session_id,
                    "instructions": event.instructions,
                    "duration_ms": event.duration_ms,
                    "tool_calls": _extract_tool_calls(event.output),
                },
                completion_start_time=event.start_time,
                model=event.model,
                usage_details=_usage_to_dict(event.usage),
            )
        observation.end()

    def _handle_tool_completed(self, event: ToolCompletedEvent) -> None:
        with self._propagate_trace_attributes(event.ctx.agent_id):
            observation = self.client.start_observation(
                trace_context=self._build_trace_context(event.ctx.trace_id, event.ctx.agent_id),
                name=event.name,
                as_type="tool",
                input=_serialize_for_langfuse(event.arguments),
                output=_serialize_for_langfuse(event.output),
                metadata={
                    "agent_id": event.ctx.agent_id,
                    "session_id": event.ctx.session_id,
                    "duration_ms": event.duration_ms,
                    "call_id": event.call_id,
                },
            )
        observation.end()

    def _handle_tool_failed(self, event: ToolFailedEvent) -> None:
        with self._propagate_trace_attributes(event.ctx.agent_id):
            observation = self.client.start_observation(
                trace_context=self._build_trace_context(event.ctx.trace_id, event.ctx.agent_id),
                name=event.name,
                as_type="tool",
                input=_serialize_for_langfuse(event.arguments),
                metadata={
                    "agent_id": event.ctx.agent_id,
                    "session_id": event.ctx.session_id,
                    "duration_ms": event.duration_ms,
                    "call_id": event.call_id,
                },
            )
        observation.update(level="ERROR", status_message=event.error)
        observation.end()

    def _build_trace_context(self, trace_id: str, agent_id: str) -> dict[str, str]:
        trace_context = {"trace_id": trace_id}
        parent_observation_id = self._agent_observation_ids.get(agent_id)
        if parent_observation_id:
            trace_context["parent_span_id"] = parent_observation_id
        return trace_context

    def _build_agent_trace_context(self, event: AgentStartedEvent) -> dict[str, str]:
        trace_context = {"trace_id": event.ctx.trace_id}
        if event.ctx.parent_agent_id:
            parent_observation_id = self._agent_observation_ids.get(event.ctx.parent_agent_id)
            if parent_observation_id:
                trace_context["parent_span_id"] = parent_observation_id
        return trace_context

    def _propagate_trace_attributes(self, agent_id: str) -> Any:
        if self.propagate_attributes_fn is None:
            return nullcontext()

        attributes = self._trace_attributes.get(agent_id)
        if not attributes:
            return nullcontext()

        return self.propagate_attributes_fn(
            user_id=attributes.get("user_id"),
            session_id=attributes.get("session_id"),
            trace_name=attributes.get("trace_name"),
        )


def build_langfuse_subscriber(settings: Settings) -> LangfuseSubscriber | None:
    if not settings.LANGFUSE_ENABLED:
        return None

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.info("Langfuse is enabled but credentials are missing. Subscriber will stay disabled.")
        return None

    try:
        from langfuse import Langfuse, propagate_attributes
    except ImportError:
        logger.warning("Langfuse SDK is not installed. Subscriber will stay disabled.")
        return None

    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        base_url=settings.LANGFUSE_HOST,
        environment=settings.LANGFUSE_ENVIRONMENT,
    )
    return LangfuseSubscriber(
        client=client,
        propagate_attributes_fn=propagate_attributes,
    )


def _extract_observation_id(observation: Any) -> str | None:
    for attribute in ("id", "observation_id"):
        value = getattr(observation, attribute, None)
        if isinstance(value, str) and value:
            return value
    return None


def _usage_to_dict(usage: ProviderUsage | None) -> dict[str, int] | None:
    if usage is None:
        return None
    return {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.total_tokens,
        "cached": usage.cached_tokens,
    }


def _serialize_for_langfuse(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize_for_langfuse(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_for_langfuse(item) for key, item in value.items()}
    if isinstance(value, ProviderTextOutputItem):
        return {"type": value.type, "text": value.text}
    if isinstance(value, ProviderFunctionCallOutputItem):
        return {
            "type": value.type,
            "call_id": value.call_id,
            "name": value.name,
            "arguments": value.arguments,
        }
    return value


def _extract_generation_input(input_items: list[Any]) -> str | None:
    messages = [
        item.content
        for item in input_items
        if isinstance(item, ProviderMessageInputItem) and item.role == "user" and item.content
    ]
    if not messages:
        return None
    return messages[-1]


def _extract_generation_output(output_items: list[Any]) -> str | None:
    texts = [item.text for item in output_items if isinstance(item, ProviderTextOutputItem) and item.text]
    if not texts:
        return None
    return "".join(texts)


def _extract_tool_calls(output_items: list[Any]) -> list[str]:
    return [item.name for item in output_items if isinstance(item, ProviderFunctionCallOutputItem) and item.name]
