from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from urllib import error, request

from app.domain.tool import FunctionToolDefinition
from app.providers.base import Provider
from app.providers.types import (
    ProviderDoneEvent,
    ProviderErrorEvent,
    ProviderFunctionCallDeltaEvent,
    ProviderFunctionCallDoneEvent,
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderTextDeltaEvent,
    ProviderTextDoneEvent,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.runtime.cancellation import CancellationRequestedError

if TYPE_CHECKING:
    from app.runtime.cancellation import CancellationSignal

_OPENROUTER_HTTP_TIMEOUT_SECONDS = 30.0


class OpenRouterProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class _FunctionCallState:
    index: int
    call_id: str = ""
    name: str = ""
    arguments_chunks: list[str] = field(default_factory=list)

    @property
    def arguments_text(self) -> str:
        return "".join(self.arguments_chunks)


@dataclass(slots=True)
class _StreamState:
    response_id: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    text_chunks: list[str] = field(default_factory=list)
    function_calls: dict[int, _FunctionCallState] = field(default_factory=dict)
    usage: ProviderUsage = field(default_factory=ProviderUsage)


class OpenRouterProvider(Provider):
    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def generate(self, request_data: ProviderRequest) -> ProviderResponse:
        if not self._api_key:
            raise OpenRouterProviderError("OPEN_ROUTER_API_KEY is not configured.")

        payload = {
            "model": request_data.model,
            "messages": self._build_messages(request_data),
        }
        if request_data.temperature is not None:
            payload["temperature"] = request_data.temperature

        tools = self._build_tools(request_data)
        if tools:
            payload["tools"] = tools

        signal = request_data.signal
        if signal is not None:
            signal.raise_if_cancelled()

        request_task = asyncio.create_task(asyncio.to_thread(self._post_json, payload))
        raw_response = await self._await_with_cancellation(
            request_task,
            signal=signal,
        )
        return self._parse_response(raw_response)

    async def stream(self, request_data: ProviderRequest) -> AsyncIterable[ProviderStreamEvent]:
        if not self._api_key:
            yield ProviderErrorEvent(error="OPEN_ROUTER_API_KEY is not configured.")
            return

        payload = {
            "model": request_data.model,
            "messages": self._build_messages(request_data),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request_data.temperature is not None:
            payload["temperature"] = request_data.temperature

        tools = self._build_tools(request_data)
        if tools:
            payload["tools"] = tools

        queue: asyncio.Queue[ProviderStreamEvent | object] = asyncio.Queue()
        finished = object()
        loop = asyncio.get_running_loop()
        signal = request_data.signal

        def produce() -> None:
            try:
                for event in self._stream_events_sync(payload, signal=signal):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # pragma: no cover - defensive fallback
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ProviderErrorEvent(error=str(exc) or "OpenRouter streaming failed."),
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, finished)

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()

        while True:
            item = await self._await_with_cancellation(
                asyncio.create_task(queue.get()),
                signal=signal,
                suppress_cancellation=True,
            )
            if item is None:
                return
            if item is finished:
                break
            yield cast(ProviderStreamEvent, item)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with request.urlopen(
                http_request,
                timeout=_OPENROUTER_HTTP_TIMEOUT_SECONDS,
            ) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise OpenRouterProviderError(
                f"OpenRouter request failed with status {exc.code}: {detail or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise OpenRouterProviderError(f"OpenRouter request failed: {exc.reason}") from exc

    def _stream_events_sync(
        self,
        payload: dict[str, Any],
        *,
        signal: CancellationSignal | None = None,
    ) -> Iterator[ProviderStreamEvent]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with request.urlopen(
                http_request,
                timeout=_OPENROUTER_HTTP_TIMEOUT_SECONDS,
            ) as response:  # noqa: S310
                lines = (raw_line.decode("utf-8", errors="ignore").rstrip("\r\n") for raw_line in response)
                yield from self._iter_stream_events_from_payloads(self._iter_sse_payloads(lines, signal=signal))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            yield ProviderErrorEvent(
                error=f"OpenRouter request failed with status {exc.code}: {detail or exc.reason}",
                code=str(exc.code),
            )
        except error.URLError as exc:
            yield ProviderErrorEvent(error=f"OpenRouter request failed: {exc.reason}")
        except Exception as exc:
            yield ProviderErrorEvent(error=str(exc) or "OpenRouter streaming failed.")

    @staticmethod
    def _iter_sse_payloads(
        lines: Iterable[str],
        *,
        signal: CancellationSignal | None = None,
    ) -> Iterator[str]:
        data_lines: list[str] = []
        for raw_line in lines:
            if signal is not None and signal.thread_event.is_set():
                break
            line = raw_line.strip()
            if not line:
                if data_lines:
                    payload = "\n".join(data_lines)
                    data_lines.clear()
                    if payload == "[DONE]":
                        break
                    yield payload
                continue

            if line.startswith(":"):
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            payload = "\n".join(data_lines)
            if payload != "[DONE]":
                yield payload

    @staticmethod
    async def _await_with_cancellation(
        task: asyncio.Task[Any],
        *,
        signal: CancellationSignal | None = None,
        suppress_cancellation: bool = False,
    ) -> Any:
        if signal is None:
            return await task

        signal.raise_if_cancelled()
        cancel_task = asyncio.create_task(signal.wait())
        done, pending = await asyncio.wait(
            {task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for pending_task in pending:
            pending_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        if cancel_task in done:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if suppress_cancellation:
                return None
            raise CancellationRequestedError("OpenRouter request cancelled.")

        return task.result()

    @staticmethod
    def _iter_stream_events_from_payloads(payloads: Iterable[str]) -> Iterator[ProviderStreamEvent]:
        state = _StreamState()
        for raw_payload in payloads:
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                yield ProviderErrorEvent(error="OpenRouter streaming payload was not valid JSON.")
                return

            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                yield ProviderErrorEvent(
                    error=str(error_payload.get("message") or "OpenRouter streaming failed."),
                    code=str(error_payload.get("code") or "") or None,
                )
                return

            OpenRouterProvider._accumulate_stream_state(state, payload)

            for event in OpenRouterProvider._delta_events_from_payload(state, payload):
                yield event

        for event in OpenRouterProvider._finalize_stream_state(state):
            yield event

    @staticmethod
    def _accumulate_stream_state(state: _StreamState, payload: dict[str, Any]) -> None:
        if state.response_id is None:
            response_id = str(payload.get("id") or "") or None
            state.response_id = response_id
        if state.model is None:
            model = str(payload.get("model") or "") or None
            state.model = model

        usage_payload = payload.get("usage")
        if isinstance(usage_payload, dict):
            state.usage = OpenRouterProvider._parse_usage(usage_payload)

        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue

            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason:
                state.finish_reason = finish_reason

            delta = choice.get("delta") or {}
            text = OpenRouterProvider._extract_text(delta.get("content"))
            if text:
                state.text_chunks.append(text)

            for tool_call in delta.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue

                index = OpenRouterProvider._coerce_index(tool_call.get("index"))
                function_state = state.function_calls.setdefault(index, _FunctionCallState(index=index))
                function_payload = tool_call.get("function") or {}

                call_id = str(tool_call.get("id") or "")
                if call_id:
                    function_state.call_id = call_id

                name = str(function_payload.get("name") or "")
                if name:
                    function_state.name = name

                arguments_delta = function_payload.get("arguments")
                if isinstance(arguments_delta, str) and arguments_delta:
                    function_state.arguments_chunks.append(arguments_delta)

    @staticmethod
    def _delta_events_from_payload(
        state: _StreamState,
        payload: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        events: list[ProviderStreamEvent] = []
        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue

            delta = choice.get("delta") or {}
            text = OpenRouterProvider._extract_text(delta.get("content"))
            if text:
                events.append(ProviderTextDeltaEvent(delta=text))

            for tool_call in delta.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue

                index = OpenRouterProvider._coerce_index(tool_call.get("index"))
                function_state = state.function_calls.get(index)
                function_payload = tool_call.get("function") or {}
                arguments_delta = function_payload.get("arguments")
                if function_state is not None and isinstance(arguments_delta, str) and arguments_delta:
                    events.append(
                        ProviderFunctionCallDeltaEvent(
                            call_id=function_state.call_id,
                            name=function_state.name,
                            arguments_delta=arguments_delta,
                        )
                    )

        return events

    @staticmethod
    def _finalize_stream_state(state: _StreamState) -> list[ProviderStreamEvent]:
        output: list[ProviderTextOutputItem | ProviderFunctionCallOutputItem] = []
        events: list[ProviderStreamEvent] = []

        text = "".join(state.text_chunks)
        if text:
            output.append(ProviderTextOutputItem(text=text))
            events.append(ProviderTextDoneEvent(text=text))

        for index in sorted(state.function_calls):
            function_state = state.function_calls[index]
            arguments = OpenRouterProvider._safe_parse_json(function_state.arguments_text)
            output.append(
                ProviderFunctionCallOutputItem(
                    call_id=function_state.call_id,
                    name=function_state.name,
                    arguments=arguments,
                )
            )
            events.append(
                ProviderFunctionCallDoneEvent(
                    call_id=function_state.call_id,
                    name=function_state.name,
                    arguments=arguments,
                )
            )

        events.append(
            ProviderDoneEvent(
                response=ProviderResponse(
                    id=state.response_id,
                    model=state.model,
                    output=output,
                    usage=state.usage,
                    finish_reason=state.finish_reason,
                )
            )
        )
        return events

    @staticmethod
    def _parse_usage(usage_payload: dict[str, Any]) -> ProviderUsage:
        prompt_tokens_details = usage_payload.get("prompt_tokens_details") or {}
        return ProviderUsage(
            input_tokens=int(usage_payload.get("prompt_tokens") or 0),
            output_tokens=int(usage_payload.get("completion_tokens") or 0),
            total_tokens=int(usage_payload.get("total_tokens") or 0),
            cached_tokens=int(prompt_tokens_details.get("cached_tokens") or usage_payload.get("cached_tokens") or 0),
        )

    @staticmethod
    def _safe_parse_json(raw_arguments: str) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            payload = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _coerce_index(raw_index: Any) -> int:
        if isinstance(raw_index, int):
            return raw_index
        if isinstance(raw_index, str) and raw_index.isdigit():
            return int(raw_index)
        return 0

    @staticmethod
    def _build_messages(request_data: ProviderRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request_data.instructions},
        ]
        pending_tool_calls: list[dict[str, Any]] = []

        def flush_pending_tool_calls() -> None:
            if pending_tool_calls:
                messages.append({"role": "assistant", "tool_calls": list(pending_tool_calls)})
                pending_tool_calls.clear()

        for item in request_data.input:
            if isinstance(item, ProviderFunctionCallInputItem):
                pending_tool_calls.append(
                    {
                        "id": item.call_id,
                        "type": "function",
                        "function": {
                            "name": item.name,
                            "arguments": json.dumps(item.arguments),
                        },
                    }
                )
                continue

            flush_pending_tool_calls()

            if isinstance(item, ProviderMessageInputItem):
                messages.append(
                    {
                        "role": item.role,
                        "content": item.content,
                    }
                )
                continue

            if isinstance(item, ProviderFunctionCallOutputInputItem):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.call_id,
                        "name": item.name,
                        "content": item.output,
                    }
                )

        flush_pending_tool_calls()
        return messages

    @staticmethod
    def _build_tools(request_data: ProviderRequest) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in request_data.tools:
            if not isinstance(tool, FunctionToolDefinition):
                continue

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return tools

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> ProviderResponse:
        choices = payload.get("choices") or []
        if not choices:
            raise OpenRouterProviderError("OpenRouter response did not contain any choices.")

        message = choices[0].get("message") or {}
        output = OpenRouterProvider._parse_output_items(message)
        usage_payload = payload.get("usage") or {}
        prompt_tokens_details = usage_payload.get("prompt_tokens_details") or {}
        usage = ProviderUsage(
            input_tokens=int(usage_payload.get("prompt_tokens") or 0),
            output_tokens=int(usage_payload.get("completion_tokens") or 0),
            total_tokens=int(usage_payload.get("total_tokens") or 0),
            cached_tokens=int(prompt_tokens_details.get("cached_tokens") or usage_payload.get("cached_tokens") or 0),
        )
        return ProviderResponse(
            id=str(payload.get("id") or "") or None,
            model=str(payload.get("model") or "") or None,
            output=output,
            usage=usage,
            finish_reason=str(choices[0].get("finish_reason") or "") or None,
        )

    @staticmethod
    def _parse_output_items(message: dict[str, Any]) -> list[ProviderTextOutputItem | ProviderFunctionCallOutputItem]:
        output: list[ProviderTextOutputItem | ProviderFunctionCallOutputItem] = []

        text = OpenRouterProvider._extract_text(message.get("content"))
        if text:
            output.append(ProviderTextOutputItem(text=text))

        for tool_call in message.get("tool_calls") or []:
            function_payload = tool_call.get("function") or {}
            raw_arguments = function_payload.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}

            output.append(
                ProviderFunctionCallOutputItem(
                    call_id=str(tool_call.get("id") or ""),
                    name=str(function_payload.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )

        return output

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return ""

        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
