from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ToolSummarySchema(BaseModel):
    name: str
    description: str | None
    type: Literal["function", "web_search", "mcp"]


class ToolsListResponse(BaseModel):
    data: list[ToolSummarySchema]
