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

## Redis

Przed uruchomieniem API odpal lokalnego Redisa, bo checkpointy i kontekst rozmowy są trzymane w Redisie.

Z katalogu głównego repo:

```bash
docker compose --env-file src/.env up -d --wait
```

`--wait` jest istotne, bo w trybie detached Compose zwraca sterowanie zanim Redis zacznie przyjmowac polaczenia.

W `src/.env` ustaw co najmniej:

```bash
REDIS_PASSWORD=change_me
REDIS_PORT=6380
REDIS_INSIGHT_PORT=8002
REDIS_SAVER_CONNECTION_STRING=redis://:change_me@127.0.0.1:6380/0
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
