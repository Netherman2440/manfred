from __future__ import annotations

from pydantic import BaseModel, Field


class AgentParamsRequest(BaseModel):
    params: str = Field(..., min_length=1)


class AgentOutputResponse(BaseModel):
    output: str
