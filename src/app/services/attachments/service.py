from __future__ import annotations

from collections.abc import Sequence

from fastapi import UploadFile

from app.db.repositories.attachment_repository import AttachmentRepository
from app.domain import Attachment, AttachmentKind, TranscriptionStatus
from app.services.audio import AudioService
from app.services.attachments.storage import AttachmentStorageService, AttachmentValidationError


class AttachmentService:
    def __init__(
        self,
        *,
        attachment_repository: AttachmentRepository,
        storage_service: AttachmentStorageService,
        audio_service: AudioService,
    ) -> None:
        self._attachment_repository = attachment_repository
        self._storage_service = storage_service
        self._audio_service = audio_service

    async def ingest_uploads(
        self,
        *,
        session_id: str,
        uploads: Sequence[UploadFile],
        source: str | None = None,
    ) -> list[Attachment]:
        if not uploads:
            raise AttachmentValidationError("At least one file must be uploaded.")

        attachments: list[Attachment] = []
        for upload in uploads:
            stored = self._storage_service.save_bytes(
                session_id,
                filename=upload.filename or "",
                content_type=upload.content_type,
                content=await upload.read(),
            )
            kind = self._classify_kind(stored.mime_type)
            transcription_status = (
                TranscriptionStatus.PENDING if kind == AttachmentKind.AUDIO else TranscriptionStatus.NOT_APPLICABLE
            )
            attachment = self._attachment_repository.create(
                session_id=session_id,
                kind=kind,
                mime_type=stored.mime_type,
                original_filename=stored.original_filename,
                stored_filename=stored.stored_filename,
                workspace_path=stored.workspace_path,
                size_bytes=stored.size_bytes,
                source=source,
                transcription_status=transcription_status,
            )
            attachments.append(await self.ensure_transcription(attachment))
            await upload.close()

        return attachments

    def list_by_item(self, item_id: str) -> list[Attachment]:
        return self._attachment_repository.list_by_item(item_id)

    def get_for_session(self, *, session_id: str, attachment_ids: Sequence[str]) -> list[Attachment]:
        if not attachment_ids:
            return []

        attachments = self._attachment_repository.list_by_ids(attachment_ids)
        found_ids = {attachment.id for attachment in attachments}
        missing_ids = [attachment_id for attachment_id in attachment_ids if attachment_id not in found_ids]
        if missing_ids:
            raise AttachmentValidationError(f"Unknown attachment ids: {', '.join(missing_ids)}")

        for attachment in attachments:
            if attachment.session_id != session_id:
                raise AttachmentValidationError(
                    f"Attachment {attachment.id} does not belong to session {session_id}."
                )

        attachment_by_id = {attachment.id: attachment for attachment in attachments}
        return [attachment_by_id[attachment_id] for attachment_id in attachment_ids]

    async def ensure_transcriptions(self, attachments: Sequence[Attachment]) -> list[Attachment]:
        hydrated: list[Attachment] = []
        for attachment in attachments:
            hydrated.append(await self.ensure_transcription(attachment))
        return hydrated

    async def ensure_transcription(self, attachment: Attachment) -> Attachment:
        if attachment.kind != AttachmentKind.AUDIO:
            return attachment
        if (
            attachment.transcription_status == TranscriptionStatus.COMPLETED
            and attachment.transcription_text is not None
        ):
            return attachment

        pending = Attachment(
            id=attachment.id,
            session_id=attachment.session_id,
            agent_id=attachment.agent_id,
            item_id=attachment.item_id,
            kind=attachment.kind,
            mime_type=attachment.mime_type,
            original_filename=attachment.original_filename,
            stored_filename=attachment.stored_filename,
            workspace_path=attachment.workspace_path,
            size_bytes=attachment.size_bytes,
            source=attachment.source,
            transcription_status=TranscriptionStatus.PENDING,
            transcription_text=attachment.transcription_text,
            created_at=attachment.created_at,
        )
        self._attachment_repository.update(pending)

        try:
            transcription_text = await self._audio_service.transcribe_audio(attachment.workspace_path)
        except Exception:
            failed = Attachment(
                id=attachment.id,
                session_id=attachment.session_id,
                agent_id=attachment.agent_id,
                item_id=attachment.item_id,
                kind=attachment.kind,
                mime_type=attachment.mime_type,
                original_filename=attachment.original_filename,
                stored_filename=attachment.stored_filename,
                workspace_path=attachment.workspace_path,
                size_bytes=attachment.size_bytes,
                source=attachment.source,
                transcription_status=TranscriptionStatus.FAILED,
                transcription_text=None,
                created_at=attachment.created_at,
            )
            self._attachment_repository.update(failed)
            raise

        completed = Attachment(
            id=attachment.id,
            session_id=attachment.session_id,
            agent_id=attachment.agent_id,
            item_id=attachment.item_id,
            kind=attachment.kind,
            mime_type=attachment.mime_type,
            original_filename=attachment.original_filename,
            stored_filename=attachment.stored_filename,
            workspace_path=attachment.workspace_path,
            size_bytes=attachment.size_bytes,
            source=attachment.source,
            transcription_status=TranscriptionStatus.COMPLETED,
            transcription_text=transcription_text,
            created_at=attachment.created_at,
        )
        return self._attachment_repository.update(completed)

    def assign_to_item(self, attachments: Sequence[Attachment], *, agent_id: str, item_id: str) -> list[Attachment]:
        assigned: list[Attachment] = []
        for attachment in attachments:
            updated = Attachment(
                id=attachment.id,
                session_id=attachment.session_id,
                agent_id=agent_id,
                item_id=item_id,
                kind=attachment.kind,
                mime_type=attachment.mime_type,
                original_filename=attachment.original_filename,
                stored_filename=attachment.stored_filename,
                workspace_path=attachment.workspace_path,
                size_bytes=attachment.size_bytes,
                source=attachment.source,
                transcription_status=attachment.transcription_status,
                transcription_text=attachment.transcription_text,
                created_at=attachment.created_at,
            )
            assigned.append(self._attachment_repository.update(updated))
        return assigned

    @staticmethod
    def _classify_kind(mime_type: str) -> AttachmentKind:
        if mime_type.startswith("image/"):
            return AttachmentKind.IMAGE
        if mime_type.startswith("audio/"):
            return AttachmentKind.AUDIO
        if mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/pdf",
            "application/xml",
            "application/zip",
        }:
            return AttachmentKind.DOCUMENT
        return AttachmentKind.OTHER
