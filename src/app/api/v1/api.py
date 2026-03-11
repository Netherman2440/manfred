from fastapi import APIRouter


api_router = APIRouter()

@api_router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        dict: Health status information.
    """
    return {"status": "healthy"}