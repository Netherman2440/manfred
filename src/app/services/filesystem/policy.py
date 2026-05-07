from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.services.filesystem.types import (
    FilesystemAccessDecision,
    FilesystemAccessRequest,
    FilesystemSubject,
    ResolvedFilesystemPath,
)
from app.services.filesystem.workspace_layout import WorkspaceLayoutService


class FilesystemAccessPolicy(Protocol):
    async def authorize(self, request: FilesystemAccessRequest) -> FilesystemAccessDecision: ...


class WorkspaceScopedFilesystemPolicy:
    def __init__(
        self,
        *,
        workspace_layout_service: WorkspaceLayoutService,
        fs_root: Path,
    ) -> None:
        self._workspace_layout_service = workspace_layout_service
        self._fs_root = fs_root.resolve()

    async def authorize(self, request: FilesystemAccessRequest) -> FilesystemAccessDecision:
        target_effective_path: Path | None = None

        allowed, message, effective_path = self._authorize_path(request.resolved_path, request.subject)
        if not allowed:
            return FilesystemAccessDecision(
                allowed=False,
                message=message,
                error_code="filesystem_access_denied",
            )

        if request.target_resolved_path is not None:
            target_allowed, target_message, target_effective_path = self._authorize_path(
                request.target_resolved_path,
                request.subject,
            )
            if not target_allowed:
                return FilesystemAccessDecision(
                    allowed=False,
                    message=target_message,
                    error_code="filesystem_access_denied",
                )

        return FilesystemAccessDecision(
            allowed=True,
            effective_path=effective_path,
            target_effective_path=target_effective_path,
        )

    def _authorize_path(
        self,
        resolved_path: ResolvedFilesystemPath,
        subject: FilesystemSubject,
    ) -> tuple[bool, str | None, Path]:
        if resolved_path.mount.name == "workspace":
            return self._authorize_workspace_path(resolved_path, subject)
        return self._authorize_user_scoped_path(resolved_path, subject)

    def _authorize_workspace_path(
        self,
        resolved_path: ResolvedFilesystemPath,
        subject: FilesystemSubject,
    ) -> tuple[bool, str | None, Path]:
        if subject.workspace_path is None:
            return False, "Filesystem access to workspace/ requires a session workspace.", resolved_path.absolute_path

        workspace_root = Path(subject.workspace_path).resolve()
        relative = resolved_path.relative_path
        effective_path = workspace_root if relative == relative.parent else workspace_root / relative

        if not effective_path.is_relative_to(workspace_root):
            return False, f"Path '{resolved_path.requested_path}' escapes the session workspace.", effective_path

        return True, None, effective_path

    def _authorize_user_scoped_path(
        self,
        resolved_path: ResolvedFilesystemPath,
        subject: FilesystemSubject,
    ) -> tuple[bool, str | None, Path]:
        if not subject.user_id and not subject.user_name:
            return False, "Filesystem access requires a user identity.", resolved_path.absolute_path

        user_key = self._workspace_layout_service.resolve_user_workspace_key(
            user_id=subject.user_id,
            user_name=subject.user_name,
        )
        scoped_root = (self._fs_root / user_key / resolved_path.mount.name).resolve()
        relative = resolved_path.relative_path
        effective_path = scoped_root if relative == relative.parent else scoped_root / relative

        if not effective_path.is_relative_to(scoped_root):
            return (
                False,
                f"Path '{resolved_path.requested_path}' escapes the user directory.",
                effective_path,
            )

        return True, None, effective_path
