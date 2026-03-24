from __future__ import annotations

import base64
import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.images.base import ImageService


DEFAULT_DESCRIPTION_PROMPT = (
    "Describe what is visible in this image. Focus on the main subjects, actions, "
    "setting, and notable details. Keep the description factual and concise."
)


class OpenAIImageService(ImageService):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        workspace_root: Path,
        vision_model: str = "gpt-4.1-mini",
        image_model: str = "gpt-image-1.5",
        image_size: str = "1024x1024",
        timeout_seconds: int = 120,
        client: Any | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._workspace_root = workspace_root.resolve(strict=False)
        self._vision_model = vision_model
        self._image_model = image_model
        self._image_size = image_size
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._output_dir = self._workspace_root / "output"
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def describe_image(self, path: str) -> str:
        return await self.analyze_image(path, DEFAULT_DESCRIPTION_PROMPT)

    async def analyze_image(self, path: str, prompt: str) -> str:
        self._ensure_api_key()
        image_path = self._resolve_workspace_path(path)
        if prompt.strip() == "":
            raise ValueError("Prompt cannot be empty.")

        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        if not image_path.is_file():
            raise IsADirectoryError(f"Not a file: {path}")

        mime_type = self._get_image_mime_type(image_path)
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        response = await self._get_client().responses.create(
            model=self._vision_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded_image}",
                        },
                    ],
                }
            ],
        )

        description = self._extract_response_text(response)
        if description == "":
            raise ValueError("OpenAI vision response did not contain text.")
        return description

    async def create_image(self, prompt: str) -> str:
        self._ensure_api_key()
        if prompt.strip() == "":
            raise ValueError("Prompt cannot be empty.")

        try:
            response = await self._get_client().images.generate(**self._build_image_request(prompt))
        except Exception:
            logging.exception("OpenAI image generation failed.")
            raise

        image_base64 = self._extract_generated_image(response)
        output_path = self._output_dir / self._build_output_filename(prompt)
        output_path.write_bytes(base64.b64decode(image_base64))
        return output_path.relative_to(self._workspace_root).as_posix()

    def _ensure_api_key(self) -> None:
        if self._api_key == "":
            raise ValueError("OPENAI_API_KEY is not configured.")

    def _resolve_workspace_path(self, path: str) -> Path:
        if path.strip() == "":
            raise ValueError("Image path cannot be empty.")

        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace_root / candidate

        resolved_path = candidate.resolve(strict=False)
        try:
            resolved_path.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ValueError("Path must be within the workspace root.") from exc

        return resolved_path

    def _get_image_mime_type(self, image_path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(image_path.name)
        if mime_type is None or not mime_type.startswith("image/"):
            raise ValueError(f"Unsupported image file type: {image_path.name}")
        return mime_type

    def _build_output_filename(self, prompt: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")
        if slug == "":
            slug = "generated_image"
        slug = slug[:40]
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{slug}_{timestamp}.png"

    def _build_image_request(self, prompt: str) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._image_model,
            "prompt": prompt,
            "size": self._image_size,
        }
        if not self._uses_gpt_image_model():
            request["response_format"] = "b64_json"
        return request

    def _uses_gpt_image_model(self) -> bool:
        return self._image_model.startswith("gpt-image-")

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The 'openai' package is not installed. Install project dependencies first."
                ) from exc

            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )

        return self._client

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if isinstance(output_text, str) and output_text.strip() != "":
                return output_text.strip()
            output = response.get("output")
        else:
            output_text = getattr(response, "output_text", None)
            if isinstance(output_text, str) and output_text.strip() != "":
                return output_text.strip()
            output = getattr(response, "output", None)

        if not isinstance(output, list):
            return ""

        parts: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for part in content:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if isinstance(text, str) and text.strip() != "":
                    parts.append(text.strip())

        return "\n".join(parts).strip()

    @staticmethod
    def _extract_generated_image(response: Any) -> str:
        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
        if not isinstance(data, list) or not data:
            raise ValueError("OpenAI image response did not contain data.")

        first_item = data[0]
        image_base64 = first_item.get("b64_json") if isinstance(first_item, dict) else getattr(first_item, "b64_json", None)
        if not isinstance(image_base64, str) or image_base64.strip() == "":
            raise ValueError("OpenAI image response did not contain base64 image data.")

        return image_base64
