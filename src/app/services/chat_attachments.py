from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain import Session, User
from app.services.filesystem import WorkspaceLayoutService


@dataclass(slots=True, frozen=True)
class IncomingAttachment:
    file_name: str
    media_type: str
    content: bytes


@dataclass(slots=True, frozen=True)
class StoredAttachment:
    file_name: str
    media_type: str
    size_bytes: int
    path: str


class ChatAttachmentStorageService:
    def __init__(self, *, workspace_layout_service: WorkspaceLayoutService) -> None:
        self.workspace_layout_service = workspace_layout_service

    def store(
        self,
        *,
        user: User,
        session: Session,
        attachments: list[IncomingAttachment],
    ) -> tuple[list[StoredAttachment], list[Path]]:
        if not attachments:
            return [], []

        layout = self.workspace_layout_service.ensure_session_workspace(user=user, session=session)
        stored: list[StoredAttachment] = []
        created_paths: list[Path] = []

        for attachment in attachments:
            resolved_name = self._resolve_available_name(layout.attachments_dir, attachment.file_name)
            destination = layout.attachments_dir / resolved_name
            destination.write_bytes(attachment.content)
            created_paths.append(destination)
            stored.append(
                StoredAttachment(
                    file_name=resolved_name,
                    media_type=attachment.media_type,
                    size_bytes=len(attachment.content),
                    path=f"workspace/attachments/{resolved_name}",
                )
            )

        return stored, created_paths

    def cleanup_files(self, paths: list[Path]) -> None:
        for path in reversed(paths):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue

    @staticmethod
    def _resolve_available_name(target_dir: Path, file_name: str) -> str:
        candidate = Path(file_name).name or "attachment"
        stem = Path(candidate).stem or "attachment"
        suffix = Path(candidate).suffix
        resolved = candidate
        counter = 1
        while (target_dir / resolved).exists():
            resolved = f"{stem}({counter}){suffix}"
            counter += 1
        return resolved
