# manfred

Repository for the Manfred AI agent.

## Setup

Install dependencies and run the project with `uv`:

```bash
cd src
uv sync
source .venv/bin/activate
export PYTHONPATH="$PWD"
uv run alembic upgrade head
```
Then run
```bash 
uv run python -m app.main
```

## Filesystem Tools

The backend exposes native local tools instead of depending on `files-mcp` at runtime:

- `read_file`
- `search_file`
- `write_file`
- `manage_file`

Allowed roots come from `FS_ROOTS` or `FS_ROOT` and default to:

- `.agent_data/agents`
- `.agent_data/shared`
- `.agent_data/skills`
- `.agent_data/workflows`
- `.agent_data/workspaces`

Optional `FS_EXCLUDE` patterns can carve out paths inside those roots and are enforced across read, search, write, and manage operations.

The agent-facing contract is workspace-relative: the model should use paths like `agents/foo.agent.md`, `shared/docs/spec.md`, or `workspaces/u-1/note.md` without a leading `/`. Existing `.agent_data/...` paths remain accepted for backward compatibility.

Paths are virtual and must stay inside the configured mounts. Absolute paths and `..` segments are rejected. The `workspaces` mount is additionally scoped per user at runtime.

## MCP

The root `.mcp.json` stays in the repo so other MCP servers can still be configured. The bundled `files` server is no longer required for native filesystem access.

## Migration

```bash
uv run alembic upgrade head
 alembic revision --autogenerate #or alembic revision -m "your message here"
```
