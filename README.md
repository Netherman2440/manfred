# manfred

Minimalny starter projektu LangGraph w Pythonie.

## Wymagania

- Python 3.12+
-  `uv` (`https://docs.astral.sh/uv/`)

## Szybki start (uv)

Linux:
```bash
cd src
uv venv
uv sync 
source .venv/bin/activate
export PYTHONPATH="$PWD"
```

## Langfuse

Ustaw w `.env`:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=development
```

## Testy

```bash
uv run pytest
```

albo:

```bash
pytest
```
