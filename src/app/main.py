from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any

import uvicorn
from fastapi import FastAPI

from app.api.v1.api import api_router
from app.infra.container import Container


container = Container()


async def _resolve_provider(provider_result: Any) -> Any:
    if isawaitable(provider_result):
        return await provider_result
    return provider_result


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _resolve_provider(app.container.init_resources())
    try:
        app.state.graph = await _resolve_provider(app.container.graph())
        yield
    finally:
        await _resolve_provider(app.container.shutdown_resources())
        app.container.langfuse_service().shutdown()


def create_app() -> FastAPI:
    settings = container.settings()
    container.wire()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        lifespan=lifespan,
    )
    app.container = container
    app.include_router(api_router, prefix=settings.API_V1_STR)
    return app


app = create_app()


if __name__ == "__main__":
    settings = container.settings()
    uvicorn.run(app, port=settings.API_PORT, host=settings.API_HOST)
