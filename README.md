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

## MCP

The repo includes a root `.mcp.json` configured for `files-mcp`.

- It exposes `files__fs_read`, `files__fs_search`, and `files__fs_write`.
- Allowed roots follow `.mcp.json` `env.FS_ROOTS`: `.agent_data/agents`, `.agent_data/shared`, `.agent_data/skills`, `.agent_data/workflows`, and `.agent_data/workspaces`.
- The config builds `files-mcp` into `/tmp/files-mcp-dist` on startup because the upstream repo in this environment does not include `dist/`.
- Use relative paths in MCP calls, for example `.agent_data/skills/example.md`; absolute paths are rejected by `files-mcp`.

## Migration

```bash
uv run alembic upgrade head
 alembic revision --autogenerate #or alembic revision -m "your message here"
```
