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
    def __init__(self, *, workspace_layout_service: WorkspaceLayoutService, max_file_size: int) -> None:
        self.workspace_layout_service = workspace_layout_service
        self._max_file_size = max_file_size

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
            if len(attachment.content) > self._max_file_size:
                raise ValueError(
                    f"Attachment '{attachment.file_name}' exceeds the maximum allowed size "
                    f"of {self._max_file_size} bytes."
                )
            destination, resolved_name = self._store_atomically(layout.attachments_dir, attachment)
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
    def _store_atomically(target_dir: Path, attachment: IncomingAttachment) -> tuple[Path, str]:
        candidate = Path(attachment.file_name).name or "attachment"
        stem = Path(candidate).stem or "attachment"
        suffix = Path(candidate).suffix
        resolved = candidate
        counter = 1
        while True:
            destination = target_dir / resolved
            try:
                with destination.open("xb") as f:
                    f.write(attachment.content)
                return destination, resolved
            except FileExistsError:
                resolved = f"{stem}({counter}){suffix}"
                counter += 1
