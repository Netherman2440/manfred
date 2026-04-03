from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request

from app.domain.tool import FunctionToolDefinition
from app.providers.base import Provider
from app.providers.types import (
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)


class OpenRouterProviderError(RuntimeError):
    pass


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

        raw_response = await asyncio.to_thread(self._post_json, payload)
        return self._parse_response(raw_response)

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
            with request.urlopen(http_request) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise OpenRouterProviderError(
                f"OpenRouter request failed with status {exc.code}: {detail or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise OpenRouterProviderError(f"OpenRouter request failed: {exc.reason}") from exc

    @staticmethod
    def _build_messages(request_data: ProviderRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request_data.instructions},
        ]

        for item in request_data.input:
            if isinstance(item, ProviderMessageInputItem):
                messages.append(
                    {
                        "role": item.role,
                        "content": item.content,
                    }
                )
                continue

            if isinstance(item, ProviderFunctionCallInputItem):
                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": item.call_id,
                                "type": "function",
                                "function": {
                                    "name": item.name,
                                    "arguments": json.dumps(item.arguments),
                                },
                            }
                        ],
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
            cached_tokens=int(
                prompt_tokens_details.get("cached_tokens")
                or usage_payload.get("cached_tokens")
                or 0
            ),
        )
        return ProviderResponse(output=output, usage=usage)

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
