from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.v1.api import api_router
from app.infra.container import Container


container = Container()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        app.container.langfuse_service().shutdown()


def create_app() -> FastAPI:
    settings = container.settings()

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
