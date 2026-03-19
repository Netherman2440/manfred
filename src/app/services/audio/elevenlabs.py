from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from uuid import uuid4

from app.services.audio.base import AudioService


class ElevenLabsAudioService(AudioService):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        workspace_root: Path,
        transcription_model: str = "scribe_v2",
        text_to_speech_model: str = "eleven_multilingual_v2",
        voice_id: str = "",
        output_format: str = "mp3_44100_128",
        timeout_seconds: int = 120,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._workspace_root = workspace_root.resolve(strict=False)
        self._transcription_model = transcription_model
        self._text_to_speech_model = text_to_speech_model
        self._voice_id = voice_id.strip()
        self._output_format = output_format
        self._timeout_seconds = timeout_seconds
        self._output_dir = self._workspace_root / "output"
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def transcribe_audio(self, path: str) -> str:
        self._ensure_api_key()
        audio_path = self._resolve_workspace_path(path)

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")
        if not audio_path.is_file():
            raise IsADirectoryError(f"Not a file: {path}")

        mime_type, _ = mimetypes.guess_type(audio_path.name)
        content_type = mime_type or "application/octet-stream"

        payload = await self._request_json(
            "POST",
            "/v1/speech-to-text",
            form_fields={"model_id": self._transcription_model},
            files=[
                {
                    "field_name": "file",
                    "filename": audio_path.name,
                    "content_type": content_type,
                    "content": audio_path.read_bytes(),
                }
            ],
        )
        transcription = payload.get("text")
        if not isinstance(transcription, str) or transcription.strip() == "":
            raise ValueError("ElevenLabs transcription response did not contain text.")

        return transcription

    async def generate_audio(self, text: str) -> str:
        self._ensure_api_key()
        if text.strip() == "":
            raise ValueError("Text to synthesize cannot be empty.")

        voice_id = await self._resolve_voice_id()
        output_path = self._output_dir / self._build_output_filename(text)

        audio_bytes = await self._request_binary(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            query={"output_format": self._output_format},
            json_body={
                "text": text,
                "model_id": self._text_to_speech_model,
            },
        )

        output_path.write_bytes(audio_bytes)
        return output_path.relative_to(self._workspace_root).as_posix()

    def _ensure_api_key(self) -> None:
        if self._api_key == "":
            raise ValueError("ELEVENLABS_API_KEY is not configured.")

    def _resolve_workspace_path(self, path: str) -> Path:
        if path.strip() == "":
            raise ValueError("Audio path cannot be empty.")

        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace_root / candidate

        resolved_path = candidate.resolve(strict=False)
        try:
            resolved_path.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ValueError("Path must be within the workspace root.") from exc

        return resolved_path

    async def _resolve_voice_id(self) -> str:
        if self._voice_id != "":
            return self._voice_id

        payload = await self._request_json("GET", "/v1/voices", query={"page_size": "1"})
        voices = payload.get("voices")
        if not isinstance(voices, list):
            raise ValueError("ElevenLabs voices response did not contain a voice list.")

        for voice in voices:
            if not isinstance(voice, dict):
                continue
            voice_id = voice.get("voice_id")
            if isinstance(voice_id, str) and voice_id.strip() != "":
                self._voice_id = voice_id.strip()
                return self._voice_id

        raise ValueError("ELEVENLABS_VOICE_ID is not configured and ElevenLabs returned no voices.")

    def _build_output_filename(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        if slug == "":
            slug = "generated_audio"
        slug = slug[:40]
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        extension = self._output_format.split("_", maxsplit=1)[0]
        return f"{slug}_{timestamp}.{extension}"

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form_fields: dict[str, str] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = await asyncio.to_thread(
            self._send_request,
            method,
            path,
            query=query,
            json_body=json_body,
            form_fields=form_fields,
            files=files,
        )
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("ElevenLabs JSON response must be an object.")
        return parsed

    async def _request_binary(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> bytes:
        return await asyncio.to_thread(
            self._send_request,
            method,
            path,
            query=query,
            json_body=json_body,
        )

    def _send_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form_fields: dict[str, str] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> bytes:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"

        headers = {
            "xi-api-key": self._api_key,
        }
        body: bytes | None = None

        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif files:
            boundary = f"----ManfredBoundary{uuid4().hex}"
            body = self._encode_multipart_body(
                form_fields=form_fields or {},
                files=files,
                boundary=boundary,
            )
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif form_fields is not None:
            body = parse.urlencode(form_fields).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        http_request = request.Request(url=url, data=body, headers=headers, method=method)

        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                return response.read()
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"ElevenLabs request failed with status {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach ElevenLabs API: {exc.reason}") from exc

    @staticmethod
    def _encode_multipart_body(
        *,
        form_fields: dict[str, str],
        files: list[dict[str, Any]],
        boundary: str,
    ) -> bytes:
        body = bytearray()

        for key, value in form_fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        for file in files:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{file["field_name"]}"; '
                    f'filename="{file["filename"]}"\r\n'
                ).encode("utf-8")
            )
            body.extend(f'Content-Type: {file["content_type"]}\r\n\r\n'.encode("utf-8"))
            body.extend(file["content"])
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        return bytes(body)
