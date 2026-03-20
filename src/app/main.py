from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn
from app.api.v1.api import api_router
from app.container import Container
from app.logging_config import configure_logging

APP_FACTORY_PATH = "app.main:create_app"

container = Container()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    app.container.observability_service().shutdown()


def create_app() -> FastAPI:
    settings = container.settings()
    configure_logging(settings)
    container.wire()

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
