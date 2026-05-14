from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.v1.users.schema import SessionDetailResponse, UserMeResponse, UserSessionsResponse
from app.container import Container
from app.db.base import utcnow
from app.domain.repositories import UserRepository
from app.domain.user import User
from app.services.filesystem import WorkspaceLayoutService
from app.services.session_query_service import (
    SessionQueryIntegrityError,
    SessionQueryNotFoundError,
    SessionQueryService,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMeResponse)
@inject
def get_current_user(
    workspace_layout_service: WorkspaceLayoutService = Depends(Provide[Container.workspace_layout_service]),
    settings=Depends(Provide[Container.settings]),
    db_session=Depends(Provide[Container.db_session]),
) -> UserMeResponse:
    try:
        user_repo = UserRepository(db_session)
        user = user_repo.get(settings.DEFAULT_USER_ID)
        if user is None:
            user = User(
                id=settings.DEFAULT_USER_ID,
                name=settings.DEFAULT_USER_NAME,
                api_key_hash=None,
                created_at=utcnow(),
            )
            try:
                user = user_repo.save(user)
                db_session.commit()
            except IntegrityError:
                db_session.rollback()
                user = user_repo.get(settings.DEFAULT_USER_ID)
                if user is None:
                    raise
        workspace_layout_service.ensure_user_workspace(user)
        return UserMeResponse(id=user.id, name=user.name)
    finally:
        db_session.close()


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
