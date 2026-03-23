from __future__ import annotations

import json

from app.domain import Attachment, TranscriptionStatus


class ChatInputBuilder:
    def build(self, *, message: str, attachments: list[Attachment]) -> str:
        parts: list[str] = []
        clean_message = message.strip()
        if clean_message:
            parts.append(clean_message)

        if attachments:
            attachment_payload = [
                {
                    "id": attachment.id,
                    "kind": attachment.kind.value,
                    "mimeType": attachment.mime_type,
                    "originalFilename": attachment.original_filename,
                    "workspacePath": attachment.workspace_path,
                }
                for attachment in attachments
            ]
            parts.append(
                "attachments: "
                + json.dumps(attachment_payload, ensure_ascii=False)
            )

            audio_transcriptions = [
                {
                    "attachmentId": attachment.id,
                    "workspacePath": attachment.workspace_path,
                    "text": attachment.transcription_text,
                }
                for attachment in attachments
                if attachment.transcription_status == TranscriptionStatus.COMPLETED
                and attachment.transcription_text is not None
            ]
            if audio_transcriptions:
                parts.append(
                    "audio_transcriptions: "
                    + json.dumps(audio_transcriptions, ensure_ascii=False)
                )

        return "\n\n".join(parts)
