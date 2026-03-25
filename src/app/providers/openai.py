from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from app.domain import (
    ProviderFunctionCall,
    ProviderFunctionCallInput,
    ProviderFunctionResultInput,
    ProviderInput,
    ProviderMessageInput,
    ProviderResponse,
    ProviderTextOutput,
)


@dataclass(slots=True, frozen=True)
class OpenAIProviderConfig:
    base_url: str
    api_key: str
    timeout_seconds: int
    provider_name: str
    app_name: str


class OpenAIProvider:
    def __init__(self, config: OpenAIProviderConfig) -> None:
        self._config = config

    def generate(self, provider_input: ProviderInput) -> ProviderResponse:
        payload = {
            "model": provider_input.model,
            "messages": self._build_messages(provider_input),
        }
        if provider_input.tools:
            payload["tools"] = [self._serialize_tool_definition(tool) for tool in provider_input.tools]
            payload["tool_choice"] = "auto"

        response_payload = self._post_json(
            url=f"{self._config.base_url.rstrip('/')}/chat/completions",
            payload=payload,
        )
        return self._parse_response(response_payload)

    def _post_json(self, *, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._config.api_key:
            raise RuntimeError(
                f"Missing API key for provider '{self._config.provider_name}'. "
                "Set the matching environment variable before calling the chat endpoint."
            )

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        if self._config.provider_name == "openrouter":
            headers["X-Title"] = self._config.app_name

        http_request = request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self._config.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Provider request failed with status {exc.code}: {response_body}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Provider request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Provider returned invalid JSON.") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("Provider returned an unexpected payload shape.")
        return parsed

    def _build_messages(self, provider_input: ProviderInput) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": provider_input.instructions,
            }
        ]

        pending_tool_calls: list[dict[str, Any]] = []

        def flush_pending_tool_calls() -> None:
            if not pending_tool_calls:
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": pending_tool_calls.copy(),
                }
            )
            pending_tool_calls.clear()

        for item in provider_input.items:
            if isinstance(item, ProviderMessageInput):
                flush_pending_tool_calls()
                messages.append(
                    {
                        "role": item.role,
                        "content": item.content,
                    }
                )
                continue

            if isinstance(item, ProviderFunctionCallInput):
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

            if isinstance(item, ProviderFunctionResultInput):
                flush_pending_tool_calls()
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.call_id,
                        "content": self._serialize_tool_output(item.output),
                    }
                )

        flush_pending_tool_calls()
        return messages

    @staticmethod
    def _serialize_tool_definition(tool: Any) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _parse_response(self, response_payload: dict[str, Any]) -> ProviderResponse:
        response_model = response_payload.get("model")
        if not isinstance(response_model, str):
            response_model = None

        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Provider response does not contain choices.")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Provider response does not contain a message.")

        output: list[ProviderTextOutput | ProviderFunctionCall] = []
        text = self._extract_text(message.get("content"))
        if text:
            output.append(ProviderTextOutput(text=text))

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function_payload = tool_call.get("function")
                if not isinstance(function_payload, dict):
                    continue

                call_id = tool_call.get("id")
                name = function_payload.get("name")
                arguments = self._parse_arguments(function_payload.get("arguments"))
                if not isinstance(call_id, str) or not isinstance(name, str):
                    continue

                output.append(
                    ProviderFunctionCall(
                        call_id=call_id,
                        name=name,
                        arguments=arguments,
                    )
                )

        return ProviderResponse(model=response_model, output=output)

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)

        return ""

    @staticmethod
    def _parse_arguments(arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments

        if not isinstance(arguments, str):
            return {}

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _serialize_tool_output(output: Any) -> str:
        if isinstance(output, str):
            return output
        return json.dumps(output, ensure_ascii=False)
