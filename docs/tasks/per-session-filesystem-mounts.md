# Per-Session Filesystem Mounts

## Goal

Agents should see a clean, session-scoped virtual filesystem with five named mounts:

```
agents/      — agent definitions (user-scoped, read-only in practice)
workflows/   — workflow definitions (user-scoped)
skills/      — skill definitions (user-scoped)
shared/      — shared knowledge base (user-scoped)
workspace/   — this session's working directory (read/write)
```

Physical layout on disk:

```
.agent_data/                                    ← fs_root
  {user_key}/                                   ← user_root
    agents/
    workflows/
    skills/
    shared/
    workspaces/                                 ← workspaces_root (per user)
      2026/05/05/
        {session_id}/                           ← session_root
          files/
          attachments/
          plan.md
```

The `workspace/` mount maps to `session_root`. The agent never sees the full path — it only knows `workspace/files/`, `workspace/attachments/`, `workspace/plan.md`.

Instructions describing the available mounts are injected into the agent's system prompt at run time, generated automatically from the mount list.

---

## Architecture

`AgentFilesystemService` is a singleton. `ToolRegistry` and `AgentLoader` are singletons.

`workspace_path` (the physical `session_root` path) is stored in the `sessions` table when a session workspace is created. It flows through the call chain to the filesystem policy, which uses it to resolve the `workspace/` mount:

```
sessions.workspace_path (DB)
  → Session.workspace_path (domain model)
    → ToolExecutionContext.workspace_path (built per tool-call in runner)
      → FilesystemSubject.workspace_path
        → policy redirects workspace/ to Path(workspace_path) / relative
```

User-scoped mounts (agents, skills, etc.) are routed by the policy using `subject.user_id + subject.user_name` to derive `user_key` and redirect to `fs_root / user_key / mount_name / relative`.

All mounts have `fs_root` (`.agent_data/`) as their physical root in the path resolver. This is the outer escape boundary. Fine-grained routing to user/session directories is handled entirely by the policy.

---

## Current State

| What | Current behavior | Problem |
|------|-----------------|---------|
| Mounts | Built from full filesystem paths in `FS_ROOTS` | Mount names derived from paths; `workspaces/` (plural) instead of `workspace/` |
| User dirs | Flat global dirs under `.agent_data/` | No per-user isolation |
| Session workspace | `input/`, `output/`, `notes.md` under `sessions/{user_key}/...` | Dir names don't match agent-facing mount structure |
| `workspace_path` | Not stored on session | Policy can't resolve which session dir to use for `workspace/` |
| Policy | Redirects `workspaces/` to user dir only | No session scoping |
| Instructions | Not generated | Agent has no filesystem contract in system prompt |

---

## Changes Required

### 1. `workspace_layout.py`

**`UserWorkspaceLayout`**:

```python
@dataclass(slots=True, frozen=True)
class UserWorkspaceLayout:
    workspace_key: str
    root: Path            # fs_root / user_key
    workspaces_root: Path # fs_root / user_key / workspaces
```

**`SessionWorkspaceLayout`**:

```python
@dataclass(slots=True, frozen=True)
class SessionWorkspaceLayout:
    user_workspace: UserWorkspaceLayout
    root: Path            # workspaces_root / date / session_id
    files_dir: Path       # root / files
    attachments_dir: Path # root / attachments
    plan_file: Path       # root / plan.md
```

**`WorkspaceLayoutService`**:
- Rename constructor param and stored attr: `workspace_root` → `fs_root`
- Remove `workspaces_root` from service level (it lives on `UserWorkspaceLayout` now)
- Add constructor params: `agent_mount_names: list[str]`, `files_dir_name: str`, `attachments_dir_name: str`, `plan_file_name: str`
- Remove: `sessions_dir_name`, `agents_dir_name`, `input_dir_name`, `output_dir_name`, `notes_file_name`
- `resolve_user_workspace()`: compute `root = fs_root / user_key`, `workspaces_root = root / "workspaces"`, return `UserWorkspaceLayout`
- `ensure_user_workspace()`: create `root / name` for each name in `agent_mount_names`; create `workspaces_root`
- `ensure_session_workspace()`: date-nest session under `workspaces_root`; create `files_dir`, `attachments_dir`; touch `plan_file`

---

### 2. `paths.py`

Replace `build_filesystem_mounts()` with `build_mounts()`:

```python
def build_mounts(
    *,
    mount_names: list[str],
    fs_root: Path,
) -> list[FilesystemMount]:
    mounts = [FilesystemMount(name=name, root=fs_root) for name in mount_names]
    mounts.append(FilesystemMount(name="workspace", root=fs_root))
    return mounts
```

`workspace` is always appended and never comes from `FS_MOUNTS`.

Remove the `workspace_root` parameter from `FilesystemPathResolver.__init__()` and the `_workspace_root` stripping logic in `normalize_virtual_path()`.

---

### 3. `policy.py`

Replace `UserScopedWorkspaceFilesystemPolicy` with `WorkspaceScopedFilesystemPolicy`:

```python
class WorkspaceScopedFilesystemPolicy:
    def __init__(
        self,
        *,
        workspace_layout_service: WorkspaceLayoutService,
        fs_root: Path,
    ) -> None:
        ...
```

**Routing logic:**

- **`workspace/` mount**: redirect to `Path(subject.workspace_path) / relative_path`.
  Deny if `subject.workspace_path` is `None`.
  Verify effective_path is relative to `Path(subject.workspace_path)`.

- **All other mounts**: derive `user_key` via `workspace_layout_service.resolve_user_workspace_key(user_id, user_name)`, redirect to `fs_root / user_key / mount.name / relative_path`.
  Deny if subject carries no user identity.
  Verify effective_path is relative to `fs_root / user_key / mount.name`.

---

### 4. `service.py`

Add to `AgentFilesystemService`:

```python
def list_mounts(self) -> list[FilesystemMount]:
    return self._path_resolver.mounts

def generate_filesystem_instructions(self) -> str:
    ...
```

`generate_filesystem_instructions()` returns a `<filesystem>` block injected into the agent system prompt. It lists all mounts from `list_mounts()`. The `workspace/` entry is special-cased to include known subdirs. Example output:

```
<filesystem>
Your file tools operate on a sandboxed filesystem. All paths are relative — never use a leading "/".

Available mounts (use fs_read(".") to list them):
- agents/      — your agent definitions
- workflows/   — your workflow definitions
- skills/      — your skill definitions
- shared/      — shared knowledge base
- workspace/   — your session workspace (read/write)
  - workspace/files/        — working files
  - workspace/attachments/  — session attachments
  - workspace/plan.md       — session plan

Rules:
1. Read a file before modifying it (checksum required for writes)
2. Use workspace/ for all session output
3. agents/, workflows/, skills/ contain definitions — prefer read over write
</filesystem>
```

---

### 5. Sessions table — `workspace_path` column

**Alembic migration:**

```python
op.add_column("sessions", sa.Column("workspace_path", sa.String(), nullable=True))
```

**`db/models/session.py`**: add `workspace_path: Mapped[str | None]`.

**`domain/session.py`**: add `workspace_path: str | None = None`.

**`domain/repositories/session_repository.py`**: map `workspace_path` in `_to_domain()` and `_from_domain()`.

---

### 6. `ToolExecutionContext` and `FilesystemSubject`

**`domain/tool.py`** — add field to `ToolExecutionContext`:

```python
workspace_path: str | None = None
```

**`services/filesystem/types.py`** — add field to `FilesystemSubject`:

```python
workspace_path: str | None = None
```

**`tools/definitions/filesystem/common.py`** — `build_filesystem_subject()`:

```python
def build_filesystem_subject(context: ToolExecutionContext) -> FilesystemSubject:
    return FilesystemSubject(
        user_id=context.user_id,
        session_id=context.session_id,
        agent_id=context.agent_id,
        user_name=context.user_name,
        workspace_path=context.workspace_path,
    )
```

**`runtime/runner.py`** — `_build_tool_execution_context()`:

```python
return ToolExecutionContext(
    user_id=context.session.user_id,
    user_name=user_name,
    session_id=context.session.id,
    agent_id=context.agent.id,
    call_id=function_call.call_id,
    tool_name=function_call.name,
    workspace_path=context.session.workspace_path,
    signal=signal,
)
```

---

### 7. `container.py`

Update `build_filesystem_service()`:

```python
def build_filesystem_service(
    *,
    settings: Settings,
    repo_root: Path,
    workspace_layout_service: WorkspaceLayoutService,
) -> AgentFilesystemService:
    fs_root = _resolve_fs_root(repo_root=repo_root, workspace_path=settings.WORKSPACE_PATH)
    mounts = build_mounts(mount_names=settings.mount_names(), fs_root=fs_root)
    path_resolver = FilesystemPathResolver(mounts)
    access_policy = WorkspaceScopedFilesystemPolicy(
        workspace_layout_service=workspace_layout_service,
        fs_root=fs_root,
    )
    return AgentFilesystemService(
        path_resolver=path_resolver,
        access_policy=access_policy,
        max_file_size=settings.MAX_FILE_SIZE,
        exclude_patterns=settings.filesystem_exclude_patterns(),
    )
```

Update `build_workspace_layout_service()` to pass `agent_mount_names`, `files_dir_name`, `attachments_dir_name`, `plan_file_name` from settings.

Update `build_runner()` to accept and pass `filesystem_service: AgentFilesystemService`.

---

### 8. `chat_service.py`

In `_load_session()`, when creating a new session, save `workspace_path` after creating the workspace:

```python
saved_session = self.session_repository.save(session)
layout = self.workspace_layout_service.ensure_session_workspace(user=user, session=saved_session)
saved_session.workspace_path = str(layout.root)
self.session_repository.save(saved_session)
return saved_session
```

Remove the existing `self.workspace_layout_service.ensure_session_workspace()` call that currently appears later in `_load_session()` (line 782).

---

### 9. `chat_attachments.py`

```python
resolved_name = self._resolve_available_name(layout.attachments_dir, attachment.file_name)
destination = layout.attachments_dir / resolved_name
path=f"workspace/attachments/{resolved_name}",
```

---

### 10. `config.py`

Rename `FS_ROOTS` to `FS_MOUNTS`. Change default value from filesystem paths to mount names:

```python
FS_MOUNTS: str = "agents,skills,workflows,shared"
FS_EXCLUDE: str = ""

def mount_names(self) -> list[str]:
    return [name.strip().strip("/") for name in self.FS_MOUNTS.split(",") if name.strip()]
```

Remove `FS_ROOT`.

Add session workspace dir-name settings:

```python
FILES_DIR_NAME: str = "files"
ATTACHMENTS_DIR_NAME: str = "attachments"
PLAN_FILE_NAME: str = "plan.md"
```

Update `.env.EXAMPLE`:

```env
# Agent-facing filesystem mount names (physical path: .agent_data/{user_key}/{name}/)
# workspace/ is always available and does not need to be listed here
FS_MOUNTS=agents,skills,workflows,shared
```

---

### 11. `runner.py`

Add `filesystem_service: AgentFilesystemService` to `Runner.__init__()`.

In `_build_provider_request()`, append filesystem instructions to the agent's task:

```python
fs_instructions = self.filesystem_service.generate_filesystem_instructions()
instructions = f"{context.agent.config.task}\n\n{fs_instructions}"
request = ProviderRequest(
    model=model,
    instructions=instructions,
    ...
)
```

---

### 12. Tests

- `tests/test_settings.py` — update `FS_MOUNTS` assertions; remove `FS_ROOT`
- Add `tests/services/filesystem/test_workspace_layout.py`:
  - `test_ensure_user_workspace_creates_mount_dirs()`
  - `test_session_workspace_dirs_created()`
- Add `tests/services/filesystem/test_paths.py`:
  - `test_build_mounts_from_config_names()`
  - `test_workspace_mount_always_present()`
  - `test_agent_cannot_escape_fs_root()`
- Add `tests/services/filesystem/test_policy.py`:
  - `test_workspace_mount_routes_to_session_workspace_path()`
  - `test_user_mount_routes_to_user_key_directory()`
  - `test_workspace_mount_denied_when_workspace_path_none()`
  - `test_escape_attempt_blocked()`
- Add `tests/services/filesystem/test_service.py`:
  - `test_generate_instructions_includes_all_mounts()`
  - `test_generate_instructions_workspace_subdirs()`

---

## Affected Files

| File | Change |
|------|--------|
| `services/filesystem/workspace_layout.py` | Rename `fs_root`; rename session dirs; add `agent_mount_names` param |
| `services/filesystem/paths.py` | `build_mounts()`; remove `workspace_root` from `FilesystemPathResolver` |
| `services/filesystem/policy.py` | `WorkspaceScopedFilesystemPolicy` — routes user and session mounts via subject |
| `services/filesystem/service.py` | Add `list_mounts()`, `generate_filesystem_instructions()` |
| `services/filesystem/types.py` | Add `workspace_path` to `FilesystemSubject` |
| `db/models/session.py` | Add `workspace_path` column |
| Alembic migration | Add `workspace_path` to sessions table |
| `domain/session.py` | Add `workspace_path` field |
| `domain/repositories/session_repository.py` | Map `workspace_path` |
| `domain/tool.py` | Add `workspace_path` to `ToolExecutionContext` |
| `tools/definitions/filesystem/common.py` | Copy `workspace_path` in `build_filesystem_subject()` |
| `runtime/runner.py` | Add `filesystem_service`; pass `workspace_path` in tool context; inject fs instructions |
| `container.py` | Update `build_filesystem_service()`; update `build_workspace_layout_service()`; update `build_runner()` |
| `services/chat_service.py` | Save `workspace_path` on session creation in `_load_session()` |
| `services/chat_attachments.py` | Use `attachments_dir`; path `"workspace/attachments/{filename}"` |
| `config.py` | `FS_MOUNTS` (was `FS_ROOTS`); remove `FS_ROOT`; add dir-name settings |
| `.env.EXAMPLE` | Update `FS_MOUNTS` entry |
