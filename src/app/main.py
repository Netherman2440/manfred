
from app.api.v1.api import api_router as router
from app.infra.container import Container
from fastapi import FastAPI
import uvicorn
container = Container()

def create_app() -> FastAPI:

    settings = container.settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
    )
    app.container = container 

    app.include_router(router)

    return app


app = create_app()
uvicorn.run(app, port=container.settings().API_PORT, host=container.settings().API_HOST)