from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.models.schema import ModelSummarySchema, ModelsListResponse
from app.container import Container
from app.services.model_catalog_service import ModelCatalogService, ModelCatalogUnavailable


router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsListResponse)
@inject
async def list_models(
    model_catalog_service: ModelCatalogService = Depends(Provide[Container.model_catalog_service]),
) -> ModelsListResponse:
    try:
        models = await model_catalog_service.list_models()
    except ModelCatalogUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model catalog unavailable. Check OpenRouter connectivity.",
        ) from exc
    return ModelsListResponse(
        data=[
            ModelSummarySchema(
                id=m.id,
                name=m.name,
                context_length=m.context_length,
                pricing_prompt_per_1k=m.pricing_prompt_per_1k,
                pricing_completion_per_1k=m.pricing_completion_per_1k,
            )
            for m in models
        ]
    )
