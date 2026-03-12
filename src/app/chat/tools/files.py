from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field


class ListFilesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path within sandbox. Use '.' for root directory.",
    )


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path to the file within sandbox",
    )


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path to the file within sandbox",
    )
    content: str = Field(
        ...,
        description="Content to write to the file",
    )


class DeleteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path to the file to delete",
    )


class CreateDirectoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path for the new directory",
    )


class FileInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Relative path to the file or directory",
    )


class FileTools:
    def __init__(self, sandbox_dir: Path) -> None:
        self.sandbox_dir = sandbox_dir.resolve()
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

        self.tools: list[BaseTool] = [
            tool("list_files", args_schema=ListFilesArgs)(self.list_files),
            tool("read_file", args_schema=ReadFileArgs)(self.read_file),
            tool("write_file", args_schema=WriteFileArgs)(self.write_file),
            tool("delete_file", args_schema=DeleteFileArgs)(self.delete_file),
            tool("create_directory", args_schema=CreateDirectoryArgs)(self.create_directory),
            tool("file_info", args_schema=FileInfoArgs)(self.file_info),
        ]

    def _resolve_path(self, path: str) -> Path:
        candidate = (self.sandbox_dir / path).resolve()

        if candidate != self.sandbox_dir and self.sandbox_dir not in candidate.parents:
            raise ValueError("Path must stay within the sandbox directory.")

        return candidate

    def _relative_path(self, path: Path) -> str:
        if path == self.sandbox_dir:
            return "."
        return str(path.relative_to(self.sandbox_dir))

    def _serialize_stat(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": self._relative_path(path),
            "name": path.name,
            "exists": True,
            "is_file": path.is_file(),
            "is_directory": path.is_dir(),
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        }

    def list_files(self, path: str) -> dict[str, Any]:
        """List files and directories at a given path within the sandbox."""
        print(f"tool=list_files path={path}")
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path}")

        entries = []
        for item in sorted(target.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name)):
            entries.append(
                {
                    "name": item.name,
                    "path": self._relative_path(item),
                    "is_file": item.is_file(),
                    "is_directory": item.is_dir(),
                }
            )

        return {
            "path": self._relative_path(target),
            "entries": entries,
        }

    def read_file(self, path: str) -> dict[str, Any]:
        """Read the contents of a file."""
        print(f"tool=read_file path={path}")
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"Path is not a file: {path}")

        return {
            "path": self._relative_path(target),
            "content": target.read_text(encoding="utf-8"),
        }

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        """Write content to a file and create parent directories if needed."""
        print(f"tool=write_file path={path}")
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": self._relative_path(target),
            "bytes_written": len(content.encode("utf-8")),
        }

    def delete_file(self, path: str) -> dict[str, Any]:
        """Delete a file."""
        print(f"tool=delete_file path={path}")
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"Path is not a file: {path}")

        target.unlink()
        return {
            "path": self._relative_path(target),
            "deleted": True,
        }

    def create_directory(self, path: str) -> dict[str, Any]:
        """Create a directory and its parent directories if needed."""
        print(f"tool=create_directory path={path}")
        target = self._resolve_path(path)
        target.mkdir(parents=True, exist_ok=True)
        return {
            "path": self._relative_path(target),
            "created": True,
        }

    def file_info(self, path: str) -> dict[str, Any]:
        """Get metadata about a file or directory."""
        print(f"tool=file_info path={path}")
        target = self._resolve_path(path)
        if not target.exists():
            return {
                "path": path,
                "exists": False,
            }

        return self._serialize_stat(target)
