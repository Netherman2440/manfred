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


class UserScopedWorkspaceFilesystemPolicy:
    def __init__(
        self,
        *,
        workspace_layout_service: WorkspaceLayoutService,
        workspace_mount_names: set[str] | None = None,
    ) -> None:
        self.workspace_layout_service = workspace_layout_service
        self.workspace_mount_names = workspace_mount_names or set()

    async def authorize(self, request: FilesystemAccessRequest) -> FilesystemAccessDecision:
        resolved_target = request.target_resolved_path
        target_effective_path: Path | None = None

        allowed, message, effective_path = self._authorize_path(request.resolved_path, request.subject)
        if not allowed:
            return FilesystemAccessDecision(
                allowed=False,
                message=message,
                error_code="filesystem_access_denied",
            )

        if resolved_target is not None:
            target_allowed, target_message, target_effective_path = self._authorize_path(
                resolved_target,
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
        mount_root = resolved_path.mount.root.resolve()
        if resolved_path.mount.name not in self.workspace_mount_names:
            return True, None, resolved_path.absolute_path

        if not subject.user_id and not subject.user_name:
            return False, "Filesystem access to workspaces requires a user_id.", resolved_path.absolute_path

        workspace_layout = self.workspace_layout_service.resolve_user_workspace(
            user_id=subject.user_id,
            user_name=subject.user_name,
        )
        scoped_root = workspace_layout.root.resolve(strict=False)
        if not scoped_root.is_relative_to(mount_root):
            return False, "Workspace filesystem scope is misconfigured.", resolved_path.absolute_path

        if resolved_path.absolute_path == mount_root:
            return True, None, scoped_root

        if resolved_path.absolute_path == scoped_root or resolved_path.absolute_path.is_relative_to(scoped_root):
            return True, None, resolved_path.absolute_path

        return (
            False,
            f"Access to '{resolved_path.requested_path}' is not allowed for the current user.",
            resolved_path.absolute_path,
        )
