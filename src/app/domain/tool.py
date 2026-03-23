from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


@dataclass(slots=True, frozen=True)
class FunctionToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    type: Literal["function"] = "function"


@dataclass(slots=True, frozen=True)
class WebSearchToolDefinition:
    type: Literal["web_search"] = "web_search"


ToolDefinition: TypeAlias = FunctionToolDefinition | WebSearchToolDefinition
ToolType: TypeAlias = Literal["sync", "async", "agent", "human"]
ToolResult: TypeAlias = dict[str, Any]
ToolHandler: TypeAlias = Callable[[dict[str, Any], Any | None], Awaitable[ToolResult]]


logger = logging.getLogger(__name__)


def tool_ok(output: Any) -> ToolResult:
    return {"ok": True, "output": output}


def tool_error(
    error: str,
    *,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
    retryable: bool = True,
) -> ToolResult:
    result: ToolResult = {
        "ok": False,
        "error": error,
        "retryable": retryable,
    }
    if hint is not None:
        result["hint"] = hint
    if details is not None:
        result["details"] = details
    return result


def tool_internal_error(*, tool_name: str) -> ToolResult:
    return tool_error(
        "Tool execution failed.",
        hint="Spróbuj innego podejścia albo poinformuj użytkownika o problemie systemowym.",
        details={"tool": tool_name},
        retryable=False,
    )


@dataclass(slots=True, frozen=True)
class Tool:
    type: ToolType
    definition: FunctionToolDefinition
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, *, max_log_value_length: int = 4000) -> None:
        self._tools: dict[str, Tool] = {}
        self._max_log_value_length = max_log_value_length

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[FunctionToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def list_by_name(self, names: Iterable[str]) -> list[FunctionToolDefinition]:
        resolved: list[FunctionToolDefinition] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is not None:
                resolved.append(tool.definition)
        return resolved

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        signal: Any | None = None,
        *,
        call_id: str | None = None,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            logger.warning(
                "Tool request failed: name=%s call_id=%s error=%s",
                name,
                call_id or "-",
                "Tool not found",
            )
            return tool_error(
                f"Tool not found: {name}",
                hint="Użyj jednej z dostępnych definicji tooli przekazanych w kontekście.",
                details={"tool": name},
                retryable=False,
            )

        logger.info(
            "Tool request: name=%s call_id=%s payload=%s",
            name,
            call_id or "-",
            self._serialize_log_value(args),
        )

        try:
            result = await tool.handler(args, signal)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Tool execution failed: name=%s call_id=%s payload=%s",
                name,
                call_id or "-",
                self._serialize_log_value(args),
            )
            logger.debug(
                "Tool failure details: name=%s call_id=%s error=%s",
                name,
                call_id or "-",
                str(exc) or exc.__class__.__name__,
            )
            return tool_internal_error(tool_name=name)

        logger.info(
            "Tool response: name=%s call_id=%s result=%s",
            name,
            call_id or "-",
            self._serialize_log_value(result),
        )
        return result

    def _serialize_log_value(self, value: Any) -> str:
        serialized = json.dumps(value, ensure_ascii=False, default=self._json_fallback, sort_keys=True)
        if len(serialized) <= self._max_log_value_length:
            return serialized

        truncated_length = len(serialized) - self._max_log_value_length
        return f"{serialized[:self._max_log_value_length]}... [truncated {truncated_length} chars]"

    @staticmethod
    def _json_fallback(value: Any) -> str:
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        return str(value)
