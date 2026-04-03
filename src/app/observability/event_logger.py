from __future__ import annotations

import json
import logging
import re
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
            _log_event(
                logger,
                logging.INFO,
                event,
                content=event.user_input,
                model=event.model,
            )
            return

        if isinstance(event, TurnStartedEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=f"Turn {event.turn_count} started.",
                turn=event.turn_count,
            )
            return

        if isinstance(event, GenerationCompletedEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=_extract_text_output(event.output),
                usage=event.usage,
                model=event.model,
                tool_calls=_extract_tool_calls(event.output),
                duration_ms=event.duration_ms,
            )
            return

        if isinstance(event, ToolCalledEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=f"{event.name} called.",
                tool=event.name,
                tool_arguments=event.arguments,
            )
            return

        if isinstance(event, ToolCompletedEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=_extract_tool_output_text(event.output) or f"{event.name} completed.",
                tool=event.name,
                tool_arguments=event.arguments,
                tool_result=event.output,
                duration_ms=event.duration_ms,
            )
            return

        if isinstance(event, ToolFailedEvent):
            _log_event(
                logger,
                logging.WARNING,
                event,
                content=event.error,
                tool=event.name,
                tool_arguments=event.arguments,
                duration_ms=event.duration_ms,
            )
            return

        if isinstance(event, TurnCompletedEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=f"Turn {event.turn_count} completed.",
                usage=event.usage,
                turn=event.turn_count,
            )
            return

        if isinstance(event, AgentCompletedEvent):
            _log_event(
                logger,
                logging.INFO,
                event,
                content=event.result,
                usage=event.usage,
                duration_ms=event.duration_ms,
            )
            return

        if isinstance(event, AgentFailedEvent):
            _log_event(
                logger,
                logging.ERROR,
                event,
                content=event.error,
            )

    return event_bus.subscribe("any", handle)


def _extract_text_output(output: list[object]) -> str | None:
    text_parts = [item.text for item in output if isinstance(item, ProviderTextOutputItem) and item.text]
    if not text_parts:
        return None
    return "".join(text_parts)


def _extract_tool_calls(output: list[object]) -> list[str]:
    return [item.name for item in output if isinstance(item, ProviderFunctionCallOutputItem) and item.name]


def _extract_tool_output_text(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None

    value = output.get("output")
    if isinstance(value, str) and value:
        return value
    return None


def _log_event(
    logger: logging.Logger,
    level: int,
    event: object,
    *,
    content: str | None,
    usage: ProviderUsage | None = None,
    **fields: Any,
) -> None:
    payload = [
        f"event={_format_field_value(getattr(event, 'type', 'unknown'))}",
        f"agent={_format_field_value(_extract_agent_name(event))}",
        f"content={_format_content(content)}",
        *_format_usage_fields(usage, overrides=fields),
    ]
    payload.extend(_format_extra_fields(fields))
    logger.log(level, " ".join(payload))


def _extract_agent_name(event: object) -> str | None:
    ctx = getattr(event, "ctx", None)
    if ctx is not None:
        agent_name = getattr(ctx, "agent_name", None)
        if isinstance(agent_name, str) and agent_name:
            return agent_name

    agent_name = getattr(event, "agent_name", None)
    if isinstance(agent_name, str) and agent_name:
        return agent_name
    return None


def _format_usage_fields(usage: ProviderUsage | None, *, overrides: dict[str, Any]) -> list[str]:
    input_tokens = overrides.pop("input_tokens", usage.input_tokens if usage is not None else None)
    output_tokens = overrides.pop("output_tokens", usage.output_tokens if usage is not None else None)
    total_tokens = overrides.pop("total_tokens", usage.total_tokens if usage is not None else None)
    cached_tokens = overrides.pop("cached_tokens", usage.cached_tokens if usage is not None else None)

    if all(value is None for value in (input_tokens, output_tokens, total_tokens, cached_tokens)):
        return []

    return [
        f"input_tokens={_format_field_value(input_tokens)}",
        f"output_tokens={_format_field_value(output_tokens)}",
        f"total_tokens={_format_field_value(total_tokens)}",
        f"cached_tokens={_format_field_value(cached_tokens)}",
    ]


def _format_extra_fields(fields: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if key == "tool_calls" and isinstance(value, list) and not value:
            continue
        parts.append(f"{key}={_format_field_value(value)}")
    return parts


def _format_content(content: str | None) -> str:
    if not content:
        return "-"
    return _format_field_value(_truncate(content, 400))


_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")


def _format_field_value(value: Any) -> str:
    if value is None:
        return "-"
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, str):
        truncated = _truncate(value, 400)
        if _SAFE_VALUE_RE.match(truncated):
            return truncated
        return json.dumps(truncated, ensure_ascii=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _serialize(value)


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
