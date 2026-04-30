from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeAlias


LineSpec: TypeAlias = str | dict[str, int] | list[int] | None


@dataclass(slots=True, frozen=True)
class FilesystemMount:
    name: str
    root: Path


@dataclass(slots=True, frozen=True)
class FilesystemSubject:
    user_id: str | None
    session_id: str
    agent_id: str
    user_name: str | None = None


@dataclass(slots=True, frozen=True)
class ResolvedFilesystemPath:
    mount: FilesystemMount
    requested_path: str
    relative_path: PurePosixPath
    absolute_path: Path


@dataclass(slots=True, frozen=True)
class FilesystemAccessRequest:
    subject: FilesystemSubject
    tool_name: str
    operation: str
    requested_path: str
    resolved_path: ResolvedFilesystemPath
    target_path: str | None = None
    target_resolved_path: ResolvedFilesystemPath | None = None


@dataclass(slots=True, frozen=True)
class FilesystemAccessDecision:
    allowed: bool
    message: str | None = None
    error_code: str | None = None
    effective_path: Path | None = None
    target_effective_path: Path | None = None


@dataclass(slots=True, frozen=True)
class FilesystemReadRequest:
    subject: FilesystemSubject
    tool_name: str
    path: str
    mode: Literal["auto", "tree", "list", "content"] = "auto"
    lines: LineSpec = None
    depth: int = 2
    limit: int = 200
    offset: int = 0
    details: bool = False
    types: list[str] | None = None
    glob: list[str] | str | None = None
    exclude: list[str] | str | None = None
    respect_ignore: bool = True


@dataclass(slots=True, frozen=True)
class FilesystemSearchRequest:
    subject: FilesystemSubject
    tool_name: str
    path: str
    query: str
    pattern_mode: Literal["literal", "regex", "fuzzy"] = "literal"
    target: Literal["all", "filename", "content"] = "all"
    case_insensitive: bool = False
    whole_word: bool = False
    multiline: bool = False
    depth: int = 8
    types: list[str] | None = None
    glob: list[str] | str | None = None
    exclude: list[str] | str | None = None
    max_results: int = 50
    respect_ignore: bool = True


@dataclass(slots=True, frozen=True)
class FilesystemWriteRequest:
    subject: FilesystemSubject
    tool_name: str
    path: str
    operation: Literal["create", "update"]
    content: str | None = None
    action: Literal["replace", "insert_before", "insert_after", "delete_lines"] = "replace"
    lines: LineSpec = None
    checksum: str | None = None
    dry_run: bool = False
    create_dirs: bool = False


@dataclass(slots=True, frozen=True)
class FilesystemManageRequest:
    subject: FilesystemSubject
    tool_name: str
    path: str
    operation: Literal["delete", "rename", "move", "copy", "mkdir", "stat"]
    target: str | None = None
    recursive: bool = False
    force: bool = False


class FilesystemToolError(Exception):
    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def as_text(self) -> str:
        if not self.hint:
            return self.message
        return f"{self.message} Hint: {self.hint}"
