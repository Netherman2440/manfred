from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.v1.api import api_router
from app.container import Container
from app.observability import configure_logging, subscribe_event_logger

APP_FACTORY_PATH = "app.main:create_app"

container = Container()


def create_app() -> FastAPI:
    settings = container.settings()
    container.wire()
    configure_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        unsubscribe = subscribe_event_logger(container.event_bus())
        try:
            yield
        finally:
            unsubscribe()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        lifespan=lifespan,
    )
    app.container = container
    app.include_router(api_router, prefix=settings.API_V1_STR)
    return app


app = create_app()


def run() -> None:
    settings = container.settings()
    uvicorn.run(
        APP_FACTORY_PATH,
        factory=True,
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD,
    )


if __name__ == "__main__":
    run()
