from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class User:
    id: str
    name: str
    api_key_hash: str | None
    created_at: datetime
