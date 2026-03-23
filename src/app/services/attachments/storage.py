from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class AttachmentValidationError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class StoredAttachmentFile:
    original_filename: str
    stored_filename: str
    workspace_path: str
    mime_type: str
    size_bytes: int


class AttachmentStorageService:
    def __init__(
        self,
        *,
        workspace_root: Path,
        max_size_bytes: int,
    ) -> None:
        self._workspace_root = workspace_root.resolve(strict=False)
        self._input_root = self._workspace_root / "input"
        self._max_size_bytes = max_size_bytes
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._input_root.mkdir(parents=True, exist_ok=True)

    def save_bytes(
        self,
        session_id: str,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> StoredAttachmentFile:
        original_filename = self._normalize_filename(filename)
        if not content:
            raise AttachmentValidationError("Attachment content cannot be empty.")
        if len(content) > self._max_size_bytes:
            raise AttachmentValidationError(
                f"Attachment exceeds max size limit of {self._max_size_bytes} bytes."
            )

        session_dir = self._resolve_session_dir(session_id)
        stored_filename = self._build_stored_filename(original_filename)
        output_path = (session_dir / stored_filename).resolve(strict=False)
        try:
            output_path.relative_to(self._workspace_root)
        except ValueError as exc:
            raise AttachmentValidationError("Attachment path must stay within the workspace.") from exc

        output_path.write_bytes(content)
        mime_type = self._resolve_mime_type(original_filename, content_type)
        return StoredAttachmentFile(
            original_filename=original_filename,
            stored_filename=stored_filename,
            workspace_path=output_path.relative_to(self._workspace_root).as_posix(),
            mime_type=mime_type,
            size_bytes=len(content),
        )

    def _resolve_session_dir(self, session_id: str) -> Path:
        clean_session_id = session_id.strip()
        if clean_session_id == "":
            raise AttachmentValidationError("sessionId cannot be empty.")

        session_dir = (self._input_root / clean_session_id).resolve(strict=False)
        try:
            session_dir.relative_to(self._workspace_root)
        except ValueError as exc:
            raise AttachmentValidationError("sessionId resolves outside the workspace.") from exc

        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    @staticmethod
    def _normalize_filename(filename: str) -> str:
        candidate = Path(filename or "").name.strip()
        if candidate == "":
            candidate = "attachment"

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
        return safe_name or "attachment"

    @staticmethod
    def _resolve_mime_type(filename: str, content_type: str | None) -> str:
        cleaned = (content_type or "").strip()
        if cleaned:
            return cleaned

        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "application/octet-stream"

    @staticmethod
    def _build_stored_filename(filename: str) -> str:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S_%f")
        return f"{timestamp}_{filename}"
