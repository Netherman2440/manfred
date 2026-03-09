# manfred-langgraph

Minimalny starter projektu LangGraph w Pythonie.

## Wymagania

- Python 3.10+
- opcjonalnie: `uv` (`https://docs.astral.sh/uv/`)

## Szybki start (uv)

```bash
uv venv
source .venv/bin/activate
uv sync --extra dev
```

## Szybki start (pip)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Uruchomienie przykładu

```bash
langgraph-demo
```

albo:

```bash
uv run langgraph-demo
```

albo:

```bash
python3 -m manfred_langgraph.main
```

## Testy

```bash
uv run pytest
```

albo:

```bash
pytest
```
