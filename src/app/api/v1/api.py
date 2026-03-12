from fastapi import APIRouter

from app.api.v1.chat.api import router as chat_router


api_router = APIRouter()
api_router.include_router(chat_router)


@api_router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
