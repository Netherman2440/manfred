from dataclasses import dataclass
from datetime import datetime

from app.domain.types import AttachmentKind, TranscriptionStatus


@dataclass(slots=True)
class Attachment:
    id: str
    session_id: str
    agent_id: str | None
    item_id: str | None
    kind: AttachmentKind
    mime_type: str
    original_filename: str
    stored_filename: str
    workspace_path: str
    size_bytes: int
    source: str | None
    transcription_status: TranscriptionStatus
    transcription_text: str | None
    created_at: datetime
