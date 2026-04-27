# Plan backendu: filesystem path hints

## Problem

Aktualny prompt agenta mówi o katalogach wewnątrz `.agent_data` jako `agents/`, `shared/`, `workflows/`, `workspaces/`, ale resolver filesystemu akceptuje tylko pełne mounty `.agent_data/agents/...`, `.agent_data/shared/...` itd. Model dostaje więc sprzeczne wskazówki i regularnie generuje błędne ścieżki.

## In scope

- `src/app/filesystem/paths.py`
- `src/app/container.py`
- `src/app/tools/definitions/filesystem/*.py`
- `.agent_data/agents/*.agent.md`
- `src/tests/test_filesystem_service.py`

## Contract

- Canonical path dla modelu:
  - `agents/...`
  - `shared/...`
  - `skills/...`
  - `workflows/...`
  - `workspaces/...`
- Backward compatibility:
  - `.agent_data/agents/...` i analogiczne stare ścieżki nadal są akceptowane wejściowo.
- Root listing:
  - `read_file(path='.')` zwraca krótkie nazwy katalogów workspace zamiast `.agent_data/...`.
- Error hint:
  - błędy walidacji ścieżki mają zwracać wskazanie „use workspace-relative paths, no leading slash”.

## Implementation notes

- Mount names wyliczać względnie do `WORKSPACE_PATH`, jeśli mount leży pod tym katalogiem.
- Resolver powinien stripować prefiks `WORKSPACE_PATH` z wejścia użytkownika przed dopasowaniem mounta.
- Opisy tooli i prompty agentów mają jawnie podawać przykładowe ścieżki.

## Tests

- alias `shared/...` działa,
- stare `.agent_data/shared/...` działa,
- `workspaces` nadal jest scoped per user,
- błąd dla `/agents/foo.md` zwraca hint zamiast nieczytelnego failure.
