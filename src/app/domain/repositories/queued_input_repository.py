from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import QueuedInputModel
from app.domain.queued_input import QueuedInput, QueuedInputAttachment


class QueuedInputRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_pending_for_session_agent(self, session_id: str, agent_id: str) -> list[QueuedInput]:
        models = self.session.scalars(
            select(QueuedInputModel)
            .where(
                QueuedInputModel.session_id == session_id,
                QueuedInputModel.agent_id == agent_id,
                QueuedInputModel.consumed_at.is_(None),
            )
            .order_by(QueuedInputModel.accepted_at.asc(), QueuedInputModel.id.asc())
        ).all()
        return [self._to_domain(model) for model in models]

    def get_pending_count(self, session_id: str, agent_id: str) -> int:
        value = self.session.scalar(
            select(func.count(QueuedInputModel.id)).where(
                QueuedInputModel.session_id == session_id,
                QueuedInputModel.agent_id == agent_id,
                QueuedInputModel.consumed_at.is_(None),
            )
        )
        return int(value or 0)

    def save(self, queued_input: QueuedInput) -> QueuedInput:
        model = self.session.get(QueuedInputModel, queued_input.id)
        if model is None:
            model = QueuedInputModel(id=queued_input.id)
            self.session.add(model)

        model.session_id = queued_input.session_id
        model.agent_id = queued_input.agent_id
        model.message = queued_input.message
        model.attachments = [
            {
                "file_name": attachment.file_name,
                "media_type": attachment.media_type,
                "size_bytes": attachment.size_bytes,
                "path": attachment.path,
            }
            for attachment in queued_input.attachments
        ]
        model.accepted_at = queued_input.accepted_at
        model.consumed_at = queued_input.consumed_at

        self.session.flush()
        return self._to_domain(model)

    def consume(self, queued_input_id: str, consumed_at) -> QueuedInput | None:
        model = self.session.get(QueuedInputModel, queued_input_id)
        if model is None:
            return None
        model.consumed_at = consumed_at
        self.session.flush()
        return self._to_domain(model)

    def delete_pending_for_session_agent(self, session_id: str, agent_id: str) -> None:
        self.session.execute(
            delete(QueuedInputModel).where(
                QueuedInputModel.session_id == session_id,
                QueuedInputModel.agent_id == agent_id,
                QueuedInputModel.consumed_at.is_(None),
            )
        )
        self.session.flush()

    @staticmethod
    def _to_domain(model: QueuedInputModel) -> QueuedInput:
        return QueuedInput(
            id=model.id,
            session_id=model.session_id,
            agent_id=model.agent_id,
            message=model.message,
            attachments=[
                QueuedInputAttachment(
                    file_name=str(payload.get("file_name") or ""),
                    media_type=str(payload.get("media_type") or "application/octet-stream"),
                    size_bytes=int(payload.get("size_bytes") or 0),
                    path=str(payload.get("path") or ""),
                )
                for payload in model.attachments or []
            ],
            accepted_at=model.accepted_at,
            consumed_at=model.consumed_at,
        )
