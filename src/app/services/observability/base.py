from __future__ import annotations

from contextlib import nullcontext
from uuid import uuid4
from typing import Any

from app.domain import Item


class ObservabilityService:
    def create_trace_id(self) -> str:
        return uuid4().hex

    def start_chat_turn(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> Any:
        return nullcontext()

    def start_generation(
        self,
        *,
        model: str,
        input_payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return nullcontext()

    def start_tool_execution(
        self,
        *,
        name: str,
        call_id: str,
        input_payload: dict[str, Any],
    ) -> Any:
        return nullcontext()

    def update_current_span(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        return None

    def update_current_generation(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        return None

    def record_item(self, item: Item) -> None:
        return None

    def record_error(
        self,
        *,
        name: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None
