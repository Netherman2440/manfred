from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.cors import apply_cors_middleware
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
        event_bus = container.event_bus()
        mcp_manager = container.mcp_manager()
        http_client = container.http_client()
        unsubscribe_logger = subscribe_event_logger(event_bus)
        markdown_event_logger = container.markdown_event_logger()
        unsubscribe_markdown = markdown_event_logger.subscribe(event_bus)
        langfuse_subscriber = container.langfuse_subscriber()
        unsubscribe_langfuse = (
            langfuse_subscriber.subscribe(event_bus) if langfuse_subscriber is not None else (lambda: None)
        )
        try:
            await mcp_manager.start()
            yield
        finally:
            await mcp_manager.close()
            await http_client.aclose()
            unsubscribe_langfuse()
            if langfuse_subscriber is not None:
                langfuse_subscriber.shutdown()
            unsubscribe_markdown()
            unsubscribe_logger()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        lifespan=lifespan,
    )
    apply_cors_middleware(app, settings)
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
