import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.domain import Attachment, AttachmentKind, TranscriptionStatus
from app.services.attachments import AttachmentService, AttachmentStorageService, AttachmentValidationError
from app.services.audio import AudioService


class FakeUpload:
    def __init__(self, *, filename: str, content_type: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self.closed = False

    async def read(self) -> bytes:
        return self._content

    async def close(self) -> None:
        self.closed = True


class StubAudioService(AudioService):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def transcribe_audio(self, path: str) -> str:
        self.calls.append(path)
        return "Przykladowa transkrypcja"

    async def generate_audio(self, text: str) -> str:
        raise NotImplementedError


class InMemoryAttachmentRepository:
    def __init__(self) -> None:
        self._store: dict[str, Attachment] = {}
        self._counter = 0

    def create(self, **kwargs: object) -> Attachment:
        self._counter += 1
        attachment = Attachment(
            id=f"att-{self._counter}",
            session_id=str(kwargs["session_id"]),
            agent_id=kwargs.get("agent_id"),
            item_id=kwargs.get("item_id"),
            kind=kwargs["kind"],
            mime_type=str(kwargs["mime_type"]),
            original_filename=str(kwargs["original_filename"]),
            stored_filename=str(kwargs["stored_filename"]),
            workspace_path=str(kwargs["workspace_path"]),
            size_bytes=int(kwargs["size_bytes"]),
            source=kwargs.get("source"),
            transcription_status=kwargs.get("transcription_status", TranscriptionStatus.NOT_APPLICABLE),
            transcription_text=kwargs.get("transcription_text"),
            created_at=datetime.now(UTC),
        )
        self._store[attachment.id] = attachment
        return attachment

    def update(self, attachment: Attachment) -> Attachment:
        self._store[attachment.id] = attachment
        return attachment

    def list_by_ids(self, attachment_ids: list[str] | tuple[str, ...]) -> list[Attachment]:
        return [self._store[attachment_id] for attachment_id in attachment_ids if attachment_id in self._store]

    def list_by_item(self, item_id: str) -> list[Attachment]:
        return [attachment for attachment in self._store.values() if attachment.item_id == item_id]


class AttachmentStorageServiceTest(unittest.TestCase):
    def test_save_bytes_writes_file_to_session_input_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            service = AttachmentStorageService(
                workspace_root=workspace_root,
                max_size_bytes=1024,
            )

            stored = service.save_bytes(
                "sess-123",
                filename="../report final.txt",
                content_type="text/plain",
                content=b"hello",
            )

            self.assertEqual(stored.original_filename, "report_final.txt")
            self.assertTrue(stored.workspace_path.startswith("input/sess-123/"))
            self.assertEqual((workspace_root / stored.workspace_path).read_bytes(), b"hello")


class AttachmentServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_audio_upload_transcribes_file_and_marks_attachment_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AttachmentService(
                attachment_repository=InMemoryAttachmentRepository(),
                storage_service=AttachmentStorageService(
                    workspace_root=Path(tmp_dir),
                    max_size_bytes=1024,
                ),
                audio_service=StubAudioService(),
            )

            upload = FakeUpload(
                filename="voice message.webm",
                content_type="audio/webm",
                content=b"audio-bytes",
            )
            attachments = await service.ingest_uploads(
                session_id="sess-123",
                uploads=[upload],
                source="voice_recording",
            )

            attachment = attachments[0]
            self.assertEqual(attachment.kind, AttachmentKind.AUDIO)
            self.assertEqual(attachment.transcription_status, TranscriptionStatus.COMPLETED)
            self.assertEqual(attachment.transcription_text, "Przykladowa transkrypcja")
            self.assertTrue(attachment.workspace_path.startswith("input/sess-123/"))
            self.assertTrue(upload.closed)

    async def test_get_for_session_rejects_attachment_from_different_session(self) -> None:
        repository = InMemoryAttachmentRepository()
        attachment = repository.create(
            session_id="sess-a",
            kind=AttachmentKind.DOCUMENT,
            mime_type="text/plain",
            original_filename="note.txt",
            stored_filename="stored-note.txt",
            workspace_path="input/sess-a/stored-note.txt",
            size_bytes=4,
            transcription_status=TranscriptionStatus.NOT_APPLICABLE,
        )
        service = AttachmentService(
            attachment_repository=repository,
            storage_service=AttachmentStorageService(
                workspace_root=Path(tempfile.mkdtemp()),
                max_size_bytes=1024,
            ),
            audio_service=StubAudioService(),
        )

        with self.assertRaises(AttachmentValidationError):
            service.get_for_session(session_id="sess-b", attachment_ids=[attachment.id])
