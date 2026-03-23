import uuid
from collections.abc import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.attachment import AttachmentModel
from app.domain import Attachment, AttachmentKind, TranscriptionStatus


class AttachmentRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        session_id: str,
        kind: AttachmentKind,
        mime_type: str,
        original_filename: str,
        stored_filename: str,
        workspace_path: str,
        size_bytes: int,
        source: str | None = None,
        agent_id: str | None = None,
        item_id: str | None = None,
        transcription_status: TranscriptionStatus = TranscriptionStatus.NOT_APPLICABLE,
        transcription_text: str | None = None,
        attachment_id: str | None = None,
    ) -> Attachment:
        entity = AttachmentModel(
            id=attachment_id or str(uuid.uuid4()),
            session_id=session_id,
            agent_id=agent_id,
            item_id=item_id,
            kind=kind.value,
            mime_type=mime_type,
            original_filename=original_filename,
            stored_filename=stored_filename,
            workspace_path=workspace_path,
            size_bytes=size_bytes,
            source=source,
            transcription_status=transcription_status.value,
            transcription_text=transcription_text,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    def get_by_id(self, attachment_id: str) -> Attachment | None:
        with self._session_factory() as session:
            entity = session.get(AttachmentModel, attachment_id)
            return self._to_domain(entity) if entity else None

    def list_by_ids(self, attachment_ids: Iterable[str]) -> list[Attachment]:
        ids = tuple(dict.fromkeys(attachment_ids))
        if not ids:
            return []

        with self._session_factory() as session:
            entities = session.scalars(
                select(AttachmentModel)
                .where(AttachmentModel.id.in_(ids))
                .order_by(AttachmentModel.created_at)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def list_by_item(self, item_id: str) -> list[Attachment]:
        with self._session_factory() as session:
            entities = session.scalars(
                select(AttachmentModel)
                .where(AttachmentModel.item_id == item_id)
                .order_by(AttachmentModel.created_at)
            ).all()
            return [self._to_domain(entity) for entity in entities]

    def update(self, attachment: Attachment) -> Attachment:
        with self._session_factory() as session:
            entity = session.get(AttachmentModel, attachment.id)
            if entity is None:
                raise ValueError(f"Attachment {attachment.id} does not exist.")

            entity.session_id = attachment.session_id
            entity.agent_id = attachment.agent_id
            entity.item_id = attachment.item_id
            entity.kind = attachment.kind.value
            entity.mime_type = attachment.mime_type
            entity.original_filename = attachment.original_filename
            entity.stored_filename = attachment.stored_filename
            entity.workspace_path = attachment.workspace_path
            entity.size_bytes = attachment.size_bytes
            entity.source = attachment.source
            entity.transcription_status = attachment.transcription_status.value
            entity.transcription_text = attachment.transcription_text
            session.commit()
            session.refresh(entity)
            return self._to_domain(entity)

    @staticmethod
    def _to_domain(entity: AttachmentModel) -> Attachment:
        return Attachment(
            id=entity.id,
            session_id=entity.session_id,
            agent_id=entity.agent_id,
            item_id=entity.item_id,
            kind=AttachmentKind(entity.kind),
            mime_type=entity.mime_type,
            original_filename=entity.original_filename,
            stored_filename=entity.stored_filename,
            workspace_path=entity.workspace_path,
            size_bytes=entity.size_bytes,
            source=entity.source,
            transcription_status=TranscriptionStatus(entity.transcription_status),
            transcription_text=entity.transcription_text,
            created_at=entity.created_at,
        )
