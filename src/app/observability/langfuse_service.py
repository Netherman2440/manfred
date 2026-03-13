from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langfuse import Langfuse, propagate_attributes


class ObservationClient(Protocol):
    def update(self, **kwargs: Any) -> None: ...


class NoopObservationClient:
    def update(self, **kwargs: Any) -> None:
        return None


class LangfuseService:
    def __init__(
        self,
        public_key: str,
        secret_key: str,
        base_url: str,
        environment: str,
        release: str,
        enabled: bool,
    ) -> None:
        self._enabled = enabled and bool(public_key) and bool(secret_key)
        self._client = self._build_client(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=environment,
            release=release,
        )

    def start_request(
        self,
        *,
        thread_id: str,
        message: str,
        stream: bool,
    ) -> AbstractContextManager[ObservationClient]:
        if not self._enabled:
            return nullcontext(NoopObservationClient())

        normalized_thread_id = self._normalize_identifier(thread_id)
        return self._client.start_as_current_observation(
            name="chat.request",
            as_type="chain",
            input={
                "message": message,
                "thread_id": normalized_thread_id,
                "stream": stream,
            },
            metadata={
                "thread_id": normalized_thread_id,
                "stream": str(stream).lower(),
            },
        )

    def start_generation(
        self,
        *,
        thread_id: str,
        model_name: str,
        messages: list[BaseMessage],
    ) -> AbstractContextManager[ObservationClient]:
        if not self._enabled:
            return nullcontext(NoopObservationClient())

        normalized_thread_id = self._normalize_identifier(thread_id)
        return self._client.start_as_current_observation(
            name="chat.generation",
            as_type="generation",
            model=model_name,
            input=self._serialize_messages(messages),
            metadata={"thread_id": normalized_thread_id},
        )

    def propagate_thread_context(self, *, thread_id: str, trace_name: str) -> AbstractContextManager[None]:
        if not self._enabled:
            return nullcontext(None)

        normalized_thread_id = self._normalize_identifier(thread_id)
        return propagate_attributes(
            session_id=normalized_thread_id,
            trace_name=trace_name,
            metadata={"thread_id": normalized_thread_id},
        )

    def flush(self) -> None:
        if self._enabled:
            self._client.flush()

    def shutdown(self) -> None:
        if self._enabled:
            self._client.shutdown()

    def get_model_name(self, llm: BaseChatModel, default: str = "unknown") -> str:
        model_name = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        if isinstance(model_name, str) and model_name:
            return model_name
        return default

    def _build_client(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        environment: str,
        release: str,
    ) -> Langfuse:
        return Langfuse(
            public_key=public_key or None,
            secret_key=secret_key or None,
            host=base_url,
            environment=environment,
            release=release,
            tracing_enabled=self._enabled,
        )

    def _normalize_identifier(self, value: str) -> str:
        ascii_value = value.encode("ascii", errors="ignore").decode("ascii").strip()
        if not ascii_value:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        if len(ascii_value) <= 200:
            return ascii_value

        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        prefix = ascii_value[: 200 - len(digest) - 1]
        return f"{prefix}-{digest}"

    def _serialize_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        return [
            {
                "type": message.type,
                "content": self._serialize_content(message.content),
            }
            for message in messages
        ]

    def _serialize_content(self, content: Any) -> Any:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return [self._serialize_content(item) for item in content]
        if isinstance(content, dict):
            return {key: self._serialize_content(value) for key, value in content.items()}
        return str(content)
