from fastapi import APIRouter

from app.api.v1.agents.api import router as agents_router
from app.api.v1.chat.api import router as chat_router
from app.api.v1.models.api import router as models_router
from app.api.v1.tools.api import router as tools_router
from app.api.v1.users.api import router as users_router

api_router = APIRouter()
api_router.include_router(chat_router)
api_router.include_router(users_router)
api_router.include_router(agents_router)
api_router.include_router(tools_router)
api_router.include_router(models_router)


@api_router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
