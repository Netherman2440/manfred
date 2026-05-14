from __future__ import annotations

import logging

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)

from app.api.v1.agents.schema import (
    AgentCreateRequest,
    AgentDetailResponse,
    AgentDetailSchema,
    AgentSessionsResponse,
    AgentsListResponse,
    AgentSummarySchema,
    AgentUpdateRequest,
)
from app.container import Container
from app.domain import User
from app.services.agent_template_service import (
    AgentTemplateExists,
    AgentTemplateInput,
    AgentTemplateInvalid,
    AgentTemplateNotFound,
    AgentTemplateService,
)
from app.services.session_query_service import SessionQueryIntegrityError, SessionQueryService

router = APIRouter(prefix="/agents", tags=["agents"])


def _get_default_user(settings: object) -> User:
    """Resolve the default user for single-user mode."""
    from app.db.base import utcnow
    from app.domain import User

    s = settings  # type: ignore[assignment]
    return User(
        id=s.DEFAULT_USER_ID,
        name=s.DEFAULT_USER_NAME,
        api_key_hash=None,
        created_at=utcnow(),
    )


@router.get("", response_model=AgentsListResponse)
@inject
def list_agents(
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    settings=Depends(Provide[Container.settings]),
) -> AgentsListResponse:
    user = _get_default_user(settings)
    summaries = agent_template_service.list_templates(user)
    return AgentsListResponse(
        data=[AgentSummarySchema(name=s.name, color=s.color, description=s.description) for s in summaries]
    )


@router.get("/{name}", response_model=AgentDetailResponse)
@inject
def get_agent(
    name: str,
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    settings=Depends(Provide[Container.settings]),
) -> AgentDetailResponse:
    user = _get_default_user(settings)
    detail = agent_template_service.get_template(user, name)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent not found: {name}")
    return AgentDetailResponse(
        data=AgentDetailSchema(
            name=detail.name,
            color=detail.color,
            description=detail.description,
            model=detail.model,
            system_prompt=detail.system_prompt,
            tools=detail.tools,
        )
    )


@router.post("", response_model=AgentDetailResponse, status_code=status.HTTP_201_CREATED)
@inject
def create_agent(
    request: AgentCreateRequest,
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    settings=Depends(Provide[Container.settings]),
) -> AgentDetailResponse:
    user = _get_default_user(settings)
    payload = AgentTemplateInput(
        name=request.name,
        color=request.color,
        description=request.description,
        model=request.model,
        tools=request.tools,
        system_prompt=request.system_prompt,
    )
    try:
        detail = agent_template_service.create_template(user, payload)
    except AgentTemplateExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "agent_already_exists", "name": request.name},
        ) from exc
    except AgentTemplateInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return AgentDetailResponse(
        data=AgentDetailSchema(
            name=detail.name,
            color=detail.color,
            description=detail.description,
            model=detail.model,
            system_prompt=detail.system_prompt,
            tools=detail.tools,
        )
    )


@router.put("/{name}", response_model=AgentDetailResponse)
@inject
def update_agent(
    name: str,
    request: AgentUpdateRequest,
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    settings=Depends(Provide[Container.settings]),
) -> AgentDetailResponse:
    logger.info(
        "update_agent name=%s request.name=%s request.color=%s request.model=%s",
        name,
        request.name,
        request.color,
        request.model,
    )
    user = _get_default_user(settings)
    payload = AgentTemplateInput(
        name=request.name,
        color=request.color,
        description=request.description,
        model=request.model,
        tools=request.tools,
        system_prompt=request.system_prompt,
    )
    logger.debug(
        "update_agent payload_meta name=%s model=%s tools_count=%d",
        payload.name,
        payload.model,
        len(payload.tools),
    )
    try:
        detail = agent_template_service.update_template(user, name, payload)
    except AgentTemplateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentTemplateInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("update_agent result name=%s color=%s model=%s", detail.name, detail.color, detail.model)
    return AgentDetailResponse(
        data=AgentDetailSchema(
            name=detail.name,
            color=detail.color,
            description=detail.description,
            model=detail.model,
            system_prompt=detail.system_prompt,
            tools=detail.tools,
        )
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
@inject
def delete_agent(
    name: str,
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    settings=Depends(Provide[Container.settings]),
) -> None:
    user = _get_default_user(settings)
    try:
        agent_template_service.delete_template(user, name)
    except AgentTemplateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{name}/sessions", response_model=AgentSessionsResponse)
@inject
def list_agent_sessions(
    name: str,
    agent_template_service: AgentTemplateService = Depends(Provide[Container.agent_template_service]),
    session_query_service: SessionQueryService = Depends(Provide[Container.session_query_service]),
    settings=Depends(Provide[Container.settings]),
) -> AgentSessionsResponse:
    user = _get_default_user(settings)

    # Verify agent exists
    detail = agent_template_service.get_template(user, name)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent not found: {name}")

    try:
        sessions = session_query_service.list_sessions_by_agent_name(user.id, name)
        return AgentSessionsResponse(data=sessions)
    except SessionQueryIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    finally:
        session_query_service.close()
