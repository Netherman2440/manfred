from __future__ import annotations

import json
from typing import Any

from app.domain import Item, ItemType, MessageRole
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository


class SessionQueryNotFoundError(LookupError):
    pass


class SessionQueryIntegrityError(RuntimeError):
    pass


class SessionQueryService:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        item_repository: ItemRepository,
    ) -> None:
        self.session_repository = session_repository
        self.agent_repository = agent_repository
        self.item_repository = item_repository

    def close(self) -> None:
        self.session_repository.session.close()

    def list_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        sessions = self.session_repository.list_by_user(user_id)
        response: list[dict[str, Any]] = []

        for session in sessions:
            root_agent_id = session.root_agent_id
            if not root_agent_id:
                raise SessionQueryIntegrityError(
                    f"Session {session.id} has no root_agent_id.",
                )

            root_agent = self.agent_repository.get(root_agent_id)
            if root_agent is None:
                raise SessionQueryIntegrityError(
                    f"Session {session.id} references missing root agent {root_agent_id}.",
                )

            response.append(
                {
                    "id": session.id,
                    "user_id": session.user_id,
                    "title": session.title,
                    "status": session.status.value,
                    "root_agent_id": root_agent.id,
                    "root_agent_name": root_agent.agent_name or "Manfred",
                    "root_agent_status": root_agent.status.value,
                    "waiting_for_count": len(root_agent.waiting_for),
                    "last_message_preview": self._build_last_message_preview(session.id),
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                }
            )

        return response

    def get_user_session_detail(self, user_id: str, session_id: str) -> dict[str, Any]:
        session = self.session_repository.get(session_id)
        if session is None or session.user_id != user_id:
            raise SessionQueryNotFoundError(f"Session not found for user {user_id}: {session_id}")

        root_agent_id = session.root_agent_id
        if not root_agent_id:
            raise SessionQueryIntegrityError(f"Session {session.id} has no root_agent_id.")

        root_agent = self.agent_repository.get(root_agent_id)
        if root_agent is None:
            raise SessionQueryIntegrityError(
                f"Session {session.id} references missing root agent {root_agent_id}.",
            )

        return {
            "session": {
                "id": session.id,
                "user_id": session.user_id,
                "title": session.title,
                "status": session.status.value,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
            "root_agent": {
                "id": root_agent.id,
                "name": root_agent.agent_name or "Manfred",
                "status": root_agent.status.value,
                "model": root_agent.config.model,
                "waiting_for": [
                    {
                        "call_id": entry.call_id,
                        "type": entry.type,
                        "name": entry.name,
                        "description": entry.description,
                        "agent_id": entry.agent_id,
                    }
                    for entry in root_agent.waiting_for
                ],
            },
            "items": [self._serialize_item(item) for item in self.item_repository.list_by_session(session.id)],
        }

    def _build_last_message_preview(self, session_id: str) -> str | None:
        items = self.item_repository.list_by_session(session_id)
        for item in reversed(items):
            if item.type == ItemType.MESSAGE and item.content:
                return item.content

            if item.type == ItemType.FUNCTION_CALL_OUTPUT:
                result = self._deserialize_tool_result(item.output)
                value = result.get("output")
                if value is None:
                    value = result.get("error")
                if value is not None:
                    return self._stringify_preview_value(value)
                if item.name:
                    return f"{item.name} completed"

            if item.type == ItemType.FUNCTION_CALL and item.name:
                return f"Tool call: {item.name}"

        return None

    def _serialize_item(self, item: Item) -> dict[str, Any]:
        base_payload = {
            "id": item.id,
            "sequence": item.sequence,
            "agent_id": item.agent_id,
            "created_at": item.created_at,
        }

        if item.type == ItemType.MESSAGE:
            return {
                **base_payload,
                "type": item.type.value,
                "role": item.role.value if item.role is not None else MessageRole.ASSISTANT.value,
                "content": item.content or "",
            }

        if item.type == ItemType.FUNCTION_CALL:
            return {
                **base_payload,
                "type": item.type.value,
                "call_id": item.call_id or "",
                "name": item.name or "",
                "arguments": self._deserialize_arguments(item.arguments_json),
            }

        if item.type == ItemType.FUNCTION_CALL_OUTPUT:
            return {
                **base_payload,
                "type": item.type.value,
                "call_id": item.call_id or "",
                "name": item.name or "",
                "tool_result": self._deserialize_tool_result(item.output),
                "is_error": item.is_error,
            }

        if item.type == ItemType.REASONING:
            return {
                **base_payload,
                "type": item.type.value,
                "content": item.content,
            }

        raise SessionQueryIntegrityError(f"Unsupported item type in session transcript: {item.type!s}")

    @staticmethod
    def _deserialize_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            payload = json.loads(raw_arguments)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _deserialize_tool_result(raw_output: str | None) -> dict[str, Any]:
        if not raw_output:
            return {}
        try:
            payload = json.loads(raw_output)
        except ValueError:
            return {"output": raw_output}
        if not isinstance(payload, dict):
            return {"output": raw_output}
        return payload

    @staticmethod
    def _stringify_preview_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True)
