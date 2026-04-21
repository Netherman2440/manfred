from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.users.schema import SessionDetailResponse, UserSessionsResponse
from app.container import Container
from app.services.session_query_service import (
    SessionQueryIntegrityError,
    SessionQueryNotFoundError,
    SessionQueryService,
)


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/sessions", response_model=UserSessionsResponse)
@inject
def list_user_sessions(
    user_id: str,
    session_query_service: SessionQueryService = Depends(Provide[Container.session_query_service]),
) -> UserSessionsResponse:
    try:
        return UserSessionsResponse(data=session_query_service.list_user_sessions(user_id))
    except SessionQueryIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    finally:
        session_query_service.close()


@router.get("/{user_id}/sessions/{session_id}", response_model=SessionDetailResponse)
@inject
def get_user_session_detail(
    user_id: str,
    session_id: str,
    session_query_service: SessionQueryService = Depends(Provide[Container.session_query_service]),
) -> SessionDetailResponse:
    try:
        return SessionDetailResponse(
            data=session_query_service.get_user_session_detail(user_id, session_id),
        )
    except SessionQueryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionQueryIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    finally:
        session_query_service.close()
