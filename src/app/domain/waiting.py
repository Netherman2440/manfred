from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

WaitingForType = Literal["tool", "agent", "human"]


@dataclass(slots=True, frozen=True)
class WaitingForEntry:
    call_id: str
    type: WaitingForType
    name: str
    description: str | None = None
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> WaitingForEntry | None:
        if not isinstance(payload, dict):
            return None

        call_id = payload.get("call_id")
        wait_type = payload.get("type")
        name = payload.get("name")
        description = payload.get("description")
        agent_id = payload.get("agent_id")

        if not isinstance(call_id, str) or not call_id:
            return None
        if wait_type not in {"tool", "agent", "human"}:
            return None
        if not isinstance(name, str) or not name:
            return None
        if description is not None and not isinstance(description, str):
            description = str(description)
        if agent_id is not None and not isinstance(agent_id, str):
            agent_id = str(agent_id)

        return cls(
            call_id=call_id,
            type=wait_type,
            name=name,
            description=description,
            agent_id=agent_id,
        )
