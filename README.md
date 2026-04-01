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

## Migration

```bash
alembic revision -m "your message here"
```