from pathlib import Path

import pytest

from app.db.base import utcnow
from app.domain import Session as DomainSession
from app.domain import SessionStatus, ToolExecutionContext, User
from app.services.filesystem import (
    AgentFilesystemService,
    FilesystemManageRequest,
    FilesystemPathResolver,
    FilesystemReadRequest,
    FilesystemSearchRequest,
    FilesystemSubject,
    FilesystemToolError,
    FilesystemWriteRequest,
    UserScopedWorkspaceFilesystemPolicy,
    WorkspaceLayoutService,
    build_filesystem_mounts,
)
from app.tools.definitions.filesystem import build_read_file_tool


def make_service(tmp_path: Path, *, exclude_patterns: list[str] | None = None) -> AgentFilesystemService:
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    mounts = build_filesystem_mounts(
        repo_root=tmp_path,
        fs_roots=[
            ".agent_data/shared",
            ".agent_data/workspaces",
        ],
        workspace_path=".agent_data",
    )
    return AgentFilesystemService(
        path_resolver=FilesystemPathResolver(mounts, workspace_root=".agent_data"),
        access_policy=UserScopedWorkspaceFilesystemPolicy(
            workspace_layout_service=workspace_layout_service,
            workspace_mount_names={"workspaces"},
        ),
        max_file_size=1024 * 1024,
        exclude_patterns=exclude_patterns,
    )


def make_subject(user_id: str = "u-1", user_name: str | None = None) -> FilesystemSubject:
    return FilesystemSubject(
        user_id=user_id,
        session_id="session-1",
        agent_id="agent-1",
        user_name=user_name,
    )


def test_path_resolver_rejects_absolute_parent_and_symlink_escape(tmp_path: Path) -> None:
    shared_root = tmp_path / ".agent_data" / "shared"
    shared_root.mkdir(parents=True)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    (shared_root / "escape").symlink_to(outside_file)

    resolver = FilesystemPathResolver(
        build_filesystem_mounts(
            repo_root=tmp_path,
            fs_roots=[".agent_data/shared"],
            workspace_path=".agent_data",
        ),
        workspace_root=".agent_data",
    )

    assert resolver.resolve("shared").mount.name == "shared"
    assert resolver.resolve(".agent_data/shared/doc.txt").requested_path == "shared/doc.txt"

    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolver.resolve("/etc/passwd")

    with pytest.raises(ValueError, match="Parent path segments"):
        resolver.resolve(".agent_data/shared/../outside.txt")

    with pytest.raises(ValueError, match="escapes the allowed mount"):
        resolver.resolve(".agent_data/shared/escape")


@pytest.mark.asyncio
async def test_workspace_access_is_scoped_per_user(tmp_path: Path) -> None:
    workspace_root = tmp_path / ".agent_data" / "workspaces"
    (workspace_root / "alice-example").mkdir(parents=True)
    (workspace_root / "bob-example").mkdir(parents=True)
    (workspace_root / "alice-example" / "notes.txt").write_text("alpha\nshared secret\n", encoding="utf-8")
    (workspace_root / "bob-example" / "notes.txt").write_text("beta\nother secret\n", encoding="utf-8")

    service = make_service(tmp_path)
    subject = make_subject("u-1", "Alice Example")

    listing = await service.read(
        FilesystemReadRequest(
            subject=subject,
            tool_name="read_file",
            path="workspaces",
            mode="list",
        )
    )
    search = await service.search(
        FilesystemSearchRequest(
            subject=subject,
            tool_name="search_file",
            path=".",
            query="secret",
        )
    )

    assert [entry["path"] for entry in listing["entries"]] == ["workspaces/notes.txt"]
    assert [result["path"] for result in search["results"]] == ["workspaces/notes.txt"]

    with pytest.raises(FilesystemToolError, match="not allowed for the current user"):
        await service.read(
            FilesystemReadRequest(
                subject=subject,
                tool_name="read_file",
                path="workspaces/bob-example/notes.txt",
                mode="content",
            )
        )


def test_workspace_layout_service_creates_session_structure(tmp_path: Path) -> None:
    service = WorkspaceLayoutService(repo_root=tmp_path, workspace_path=".agent_data")
    now = utcnow()
    user = User(id="user-1", name="Anna Kowalska", api_key_hash=None, created_at=now)
    session = DomainSession(
        id="session-123",
        user_id=user.id,
        root_agent_id=None,
        status=SessionStatus.ACTIVE,
        title=None,
        created_at=now,
        updated_at=now,
    )

    layout = service.ensure_session_workspace(user=user, session=session)

    assert layout.user_workspace.root == tmp_path / ".agent_data" / "workspaces" / "anna-kowalska"
    assert layout.user_workspace.agents_root.is_dir()
    assert layout.input_dir.is_dir()
    assert layout.output_dir.is_dir()
    assert layout.notes_file.is_file()


@pytest.mark.asyncio
async def test_write_file_supports_dry_run_and_checksum_guard(tmp_path: Path) -> None:
    shared_root = tmp_path / ".agent_data" / "shared"
    shared_root.mkdir(parents=True)
    target_file = shared_root / "doc.txt"
    target_file.write_text("a\nb\n", encoding="utf-8")

    service = make_service(tmp_path)
    dry_run = await service.write(
        FilesystemWriteRequest(
            subject=make_subject(),
            tool_name="write_file",
            path="shared/doc.txt",
            operation="update",
            action="replace",
            lines="2-2",
            content="bee\n",
            dry_run=True,
        )
    )

    assert "@@" in dry_run["diff"]
    assert target_file.read_text(encoding="utf-8") == "a\nb\n"

    with pytest.raises(FilesystemToolError, match="Checksum mismatch"):
        await service.write(
            FilesystemWriteRequest(
                subject=make_subject(),
                tool_name="write_file",
                path=".agent_data/shared/doc.txt",
                operation="update",
                content="replaced\n",
                checksum="bad-checksum",
            )
        )


@pytest.mark.asyncio
async def test_root_listing_uses_workspace_relative_mount_names(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    listing = await service.read(
        FilesystemReadRequest(
            subject=make_subject(),
            tool_name="read_file",
            path=".",
            mode="list",
        )
    )

    assert [entry["path"] for entry in listing["entries"]] == ["shared", "workspaces"]


@pytest.mark.asyncio
async def test_fs_exclude_blocks_direct_access_and_hides_entries(tmp_path: Path) -> None:
    shared_root = tmp_path / ".agent_data" / "shared"
    (shared_root / "private").mkdir(parents=True)
    (shared_root / "public").mkdir(parents=True)
    (shared_root / "private" / "secret.txt").write_text("secret", encoding="utf-8")
    (shared_root / "public" / "note.txt").write_text("visible secret", encoding="utf-8")

    service = make_service(tmp_path, exclude_patterns=["shared/private/**"])

    listing = await service.read(
        FilesystemReadRequest(
            subject=make_subject(),
            tool_name="read_file",
            path="shared",
            mode="list",
        )
    )
    search = await service.search(
        FilesystemSearchRequest(
            subject=make_subject(),
            tool_name="search_file",
            path="shared",
            query="secret",
        )
    )

    assert [entry["path"] for entry in listing["entries"]] == ["shared/public"]
    assert [result["path"] for result in search["results"]] == ["shared/public/note.txt"]

    with pytest.raises(FilesystemToolError, match="excluded by filesystem policy"):
        await service.read(
            FilesystemReadRequest(
                subject=make_subject(),
                tool_name="read_file",
                path="shared/private/secret.txt",
                mode="content",
            )
        )

    with pytest.raises(FilesystemToolError, match="excluded by filesystem policy"):
        await service.write(
            FilesystemWriteRequest(
                subject=make_subject(),
                tool_name="write_file",
                path="shared/private/new.txt",
                operation="create",
                content="blocked\n",
                create_dirs=True,
            )
        )

    with pytest.raises(FilesystemToolError, match="excluded by filesystem policy"):
        await service.manage(
            FilesystemManageRequest(
                subject=make_subject(),
                tool_name="manage_file",
                path="shared/private",
                operation="stat",
            )
        )


@pytest.mark.asyncio
async def test_read_file_tool_returns_path_hint_for_absolute_path(tmp_path: Path) -> None:
    tool = build_read_file_tool(make_service(tmp_path))

    result = await tool.handler(
        {"path": "/agents/poem.md"},
        ToolExecutionContext(
            user_id="u-1",
            session_id="session-1",
            agent_id="agent-1",
            call_id="call-1",
            tool_name="read_file",
        ),
    )

    assert result["ok"] is False
    assert "workspace-relative paths" in str(result["error"])
