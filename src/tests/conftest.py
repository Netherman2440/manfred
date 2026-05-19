from pathlib import Path

import pytest

from app.services.filesystem import AgentFilesystemService
from app.services.workspace_layout import WorkspaceLayoutService


class FakeFilesystemService:
    """Minimal stub for tests that need a Runner but don't test filesystem features."""

    def generate_filesystem_instructions(self) -> str:
        return ""

    def list_mounts(self) -> list:
        return []


def build_fake_filesystem_service(tmp_path: Path) -> AgentFilesystemService:
    fs_root = tmp_path / ".agent_data"
    fs_root.mkdir(parents=True, exist_ok=True)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
        agent_mount_names=["agents", "shared"],
    )
    return AgentFilesystemService(
        workspace_layout_service=workspace_layout_service,
        mount_names=["agents", "shared"],
        max_file_size=1024 * 1024,
    )


@pytest.fixture
def fake_filesystem_service(tmp_path: Path) -> AgentFilesystemService:
    return build_fake_filesystem_service(tmp_path)
