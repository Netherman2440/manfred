from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from app.events import (
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentStartedEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
)
from app.providers import ProviderFunctionCallOutputItem, ProviderTextOutputItem, ProviderUsage


def subscribe_event_logger(event_bus: EventBus) -> Callable[[], None]:
    logger = logging.getLogger("app.events")

    def handle(event: object) -> None:
        if isinstance(event, AgentStartedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s session_id=%s model=%s user_input=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.ctx.session_id,
                event.model,
                _truncate(event.user_input),
            )
            return

        if isinstance(event, TurnStartedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s turn_count=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.turn_count,
            )
            return

        if isinstance(event, GenerationCompletedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s model=%s tokens=%s content=%s tool_calls=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.model,
                _format_usage(event.usage),
                _truncate(_extract_text_output(event.output)),
                _serialize(_extract_tool_calls(event.output)),
            )
            return

        if isinstance(event, ToolCalledEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s call_id=%s tool=%s arguments=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.call_id,
                event.name,
                _serialize(event.arguments),
            )
            return

        if isinstance(event, ToolCompletedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s call_id=%s tool=%s duration_ms=%s output=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.call_id,
                event.name,
                event.duration_ms,
                _serialize(event.output),
            )
            return

        if isinstance(event, ToolFailedEvent):
            logger.warning(
                "event=%s trace_id=%s agent_id=%s call_id=%s tool=%s duration_ms=%s error=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.call_id,
                event.name,
                event.duration_ms,
                _truncate(event.error),
            )
            return

        if isinstance(event, TurnCompletedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s turn_count=%s tokens=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.turn_count,
                _format_usage(event.usage),
            )
            return

        if isinstance(event, AgentCompletedEvent):
            logger.info(
                "event=%s trace_id=%s agent_id=%s duration_ms=%s result=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                event.duration_ms,
                _truncate(event.result),
            )
            return

        if isinstance(event, AgentFailedEvent):
            logger.error(
                "event=%s trace_id=%s agent_id=%s error=%s",
                event.type,
                event.ctx.trace_id,
                event.ctx.agent_id,
                _truncate(event.error),
            )

    return event_bus.subscribe("any", handle)


def _extract_text_output(output: list[object]) -> str | None:
    text_parts = [item.text for item in output if isinstance(item, ProviderTextOutputItem) and item.text]
    if not text_parts:
        return None
    return "".join(text_parts)


def _extract_tool_calls(output: list[object]) -> list[str]:
    return [item.name for item in output if isinstance(item, ProviderFunctionCallOutputItem) and item.name]


def _format_usage(usage: ProviderUsage | None) -> str:
    if usage is None:
        return "-"
    return f"{usage.input_tokens}/{usage.output_tokens}/{usage.total_tokens}"


def _serialize(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)

    try:
        return _truncate(json.dumps(value, ensure_ascii=True, default=str), 240)
    except (TypeError, ValueError):
        return _truncate(str(value), 240)


def _truncate(value: str | None, limit: int = 240) -> str:
    if not value:
        return "-"
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
