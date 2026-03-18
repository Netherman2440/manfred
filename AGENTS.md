# Manfred Repo Conventions

## Stack

- HTTP API: `FastAPI`
- API schemas and settings: `Pydantic`
- Persistence: `SQLAlchemy ORM`
- Migrations: `Alembic`
- Dependency composition: `container.py`

## Configuration

- All environment variables must be mapped into `config.py`.
- `config.py` may define sensible defaults when an env value is optional.
- Application code should consume configuration through `config.py`, not directly from `os.environ`.
- Every config change must be reflected in `.env.EXAMPLE`.

## Dependency Injection

- `container.py` is the single source of truth for application-wide dependencies.
- Define shared services in the container: config, app state, LLM providers, repositories, tool registry, external integrations, and runtime services.
- FastAPI endpoints should use `Depends()` and receive dependencies sourced from the container.
- Do not instantiate providers, repositories, or shared services ad hoc inside route handlers.
- If a new feature needs a reusable dependency, register it in the container first.

## Tools

- One tool equals one file.
- Keep tool definition/configuration at the top of the file and the handler implementation below.
- If multiple related tools belong to one area, group them under a shared subdirectory in `src/app/agent/tools/`.
- Tools may depend on external services, but those services must be created in the container and injected into the tool.
- Registration of agent tools must happen centrally in the container.
- The container defines which tools are active for the current app runtime.

## Persistence

- Database models should be implemented with SQLAlchemy ORM.
- Schema evolution should go through Alembic migrations.
- Repository logic should stay separate from API schemas and route handlers.

## General Architecture

- Keep clear separation between API, domain, runtime, repositories, providers, and tools.
- Prefer wiring cross-cutting concerns in the container rather than passing config manually in many places.
- Preserve high-level runtime behavior from the original agent example; do not couple the system to one specific LLM SDK.
- Avoid long hundreds of lines files.