from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from app.api.v1.tools.schema import ToolSummarySchema, ToolsListResponse
from app.container import Container
from app.services.tool_catalog_service import ToolCatalogService


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolsListResponse)
@inject
def list_tools(
    tool_catalog_service: ToolCatalogService = Depends(Provide[Container.tool_catalog_service]),
) -> ToolsListResponse:
    tools = tool_catalog_service.list_tools()
    return ToolsListResponse(
        data=[
            ToolSummarySchema(name=t.name, description=t.description, type=t.type)
            for t in tools
        ]
    )
