from __future__ import annotations

from pydantic import BaseModel


class ModelSummarySchema(BaseModel):
    id: str
    name: str
    context_length: int | None
    pricing_prompt_per_1k: float | None
    pricing_completion_per_1k: float | None


class ModelsListResponse(BaseModel):
    data: list[ModelSummarySchema]
