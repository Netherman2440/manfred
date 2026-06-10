"""Async HTTP/SSE client for the Manfred backend.

Thin wrapper over the `/api/v1` endpoints a terminal UI needs. Streaming chat
yields parsed SSE events; deliver/cancel return the final ChatResponse dict.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class ManfredClientError(RuntimeError):
    """Raised when the backend returns an error or is unreachable."""


@dataclass(slots=True)
class StreamEvent:
    event: str
    data: dict[str, Any]


@dataclass(slots=True)
class Attachment:
    file_name: str
    media_type: str
    content: bytes

    @classmethod
    def from_path(cls, path: Path) -> Attachment:
        import mimetypes

        media_type, _ = mimetypes.guess_type(path.name)
        return cls(
            file_name=path.name,
            media_type=media_type or "application/octet-stream",
            content=path.read_bytes(),
        )


class ManfredClient:
    def __init__(self, base_url: str, *, timeout: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._api = f"{self.base_url}/api/v1"
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- discovery -------------------------------------------------------

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self._api}/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def me(self) -> dict[str, Any]:
        return await self._get_json(f"{self._api}/users/me")

    async def list_agents(self) -> list[dict[str, Any]]:
        payload = await self._get_json(f"{self._api}/agents")
        return payload.get("data", [])

    async def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        payload = await self._get_json(f"{self._api}/users/{user_id}/sessions")
        return payload.get("data", [])

    async def session_detail(self, user_id: str, session_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"{self._api}/users/{user_id}/sessions/{session_id}")
        return payload.get("data", {})

    # ---- chat ------------------------------------------------------------

    async def stream_chat(
        self,
        *,
        message: str,
        session_id: str | None = None,
        agent_name: str | None = None,
        attachments: Sequence[Attachment] = (),
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self._api}/chat/completions"
        if attachments:
            data: dict[str, str] = {"message": message, "stream": "true"}
            if session_id:
                data["session_id"] = session_id
            if agent_name:
                data["agent_name"] = agent_name
            files = [("attachments", (att.file_name, att.content, att.media_type)) for att in attachments]
            request = self._client.build_request("POST", url, data=data, files=files)
        else:
            body: dict[str, Any] = {
                "input": [{"type": "message", "role": "user", "content": message}],
                "stream": True,
            }
            if session_id:
                body["session_id"] = session_id
            if agent_name:
                body["agent_config"] = {"agent_name": agent_name}
            request = self._client.build_request("POST", url, json=body)

        async for event in self._stream_sse(request):
            yield event

    async def queue(self, session_id: str, message: str) -> dict[str, Any]:
        return await self._post_json(
            f"{self._api}/chat/sessions/{session_id}/queue",
            {"message": message},
        )

    async def deliver(
        self,
        agent_id: str,
        *,
        call_id: str,
        output: Any,
        is_error: bool = False,
    ) -> dict[str, Any]:
        return await self._post_json(
            f"{self._api}/chat/agents/{agent_id}/deliver?include_tool_result=true",
            {"call_id": call_id, "output": output, "is_error": is_error},
        )

    async def cancel(self, session_id: str) -> dict[str, Any]:
        return await self._post_json(
            f"{self._api}/chat/sessions/{session_id}/cancel",
            None,
        )

    async def summarize(self, session_id: str) -> dict[str, Any]:
        response = await self._client.post(f"{self._api}/chat/sessions/{session_id}/summarize")
        if response.status_code == 204:
            return {"status": "no_unobserved"}
        self._raise_for_status(response)
        return response.json()

    # ---- internals -------------------------------------------------------

    async def _stream_sse(self, request: httpx.Request) -> AsyncIterator[StreamEvent]:
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise ManfredClientError(f"Connection failed: {exc}") from exc
        try:
            if response.status_code >= 400:
                await response.aread()
                self._raise_for_status(response)
            event_name = "message"
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line == "":
                    if data_lines:
                        yield self._build_event(event_name, data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip())
            if data_lines:
                yield self._build_event(event_name, data_lines)
        except httpx.HTTPError as exc:
            raise ManfredClientError(f"Connection failed: {exc}") from exc
        finally:
            await response.aclose()

    @staticmethod
    def _build_event(event_name: str, data_lines: list[str]) -> StreamEvent:
        raw = "\n".join(data_lines)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw}
        return StreamEvent(event=event_name or data.get("type", "message"), data=data)

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise ManfredClientError(f"Connection failed: {exc}") from exc
        self._raise_for_status(response)
        return response.json()

    async def _post_json(self, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        try:
            response = await self._client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise ManfredClientError(f"Connection failed: {exc}") from exc
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = response.text
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            detail = response.json().get("detail", detail)
        raise ManfredClientError(f"HTTP {response.status_code}: {detail}")
