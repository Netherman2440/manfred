from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.events import (
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentResumedEvent,
    AgentStartedEvent,
    AgentWaitingEvent,
    BaseEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
)
from app.providers import (
    ProviderFunctionCallOutputItem,
    ProviderTextOutputItem,
    ProviderUsage,
)

logger = logging.getLogger("app.observability.markdown_event_logger")


DEFAULT_FILENAME = "logs.md"
MAX_BLOCK_CHARS = 3000


WorkspaceResolver = Callable[[str], Path | None]


class MarkdownEventLogger:
    """Appends each event-bus event as a markdown block to {session_workspace}/logs.md.

    Useful for handing a full session transcript to a stronger reviewer model: each
    block is self-contained and copy-paste friendly. Workspaces are resolved per
    session_id via the injected resolver, and cached so repeat events don't hit the DB.
    """

    def __init__(
        self,
        *,
        workspace_resolver: WorkspaceResolver,
        filename: str = DEFAULT_FILENAME,
    ) -> None:
        self._workspace_resolver = workspace_resolver
        self._filename = filename
        self._workspace_cache: dict[str, Path | None] = {}
        self._cache_lock = threading.Lock()
        self._file_locks: dict[str, threading.Lock] = {}

    def subscribe(self, event_bus: EventBus) -> Callable[[], None]:
        event_types = (
            "agent.started",
            "generation.completed",
            "tool.completed",
            "tool.failed",
            "agent.waiting",
            "agent.resumed",
            "agent.completed",
            "agent.failed",
        )
        unsubscribes = [event_bus.subscribe(et, self._handle) for et in event_types]

        def unsubscribe() -> None:
            for stop in unsubscribes:
                stop()

        return unsubscribe

    def _handle(self, event: BaseEvent) -> None:
        try:
            session_id = getattr(event.ctx, "session_id", None)
            if not session_id:
                return
            workspace = self._resolve_workspace(session_id)
            if workspace is None:
                return
            block = self._format(event)
            if not block:
                return
            target = workspace / self._filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_for(target), target.open("a", encoding="utf-8") as fh:
                fh.write(block)
                fh.write("\n")
        except Exception:
            logger.exception("Markdown event logger failed for %s", getattr(event, "type", "unknown"))

    def _resolve_workspace(self, session_id: str) -> Path | None:
        with self._cache_lock:
            cached = self._workspace_cache.get(session_id)
            if cached is not None:
                return cached
        path = self._workspace_resolver(session_id)
        if path is None:
            # Session may not be committed yet — don't cache, retry next event.
            return None
        with self._cache_lock:
            self._workspace_cache[session_id] = path
        return path

    def _lock_for(self, path: Path) -> threading.Lock:
        key = str(path)
        with self._cache_lock:
            lock = self._file_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._file_locks[key] = lock
            return lock

    # ---- formatting ----

    def _format(self, event: BaseEvent) -> str | None:
        ts = self._format_timestamp(event)
        agent = self._agent_label(event)
        depth = getattr(event.ctx, "depth", 0) or 0
        prefix = "↳ " * depth

        if isinstance(event, AgentStartedEvent):
            lines = [
                f"## {ts} · {prefix}agent.started · {agent}",
                "",
                f"- model: `{event.model}`",
            ]
            if event.user_input:
                lines += ["- user input:", "", self._fenced(event.user_input, "text")]
            elif event.task:
                lines += ["- task:", "", self._fenced(event.task, "text")]
            return self._join(lines)

        if isinstance(event, GenerationCompletedEvent):
            text = _extract_text_output(event.output)
            tool_calls = _extract_tool_calls(event.output)
            lines = [
                f"## {ts} · {prefix}generation.completed · {agent} · {event.duration_ms}ms",
                "",
                f"- usage: {self._format_usage(event.usage)}",
                f"- model: `{event.model}`",
            ]
            if tool_calls:
                rendered = ", ".join(f"`{name}`" for name in tool_calls)
                lines.append(f"- tool calls: {rendered}")
            if text:
                lines += ["", "Assistant text:", "", self._fenced(text, "text")]
            return self._join(lines)

        if isinstance(event, ToolCompletedEvent):
            lines = [
                f"## {ts} · {prefix}tool.completed · `{event.name}` · {event.duration_ms}ms · {agent}",
                "",
                f"- call_id: `{event.call_id}`",
                "",
                "Arguments:",
                "",
                self._fenced(self._pretty_json(event.arguments), "json"),
                "",
                "Result:",
                "",
                self._fenced(self._pretty_json(event.output), "json"),
            ]
            return self._join(lines)

        if isinstance(event, ToolFailedEvent):
            lines = [
                f"## {ts} · {prefix}tool.failed · `{event.name}` · {event.duration_ms}ms · {agent}",
                "",
                f"- call_id: `{event.call_id}`",
                f"- error: {event.error}",
                "",
                "Arguments:",
                "",
                self._fenced(self._pretty_json(event.arguments), "json"),
            ]
            return self._join(lines)

        if isinstance(event, AgentCompletedEvent):
            lines = [
                f"## {ts} · {prefix}agent.completed · {agent} · {event.duration_ms}ms",
                "",
                f"- usage: {self._format_usage(event.usage)}",
            ]
            if event.result:
                lines += ["", "Result:", "", self._fenced(event.result, "text")]
            return self._join(lines)

        if isinstance(event, AgentWaitingEvent):
            descriptions = _extract_waiting_descriptions(event.waiting_for)
            lines = [f"## {ts} · {prefix}agent.waiting · {agent}"]
            if descriptions:
                lines += ["", "Waiting for:", "", self._fenced(descriptions, "text")]
            return self._join(lines)

        if isinstance(event, AgentResumedEvent):
            return self._join(
                [
                    f"## {ts} · {prefix}agent.resumed · {agent}",
                    "",
                    f"- call_id: `{event.call_id}`",
                ]
            )

        if isinstance(event, AgentFailedEvent):
            return self._join(
                [
                    f"## {ts} · {prefix}agent.failed · {agent}",
                    "",
                    f"- error: {event.error}",
                ]
            )

        return None

    @staticmethod
    def _format_timestamp(event: BaseEvent) -> str:
        ts = getattr(event.ctx, "timestamp", None)
        if ts is None:
            return "—"
        try:
            return ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
        except Exception:
            return str(ts)

    @staticmethod
    def _agent_label(event: BaseEvent) -> str:
        name = getattr(event.ctx, "agent_name", None)
        if isinstance(name, str) and name:
            return f"`{name}`"
        agent_id = getattr(event.ctx, "agent_id", None)
        return f"`{agent_id or 'agent'}`"

    @staticmethod
    def _format_usage(usage: ProviderUsage | None) -> str:
        if usage is None:
            return "—"
        return (
            f"in={usage.input_tokens} out={usage.output_tokens} total={usage.total_tokens} cached={usage.cached_tokens}"
        )

    @staticmethod
    def _pretty_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _fenced(text: str, language: str) -> str:
        truncated = _truncate(text, MAX_BLOCK_CHARS)
        # Avoid breaking the fence if the content contains a triple backtick.
        fence = "```"
        while fence in truncated:
            fence += "`"
        return f"{fence}{language}\n{truncated}\n{fence}"

    @staticmethod
    def _join(lines: list[str]) -> str:
        return "\n".join(lines) + "\n"


def _extract_text_output(output: list[object]) -> str | None:
    text_parts = [item.text for item in output if isinstance(item, ProviderTextOutputItem) and item.text]
    if not text_parts:
        return None
    return "".join(text_parts)


def _extract_tool_calls(output: list[object]) -> list[str]:
    return [item.name for item in output if isinstance(item, ProviderFunctionCallOutputItem) and item.name]


def _extract_waiting_descriptions(waiting_for: list[object]) -> str | None:
    descriptions: list[str] = []
    for entry in waiting_for:
        description = getattr(entry, "description", None)
        if isinstance(description, str) and description:
            descriptions.append(description)
    if not descriptions:
        return None
    return "\n".join(f"- {d}" for d in descriptions)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 50]}\n…<truncated {len(value) - (limit - 50)} chars>"
