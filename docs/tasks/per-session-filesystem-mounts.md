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

Physical layout on disk (per user, per session):

```
.agent_data/
  {user_key}/
    agents/
    workflows/
    skills/
    shared/
    workspaces/
      2026/05/05/
        {session_id}/
          files/
          attachments/
          plan.md
```

The `workspace/` mount maps to `.agent_data/{user_key}/workspaces/{date}/{session_id}/`.
The agent never sees the full path — it only knows `workspace/files/`, `workspace/attachments/`, `workspace/plan.md`.

Instructions describing the available mounts are injected into the agent's system prompt at run time,
generated automatically from the mount list (same pattern as `files-mcp` in 4th-devs).

---

## Current State

| What | Current behavior | Problem |
|------|-----------------|---------|
| Mounts | Global, built from `FS_ROOTS` at container startup | Same mounts for all users/sessions |
| User dirs | `.agent_data/agents/`, `.agent_data/shared/` etc. (flat global) | No per-user isolation on agents/skills/shared |
| Session workspace | `.../workspaces/{user_key}/sessions/{date}/{session_id}/input`, `/output`, `/notes.md` | Wrong dir names; agent sees `workspaces/` (plural) not `workspace/` |
| Filesystem service | Singleton in `Container` | Can't be per-session |
| Tool registry | Singleton, filesystem service baked in at build time | Follows the same limitation |
| Policy | `UserScopedWorkspaceFilesystemPolicy` redirects `workspaces/` mount root to user scoped path | Complex workaround for missing per-session mounts |
| Instructions | None generated from mounts | Agent has no filesystem contract in system prompt |

---

## Changes Required

### 1. `workspace_layout.py` — Restructure user and session layouts

**`UserWorkspaceLayout`** — simplified: only `root` and `workspaces_root`. Individual mount dirs are not hardcoded here; they're driven by config mount names.

```python
@dataclass(slots=True, frozen=True)
class UserWorkspaceLayout:
    workspace_key: str
    root: Path            # .agent_data/{user_key}/
    workspaces_root: Path # .agent_data/{user_key}/workspaces/
```

The physical path for any named mount is simply `root / mount_name`. No need for per-mount fields on this dataclass.

**`SessionWorkspaceLayout`** — rename dirs to match agent-facing names:

```python
@dataclass(slots=True, frozen=True)
class SessionWorkspaceLayout:
    user_workspace: UserWorkspaceLayout
    root: Path            # .../workspaces/{date}/{session_id}/
    files_dir: Path       # .../workspaces/{date}/{session_id}/files/       (was: input_dir)
    attachments_dir: Path # .../workspaces/{date}/{session_id}/attachments/ (was: output_dir)
    plan_file: Path       # .../workspaces/{date}/{session_id}/plan.md      (was: notes_file)
```

**`WorkspaceLayoutService`** changes:
- Constructor: accept `agent_mount_names: list[str]` (from config); rename `input_dir_name` → `files_dir_name`, `output_dir_name` → `attachments_dir_name`, `notes_file_name` → `plan_file_name`
- `resolve_user_workspace()`: return `UserWorkspaceLayout` with `root` and `workspaces_root` only
- `ensure_user_workspace()`: iterate `agent_mount_names` and create `root / name` for each; also create `workspaces_root`
- `ensure_session_workspace()`: use `workspaces_root` for date-nesting; create `files/`, `attachments/`, touch `plan.md`

New path structure:
```
workspace_root = .agent_data/
user root      = .agent_data/{user_key}/           ← was: .agent_data/workspaces/{user_key}/
workspaces dir = .agent_data/{user_key}/workspaces/
session root   = .agent_data/{user_key}/workspaces/{YYYY/MM/DD}/{session_id}/
```

> **Note:** This moves the user root from `workspaces/{user_key}/` to `{user_key}/` directly under workspace_root.
> The `WORKSPACE_PATH` env var still points to `.agent_data/`. Migration: existing `workspaces/{user_key}/` dirs would need to be moved.

**Mount building** is a free function in `paths.py` (see section 2), not a method on the layout service.

---

### 2. `paths.py` — Replace `build_filesystem_mounts()` with session-aware factory

`FilesystemPathResolver` already handles named mounts correctly — no changes needed there.

Replace `build_filesystem_mounts()` with `build_session_mounts()`:

```python
def build_session_mounts(
    *,
    mount_names: list[str],                 # from config FS_ROOTS, e.g. ["agents", "skills", "shared"]
    user_workspace: UserWorkspaceLayout,
    session_workspace: SessionWorkspaceLayout,
) -> list[FilesystemMount]:
    mounts = [
        FilesystemMount(name=name, root=user_workspace.root / name)
        for name in mount_names
    ]
    # workspace is always appended last and never comes from FS_ROOTS
    mounts.append(FilesystemMount(name="workspace", root=session_workspace.root))
    return mounts
```

The physical path for each user-scoped mount is `user_workspace.root / name` — straightforward derivation from the mount name itself.

Remove the `_workspace_root` stripping in `normalize_virtual_path()` — it was a workaround for the old global-mount setup and is no longer needed.

---

### 3. `policy.py` — Replace with permissive policy

With per-session mounts already correctly scoped (each mount points to the exact user/session directory), the complex redirect logic in `UserScopedWorkspaceFilesystemPolicy` is no longer needed.

Add a `PermissiveFilesystemPolicy` (allows all access within mounts):

```python
class PermissiveFilesystemPolicy:
    async def authorize(self, request: FilesystemAccessRequest) -> FilesystemAccessDecision:
        return FilesystemAccessDecision(
            allowed=True,
            effective_path=request.resolved_path.absolute_path,
            target_effective_path=(
                request.target_resolved_path.absolute_path
                if request.target_resolved_path else None
            ),
        )
```

Keep `UserScopedWorkspaceFilesystemPolicy` if needed as fallback for the old global-mount setup.

---

### 4. `service.py` — Add mount instructions generator

Add two methods to `AgentFilesystemService`:

```python
def list_mounts(self) -> list[FilesystemMount]:
    return self._path_resolver.mounts

def generate_filesystem_instructions(self) -> str:
    """
    Returns a <filesystem> block for injection into the agent system prompt.
    Describes available mounts and usage rules.
    """
```

Example output (generated from the actual mount list at runtime):

```markdown
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

The mount descriptions and the workspace sub-structure section are generated from the mount list.
The `workspace/` mount entry is special-cased to list known subdirs.

---

### 5. `container.py` — Remove filesystem and related singletons; add per-session factory

**Remove from `Container`:**
- `filesystem_service` singleton
- `tool_registry` singleton
- `agent_loader` singleton

All three move to per-session scope, created together in `build_runner()`.

**Add factory function:**

```python
def build_session_filesystem_service(
    *,
    session_workspace: SessionWorkspaceLayout,
    settings: Settings,
) -> AgentFilesystemService:
    mounts = build_session_mounts(
        mount_names=settings.agent_mount_names(),
        user_workspace=session_workspace.user_workspace,
        session_workspace=session_workspace,
    )
    path_resolver = FilesystemPathResolver(mounts)
    access_policy = PermissiveFilesystemPolicy()
    return AgentFilesystemService(
        path_resolver=path_resolver,
        access_policy=access_policy,
        max_file_size=settings.MAX_FILE_SIZE,
        exclude_patterns=settings.filesystem_exclude_patterns(),
    )
```

**Update `build_runner()`** — accepts `session_workspace` instead of a pre-built `tool_registry`/`agent_loader`; builds all three internally:

```python
def build_runner(
    *,
    session: Session,
    session_workspace: SessionWorkspaceLayout,   # NEW — replaces filesystem_service arg
    settings: Settings,
    mcp_manager: StdioMcpManager,
    provider_registry: ProviderRegistry,
    event_bus: EventBus,
    message_queue: SessionMessageQueue,
    repo_root: Path,
) -> Runner:
    filesystem_service = build_session_filesystem_service(
        session_workspace=session_workspace,
        settings=settings,
    )
    tool_registry = ToolRegistry(tools=get_tools(filesystem_service))
    agent_loader = AgentLoader(
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        repo_root=repo_root,
        workspace_path=settings.WORKSPACE_PATH,
    )
    return Runner(
        ...,
        tool_registry=tool_registry,
        agent_loader=agent_loader,
    )
```

`AgentLoader` per-sesja jest tani — nie ma żadnej ciężkiej inicjalizacji, pliki agentów czyta dopiero przy `load_agent()`.

**Update `build_chat_service()`** — remove `tool_registry` and `agent_loader` parameters; add `repo_root` and `settings` so it can pass them to `build_runner()`.

---

### 6. `chat_service.py` — Lazy runner initialization

`build_chat_service()` is called before the chat session is known (only the DB session exists at that point), so the runner cannot be built there.

**`ChatService` constructor change:**
- Remove `runner: Runner`, `agent_loader: AgentLoader` parameters
- Add the dependencies needed to build a runner: `repo_root: Path`, and ensure `settings: Settings` is present (already is)
- Store `self._runner: Runner | None = None`

**New private method:**

```python
def _ensure_runner(self, user: User, session: Session) -> Runner:
    if self._runner is None:
        session_workspace = self.workspace_layout_service.ensure_session_workspace(
            user=user, session=session
        )
        self._runner = build_runner(
            session=session,
            session_workspace=session_workspace,
            settings=self.settings,
            mcp_manager=self._mcp_manager,
            provider_registry=self._provider_registry,
            event_bus=self._event_bus,
            message_queue=self._message_queue,
            repo_root=self._repo_root,
        )
    return self._runner
```

`ensure_session_workspace()` uses `mkdir(exist_ok=True)` and `touch(exist_ok=True)` — idempotent, safe to call on an existing workspace.

**Call sites — all three flows must call `_ensure_runner()` before using `self.runner`:**

- `prepare_chat()` — already has `user` and `session` from `_load_session()`; call after `_load_session()`
- `_prepare_edit_setup()` — already loads `user` and `session`; call after loading them
- `deliver_to_agent()` — has `agent_id → current_agent.session_id`; load user via `_ensure_default_user()`, load session via `session_repository.get(current_agent.session_id)`; then call `_ensure_runner(user, session)`

**`build_chat_service()`** — remove `tool_registry`, `agent_loader`, `runner` parameters; add `repo_root`.

---

### 7. System prompt injection

In `runner.py` (or `chat_service.py`), when assembling the agent's system prompt, append the filesystem instructions:

```python
fs_instructions = filesystem_service.generate_filesystem_instructions()
system_prompt = f"{agent_template.system_prompt}\n\n{fs_instructions}"
```

The exact injection point is wherever system prompts are assembled before the first model call.
Check `runner.py` for where `system_prompt` is built from the agent template.

---

### 8. `config.py` — Redefine `FS_ROOTS` as agent mount names

**Keep `FS_ROOTS`** — but redefine its meaning: it's now a comma-separated list of **agent-facing mount names**, not filesystem paths. Each name maps to `{user_key}/{name}/` on disk.

```python
FS_ROOTS: str = "agents,skills,workflows,shared"
FS_EXCLUDE: str = ""   # keep as-is

def agent_mount_names(self) -> list[str]:
    return [name.strip().strip("/") for name in self.FS_ROOTS.split(",") if name.strip()]
```

`workspace` is never listed in `FS_ROOTS` — it is always added automatically by `build_session_mounts()`.

**Remove:**
- `FS_ROOT` (single-root legacy override) — no longer needed

**Add session workspace dir-name knobs** (for the internal structure of the session folder):

```python
FILES_DIR_NAME: str = "files"
ATTACHMENTS_DIR_NAME: str = "attachments"
PLAN_FILE_NAME: str = "plan.md"
```

Pass these into `WorkspaceLayoutService` at construction time in `container.py`.

Reflect all changes in `.env.EXAMPLE`. The `.env.EXAMPLE` entry for `FS_ROOTS` should be annotated to clarify it's mount names, not paths:

```env
# Agent filesystem mounts (agent-facing names; physical path: .agent_data/{user_key}/{name}/)
# workspace/ is always available and does not need to be listed here
FS_ROOTS=agents,skills,workflows,shared
```

---

### 9. `chat_attachments.py` — Rename `input_dir` → `attachments_dir`

`ChatAttachmentStorageService.store()` at line 44–53 uses `layout.input_dir` to resolve the destination path for uploaded files. After the `SessionWorkspaceLayout` rename, update to `layout.attachments_dir`.

The virtual path returned to the agent (line 53) currently uses `layout.input_dir.name` — this will become `layout.attachments_dir.name` (`"attachments"`), which correctly matches the agent-facing mount structure `workspace/attachments/`.

---

### 10. Tests to update / add

- `tests/test_settings.py` — update FS_ROOTS assertions: now a list of names, not paths; remove FS_ROOT
- `tests/test_mcp_config.py` — unrelated, leave as-is
- Add `tests/services/filesystem/test_workspace_layout.py`:
  - `test_ensure_user_workspace_creates_mount_dirs()` — dirs from FS_ROOTS exist after ensure
  - `test_ensure_user_workspace_skips_unlisted_mount()` — removing a name from FS_ROOTS removes that dir from creation
  - `test_session_workspace_dirs_created()` — files/, attachments/, plan.md exist
- Add `tests/services/filesystem/test_paths.py`:
  - `test_build_session_mounts_from_config_names()`
  - `test_workspace_mount_always_present_regardless_of_fs_roots()`
  - `test_agent_cannot_escape_mount()`
- Add `tests/services/filesystem/test_service.py`:
  - `test_generate_instructions_includes_all_active_mounts()`
  - `test_generate_instructions_workspace_section_lists_subdirs()`

---

## Affected Files Summary

| File | Change type |
|------|-------------|
| `services/filesystem/workspace_layout.py` | Refactor — simplified `UserWorkspaceLayout`, rename session dirs, remove per-mount fields |
| `services/filesystem/paths.py` | Replace `build_filesystem_mounts()` with `build_session_mounts(mount_names, ...)` |
| `services/filesystem/policy.py` | Add `PermissiveFilesystemPolicy`; keep old policy |
| `services/filesystem/service.py` | Add `list_mounts()`, `generate_filesystem_instructions()` |
| `container.py` | Remove `filesystem_service`, `tool_registry`, `agent_loader` singletons; add `build_session_filesystem_service()`; update `build_runner()` to build all three per-session |
| `services/chat_service.py` | Remove `runner`/`agent_loader` from constructor; add `_ensure_runner(user, session)` lazy init; call from all three flows (prepare_chat, _prepare_edit_setup, deliver_to_agent) |
| `services/chat_attachments.py` | Rename `layout.input_dir` → `layout.attachments_dir` (lines 44–53) |
| `runtime/runner.py` | Accept `filesystem_service`; inject instructions into system prompt |
| `config.py` | Redefine `FS_ROOTS` as mount names; remove `FS_ROOT`; add session dir-name knobs |
| `.env.EXAMPLE` | Annotate `FS_ROOTS` as mount names list, not paths |
| `tools/definitions/filesystem/*.py` | No logic change — verify they still receive `filesystem_service` correctly |

---

## Migration Note

Existing `.agent_data/workspaces/{user_key}/` directories will need to be moved to `.agent_data/{user_key}/`. This is a one-time rename. Add a startup check or migration script if needed.
