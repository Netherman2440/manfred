from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from app.services.filesystem.paths import FilesystemPathResolver
from app.services.filesystem.policy import FilesystemAccessPolicy
from app.services.filesystem.types import (
    FilesystemAccessRequest,
    FilesystemManageRequest,
    FilesystemReadRequest,
    FilesystemSearchRequest,
    FilesystemSubject,
    FilesystemToolError,
    FilesystemWriteRequest,
    ResolvedFilesystemPath,
)

DEFAULT_IGNORED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
}


class AgentFilesystemService:
    def __init__(
        self,
        *,
        path_resolver: FilesystemPathResolver,
        access_policy: FilesystemAccessPolicy,
        max_file_size: int,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.path_resolver = path_resolver
        self.access_policy = access_policy
        self.max_file_size = max_file_size
        self.exclude_patterns = self._normalize_patterns(exclude_patterns)

    def list_mounts(self) -> list:
        return self.path_resolver.mounts

    def generate_filesystem_instructions(self) -> str:
        mount_lines = []
        for mount in sorted(self.list_mounts(), key=lambda m: m.name):
            if mount.name == "workspace":
                mount_lines.append("- workspace/      — your session workspace (read/write)")
                mount_lines.append("  - workspace/files/        — working files")
                mount_lines.append("  - workspace/attachments/  — session attachments")
                mount_lines.append("  - workspace/plan.md       — session plan")
            else:
                descriptions = {
                    "agents": "your agent definitions",
                    "workflows": "your workflow definitions",
                    "skills": "your skill definitions",
                    "shared": "shared knowledge base",
                }
                desc = descriptions.get(mount.name, mount.name)
                mount_lines.append(f"- {mount.name}/      — {desc}")

        mounts_block = "\n".join(mount_lines)
        return (
            "<filesystem>\n"
            'Your file tools operate on a sandboxed filesystem. All paths are relative — never use a leading "/".\n'
            "\n"
            'Available mounts (use fs_read(".") to list them):\n'
            f"{mounts_block}\n"
            "\n"
            "Rules:\n"
            "1. Read a file before modifying it (checksum required for writes)\n"
            "2. Use workspace/ for all session output\n"
            "3. agents/, workflows/, skills/ contain definitions — prefer read over write\n"
            "</filesystem>"
        )

    async def read(self, request: FilesystemReadRequest) -> dict[str, Any]:
        normalized_path = self.path_resolver.normalize_virtual_path(request.path)
        if normalized_path == ".":
            return self._read_root_listing()

        resolved_path = self.path_resolver.resolve(normalized_path)
        effective_path = await self._authorize(
            subject=request.subject,
            tool_name=request.tool_name,
            operation="read",
            requested_path=normalized_path,
            resolved_path=resolved_path,
        )

        mode = request.mode
        if mode == "auto":
            if effective_path.exists() and effective_path.is_file():
                mode = "content"
            else:
                mode = "list"

        if mode == "content":
            return self._read_file_content(
                requested_path=normalized_path,
                display_base=normalized_path,
                effective_path=effective_path,
                lines=request.lines,
                offset=request.offset,
            )
        if mode == "tree":
            return self._read_directory(
                requested_path=normalized_path,
                display_base=normalized_path,
                effective_path=effective_path,
                depth=request.depth,
                limit=request.limit,
                offset=request.offset,
                details=request.details,
                recursive=True,
                types=request.types,
                glob=request.glob,
                exclude=request.exclude,
                respect_ignore=request.respect_ignore,
            )
        if mode == "list":
            return self._read_directory(
                requested_path=normalized_path,
                display_base=normalized_path,
                effective_path=effective_path,
                depth=1,
                limit=request.limit,
                offset=request.offset,
                details=request.details,
                recursive=False,
                types=request.types,
                glob=request.glob,
                exclude=request.exclude,
                respect_ignore=request.respect_ignore,
            )

        raise FilesystemToolError(f"Unsupported read mode: {request.mode}")

    async def search(self, request: FilesystemSearchRequest) -> dict[str, Any]:
        normalized_path = self.path_resolver.normalize_virtual_path(request.path)
        if not request.query.strip():
            raise FilesystemToolError("query must be a non-empty string")
        roots: list[tuple[str, Path]] = []

        if normalized_path == ".":
            for mount in self.path_resolver.mounts:
                resolved_mount = self.path_resolver.build_mount_root(mount)
                try:
                    effective_path = await self._authorize(
                        subject=request.subject,
                        tool_name=request.tool_name,
                        operation="search",
                        requested_path=mount.name,
                        resolved_path=resolved_mount,
                    )
                except FilesystemToolError:
                    continue
                roots.append((mount.name, effective_path))
        else:
            resolved_path = self.path_resolver.resolve(normalized_path)
            effective_path = await self._authorize(
                subject=request.subject,
                tool_name=request.tool_name,
                operation="search",
                requested_path=normalized_path,
                resolved_path=resolved_path,
            )
            roots.append((normalized_path, effective_path))

        results: list[dict[str, Any]] = []
        for display_base, root_path in roots:
            if len(results) >= request.max_results:
                break
            for result in self._search_in_root(
                display_base=display_base,
                root_path=root_path,
                request=request,
            ):
                results.append(result)
                if len(results) >= request.max_results:
                    break

        return {
            "path": normalized_path,
            "query": request.query,
            "patternMode": request.pattern_mode,
            "target": request.target,
            "results": results,
            "count": len(results),
        }

    async def write(self, request: FilesystemWriteRequest) -> dict[str, Any]:
        normalized_path = self.path_resolver.normalize_virtual_path(request.path)
        resolved_path = self.path_resolver.resolve(normalized_path)
        effective_path = await self._authorize(
            subject=request.subject,
            tool_name=request.tool_name,
            operation=request.operation,
            requested_path=normalized_path,
            resolved_path=resolved_path,
        )

        if request.operation == "create":
            return self._create_file(
                requested_path=normalized_path,
                effective_path=effective_path,
                content=request.content or "",
                dry_run=request.dry_run,
                create_dirs=request.create_dirs,
            )

        if request.operation == "update":
            return self._update_file(
                requested_path=normalized_path,
                effective_path=effective_path,
                content=request.content,
                action=request.action,
                lines=request.lines,
                checksum=request.checksum,
                dry_run=request.dry_run,
            )

        raise FilesystemToolError(f"Unsupported write operation: {request.operation}")

    async def manage(self, request: FilesystemManageRequest) -> dict[str, Any]:
        normalized_path = self.path_resolver.normalize_virtual_path(request.path)
        resolved_path = self.path_resolver.resolve(normalized_path)
        target_resolved_path = (
            self.path_resolver.resolve(self.path_resolver.normalize_virtual_path(request.target))
            if request.target
            else None
        )
        effective_path, target_effective_path = await self._authorize_with_target(
            subject=request.subject,
            tool_name=request.tool_name,
            operation=request.operation,
            requested_path=normalized_path,
            resolved_path=resolved_path,
            target_path=request.target,
            target_resolved_path=target_resolved_path,
        )

        if request.operation == "stat":
            return self._stat_path(normalized_path, effective_path)
        if request.operation == "mkdir":
            return self._mkdir(normalized_path, effective_path, recursive=request.recursive)
        if request.operation == "delete":
            return self._delete(
                requested_path=normalized_path,
                resolved_path=resolved_path,
                effective_path=effective_path,
                recursive=request.recursive,
                force=request.force,
            )
        if request.operation in {"rename", "move"}:
            if request.target is None or target_effective_path is None:
                raise FilesystemToolError("target is required for rename and move operations.")
            return self._move(
                requested_path=normalized_path,
                target_path=request.target,
                source_path=effective_path,
                target_effective_path=target_effective_path,
            )
        if request.operation == "copy":
            if request.target is None or target_effective_path is None:
                raise FilesystemToolError("target is required for copy operations.")
            return self._copy(
                requested_path=normalized_path,
                target_path=request.target,
                source_path=effective_path,
                target_effective_path=target_effective_path,
                recursive=request.recursive,
                force=request.force,
            )

        raise FilesystemToolError(f"Unsupported manage operation: {request.operation}")

    async def _authorize(
        self,
        *,
        subject,
        tool_name: str,
        operation: str,
        requested_path: str,
        resolved_path: ResolvedFilesystemPath,
    ) -> Path:
        decision = await self.access_policy.authorize(
            FilesystemAccessRequest(
                subject=subject,
                tool_name=tool_name,
                operation=operation,
                requested_path=requested_path,
                resolved_path=resolved_path,
            )
        )
        if not decision.allowed or decision.effective_path is None:
            raise FilesystemToolError(decision.message or "Filesystem access denied.")
        await self._reject_if_excluded(requested_path)
        return decision.effective_path

    async def _authorize_with_target(
        self,
        *,
        subject,
        tool_name: str,
        operation: str,
        requested_path: str,
        resolved_path: ResolvedFilesystemPath,
        target_path: str | None,
        target_resolved_path: ResolvedFilesystemPath | None,
    ) -> tuple[Path, Path | None]:
        decision = await self.access_policy.authorize(
            FilesystemAccessRequest(
                subject=subject,
                tool_name=tool_name,
                operation=operation,
                requested_path=requested_path,
                resolved_path=resolved_path,
                target_path=target_path,
                target_resolved_path=target_resolved_path,
            )
        )
        if not decision.allowed or decision.effective_path is None:
            raise FilesystemToolError(decision.message or "Filesystem access denied.")
        await self._reject_if_excluded(requested_path)
        if target_path is not None:
            await self._reject_if_excluded(target_path)
        return decision.effective_path, decision.target_effective_path

    def _read_root_listing(self) -> dict[str, Any]:
        entries = [
            {"name": mount.name, "path": mount.name, "type": "directory"}
            for mount in sorted(self.path_resolver.mounts, key=lambda item: item.name)
            if not self._is_excluded_path(mount.name, mount.name.rsplit("/", 1)[-1])
        ]
        return {"path": ".", "mode": "list", "kind": "roots", "entries": entries}

    def _read_file_content(
        self,
        *,
        requested_path: str,
        display_base: str,
        effective_path: Path,
        lines: Any | None,
        offset: int,
    ) -> dict[str, Any]:
        if not effective_path.exists():
            raise FilesystemToolError(f"Path not found: {requested_path}")
        if effective_path.is_dir():
            raise FilesystemToolError(f"Path is a directory, not a file: {requested_path}")

        raw_bytes = effective_path.read_bytes()
        checksum = self._checksum(raw_bytes)
        if len(raw_bytes) > self.max_file_size:
            raise FilesystemToolError(
                f"File '{requested_path}' exceeds MAX_FILE_SIZE ({self.max_file_size} bytes).",
                hint="Use read_file with mode='list' or search_file to inspect large files.",
            )

        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "path": display_base,
                "mode": "content",
                "kind": "binary",
                "size": len(raw_bytes),
                "checksum": checksum,
            }

        selected_lines = self._select_lines(text, lines, offset=offset)
        return {
            "path": display_base,
            "mode": "content",
            "kind": "file",
            "size": len(raw_bytes),
            "checksum": checksum,
            "lineCount": len(text.splitlines()),
            "content": selected_lines,
        }

    def _read_directory(
        self,
        *,
        requested_path: str,
        display_base: str,
        effective_path: Path,
        depth: int,
        limit: int,
        offset: int,
        details: bool,
        recursive: bool,
        types: list[str] | None,
        glob: list[str] | str | None,
        exclude: list[str] | str | None,
        respect_ignore: bool,
    ) -> dict[str, Any]:
        if not effective_path.exists():
            if requested_path == display_base:
                return {
                    "path": display_base,
                    "mode": "tree" if recursive else "list",
                    "kind": "directory",
                    "entries": [],
                }
            raise FilesystemToolError(f"Path not found: {requested_path}")
        if not effective_path.is_dir():
            raise FilesystemToolError(f"Path is not a directory: {requested_path}")

        entries = self._collect_directory_entries(
            display_base=display_base,
            base_path=effective_path,
            current_path=effective_path,
            current_depth=0,
            max_depth=max(depth, 1),
            recursive=recursive,
            limit=max(limit, 1),
            details=details,
            types=types,
            glob=glob,
            exclude=exclude,
            respect_ignore=respect_ignore,
        )
        if offset > 0:
            entries = entries[offset:]
        return {
            "path": display_base,
            "mode": "tree" if recursive else "list",
            "kind": "directory",
            "entries": entries,
        }

    def _collect_directory_entries(
        self,
        *,
        display_base: str,
        base_path: Path,
        current_path: Path,
        current_depth: int,
        max_depth: int,
        recursive: bool,
        limit: int,
        details: bool,
        types: list[str] | None,
        glob: list[str] | str | None,
        exclude: list[str] | str | None,
        respect_ignore: bool,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []

        if current_depth >= max_depth:
            return entries

        try:
            children = sorted(current_path.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower()))
        except FileNotFoundError:
            return entries

        for child in children:
            relative_path = child.relative_to(base_path).as_posix()
            if respect_ignore and self._is_ignored(relative_path):
                continue
            entry_path = self._join_display_path(display_base, relative_path)
            if self._is_excluded_path(entry_path, child.name):
                continue
            if not self._matches_filters(
                entry_path=entry_path,
                filename=child.name,
                is_dir=child.is_dir(),
                types=types,
                glob=glob,
                exclude=exclude,
            ):
                continue

            entry: dict[str, Any] = {
                "name": child.name,
                "path": entry_path,
                "type": "directory" if child.is_dir() else "file",
                "depth": current_depth + 1,
            }
            if details:
                stat_result = child.stat()
                entry["size"] = stat_result.st_size
                entry["modifiedAt"] = stat_result.st_mtime
                entry["isSymlink"] = child.is_symlink()

            entries.append(entry)
            if len(entries) >= limit:
                break

            if recursive and child.is_dir():
                nested_entries = self._collect_directory_entries(
                    display_base=display_base,
                    base_path=base_path,
                    current_path=child,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    recursive=recursive,
                    limit=limit - len(entries),
                    details=details,
                    types=types,
                    glob=glob,
                    exclude=exclude,
                    respect_ignore=respect_ignore,
                )
                entries.extend(nested_entries)
                if len(entries) >= limit:
                    break

        return entries

    def _search_in_root(
        self,
        *,
        display_base: str,
        root_path: Path,
        request: FilesystemSearchRequest,
    ) -> Iterable[dict[str, Any]]:
        if not root_path.exists():
            return []
        if root_path.is_file():
            return self._search_file(
                display_base=display_base,
                file_path=root_path,
                request=request,
            )

        results: list[dict[str, Any]] = []
        for current_root, dirnames, filenames in os.walk(root_path):
            current_path = Path(current_root)
            relative_dir = "." if current_path == root_path else current_path.relative_to(root_path).as_posix()
            depth = 0 if relative_dir == "." else len(relative_dir.split("/"))
            if depth > request.depth:
                dirnames[:] = []
                continue

            if request.respect_ignore:
                dirnames[:] = [name for name in dirnames if not self._is_ignored(self._join_rel(relative_dir, name))]
                filenames = [name for name in filenames if not self._is_ignored(self._join_rel(relative_dir, name))]

            dirnames[:] = [
                name
                for name in dirnames
                if not self._is_excluded_path(
                    self._join_display_path(display_base, self._join_rel(relative_dir, name)),
                    name,
                )
            ]
            filenames = [
                name
                for name in filenames
                if not self._is_excluded_path(
                    self._join_display_path(display_base, self._join_rel(relative_dir, name)),
                    name,
                )
            ]

            for dirname in list(dirnames):
                dir_display_path = self._join_display_path(display_base, self._join_rel(relative_dir, dirname))
                if self._matches_filename(dirname, request):
                    results.append(
                        {
                            "path": dir_display_path,
                            "type": "directory",
                            "match": "filename",
                        }
                    )
                    if len(results) >= request.max_results:
                        return results

            for filename in filenames:
                file_path = current_path / filename
                file_results = self._search_file(
                    display_base=display_base,
                    file_path=file_path,
                    request=request,
                    relative_dir=relative_dir,
                )
                for result in file_results:
                    results.append(result)
                    if len(results) >= request.max_results:
                        return results

        return results

    def _search_file(
        self,
        *,
        display_base: str,
        file_path: Path,
        request: FilesystemSearchRequest,
        relative_dir: str = ".",
    ) -> list[dict[str, Any]]:
        relative_path = self._join_rel(relative_dir, file_path.name)
        display_path = self._join_display_path(display_base, relative_path)
        if not self._matches_filters(
            entry_path=display_path,
            filename=file_path.name,
            is_dir=False,
            types=request.types,
            glob=request.glob,
            exclude=request.exclude,
        ):
            return []

        results: list[dict[str, Any]] = []
        if request.target in {"all", "filename"} and self._matches_filename(file_path.name, request):
            results.append(
                {
                    "path": display_path,
                    "type": "file",
                    "match": "filename",
                }
            )

        if request.target not in {"all", "content"}:
            return results
        if not file_path.exists() or file_path.stat().st_size > self.max_file_size:
            return results

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return results

        matches = self._find_content_matches(text, request)
        if matches:
            results.append(
                {
                    "path": display_path,
                    "type": "file",
                    "match": "content",
                    "matches": matches,
                }
            )

        return results

    def _create_file(
        self,
        *,
        requested_path: str,
        effective_path: Path,
        content: str,
        dry_run: bool,
        create_dirs: bool,
    ) -> dict[str, Any]:
        if effective_path.exists():
            raise FilesystemToolError(f"File already exists: {requested_path}")
        if not create_dirs and not effective_path.parent.exists():
            raise FilesystemToolError(
                f"Parent directory does not exist for '{requested_path}'.",
                hint="Retry with createDirs=true to create missing directories.",
            )

        if create_dirs:
            effective_path.parent.mkdir(parents=True, exist_ok=True)

        diff = self._build_diff("", content, requested_path)
        if not dry_run:
            effective_path.write_text(content, encoding="utf-8")

        return {
            "path": requested_path,
            "operation": "create",
            "dryRun": dry_run,
            "diff": diff,
            "newChecksum": self._checksum(content.encode("utf-8")),
        }

    def _update_file(
        self,
        *,
        requested_path: str,
        effective_path: Path,
        content: str | None,
        action: str,
        lines: Any | None,
        checksum: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        if not effective_path.exists():
            raise FilesystemToolError(f"Path not found: {requested_path}")
        if effective_path.is_dir():
            raise FilesystemToolError(f"Path is a directory, not a file: {requested_path}")

        current_text = effective_path.read_text(encoding="utf-8")
        current_checksum = self._checksum(current_text.encode("utf-8"))
        if checksum and checksum != current_checksum:
            raise FilesystemToolError(
                f"Checksum mismatch for '{requested_path}'.",
                hint=f"Read the file again and retry with checksum={current_checksum}.",
            )

        new_text = self._apply_update_action(current_text, content, action, lines)
        diff = self._build_diff(current_text, new_text, requested_path)
        new_checksum = self._checksum(new_text.encode("utf-8"))

        if not dry_run:
            effective_path.write_text(new_text, encoding="utf-8")

        return {
            "path": requested_path,
            "operation": "update",
            "action": action,
            "dryRun": dry_run,
            "diff": diff,
            "newChecksum": new_checksum,
        }

    def _stat_path(self, requested_path: str, effective_path: Path) -> dict[str, Any]:
        if not effective_path.exists():
            raise FilesystemToolError(f"Path not found: {requested_path}")

        stat_result = effective_path.stat()
        payload: dict[str, Any] = {
            "path": requested_path,
            "type": "directory" if effective_path.is_dir() else "file",
            "size": stat_result.st_size,
            "modifiedAt": stat_result.st_mtime,
            "isSymlink": effective_path.is_symlink(),
        }
        if effective_path.is_file():
            payload["checksum"] = self._checksum(effective_path.read_bytes())
        return payload

    def _mkdir(self, requested_path: str, effective_path: Path, *, recursive: bool) -> dict[str, Any]:
        effective_path.mkdir(parents=recursive, exist_ok=True)
        return {"path": requested_path, "operation": "mkdir", "created": True}

    def _delete(
        self,
        *,
        requested_path: str,
        resolved_path: ResolvedFilesystemPath,
        effective_path: Path,
        recursive: bool,
        force: bool,
    ) -> dict[str, Any]:
        if resolved_path.relative_path.as_posix() in {".", ""}:
            raise FilesystemToolError(f"Refusing to delete mount root '{requested_path}'.")
        if not effective_path.exists():
            if force:
                return {"path": requested_path, "operation": "delete", "deleted": False}
            raise FilesystemToolError(f"Path not found: {requested_path}")

        if effective_path.is_dir():
            if not recursive:
                raise FilesystemToolError(f"Directory delete requires recursive=true for '{requested_path}'.")
            shutil.rmtree(effective_path)
        else:
            effective_path.unlink()

        return {"path": requested_path, "operation": "delete", "deleted": True}

    def _move(
        self,
        *,
        requested_path: str,
        target_path: str,
        source_path: Path,
        target_effective_path: Path,
    ) -> dict[str, Any]:
        if not source_path.exists():
            raise FilesystemToolError(f"Path not found: {requested_path}")
        target_effective_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(target_effective_path))
        return {"path": requested_path, "target": target_path, "operation": "move", "moved": True}

    def _copy(
        self,
        *,
        requested_path: str,
        target_path: str,
        source_path: Path,
        target_effective_path: Path,
        recursive: bool,
        force: bool,
    ) -> dict[str, Any]:
        if not source_path.exists():
            raise FilesystemToolError(f"Path not found: {requested_path}")
        if target_effective_path.exists():
            if not force:
                raise FilesystemToolError(
                    f"Target already exists: {target_path}",
                    hint="Retry with force=true to overwrite the target.",
                )
            if target_effective_path.is_dir():
                shutil.rmtree(target_effective_path)
            else:
                target_effective_path.unlink()

        target_effective_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            if not recursive:
                raise FilesystemToolError(f"Directory copy requires recursive=true for '{requested_path}'.")
            shutil.copytree(source_path, target_effective_path)
        else:
            shutil.copy2(source_path, target_effective_path)

        return {"path": requested_path, "target": target_path, "operation": "copy", "copied": True}

    def _apply_update_action(
        self,
        current_text: str,
        content: str | None,
        action: str,
        lines: Any | None,
    ) -> str:
        if action == "replace" and lines is None:
            return content or ""

        line_range = self._parse_single_line_range(lines)
        if line_range is None:
            raise FilesystemToolError("lines is required for the selected write action.")

        start, end = line_range
        source_lines = current_text.splitlines(keepends=True)
        if start < 1 or end < start or end > max(len(source_lines), 1):
            raise FilesystemToolError("Requested line range is outside the file bounds.")

        replacement_lines = [] if content is None else content.splitlines(keepends=True)
        if content and not content.endswith("\n"):
            replacement_lines = (content + "\n").splitlines(keepends=True)

        start_index = start - 1
        end_index = end

        if action == "replace":
            updated_lines = source_lines[:start_index] + replacement_lines + source_lines[end_index:]
        elif action == "insert_before":
            updated_lines = source_lines[:start_index] + replacement_lines + source_lines[start_index:]
        elif action == "insert_after":
            updated_lines = source_lines[:end_index] + replacement_lines + source_lines[end_index:]
        elif action == "delete_lines":
            updated_lines = source_lines[:start_index] + source_lines[end_index:]
        else:
            raise FilesystemToolError(f"Unsupported write action: {action}")

        return "".join(updated_lines)

    def _find_content_matches(self, text: str, request: FilesystemSearchRequest) -> list[dict[str, Any]]:
        snippets: list[dict[str, Any]] = []
        if request.pattern_mode == "fuzzy":
            for line_number, line in enumerate(text.splitlines(), start=1):
                if self._matches_fuzzy(line, request.query, request.case_insensitive):
                    snippets.append({"line": line_number, "text": line})
                    if len(snippets) >= 3:
                        break
            return snippets

        flags = 0
        if request.case_insensitive:
            flags |= re.IGNORECASE
        if request.multiline:
            flags |= re.MULTILINE | re.DOTALL

        pattern = request.query if request.pattern_mode == "regex" else re.escape(request.query)
        if request.whole_word:
            pattern = rf"\b{pattern}\b"

        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise FilesystemToolError(f"Invalid regex pattern: {exc.msg}") from exc

        lines = text.splitlines()
        for match in compiled.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            line_index = line_number - 1
            line_text = lines[line_index] if 0 <= line_index < len(lines) else ""
            snippets.append({"line": line_number, "text": line_text})
            if len(snippets) >= 3:
                break
        return snippets

    def _matches_filename(self, filename: str, request: FilesystemSearchRequest) -> bool:
        if request.pattern_mode == "fuzzy":
            return self._matches_fuzzy(filename, request.query, request.case_insensitive)

        flags = re.IGNORECASE if request.case_insensitive else 0
        pattern = request.query if request.pattern_mode == "regex" else re.escape(request.query)
        if request.whole_word:
            pattern = rf"\b{pattern}\b"
        return re.search(pattern, filename, flags) is not None

    @staticmethod
    def _matches_fuzzy(value: str, query: str, case_insensitive: bool) -> bool:
        haystack = value.lower() if case_insensitive else value
        needle = query.lower() if case_insensitive else query
        iterator = iter(haystack)
        return all(character in iterator for character in needle)

    def _matches_filters(
        self,
        *,
        entry_path: str,
        filename: str,
        is_dir: bool,
        types: list[str] | None,
        glob: list[str] | str | None,
        exclude: list[str] | str | None,
    ) -> bool:
        normalized_types = {item.lower() for item in types or []}
        if normalized_types:
            if is_dir and normalized_types.isdisjoint({"dir", "directory"}):
                return False
            if not is_dir and normalized_types.isdisjoint({"file", "text", "binary"}):
                return False

        include_patterns = self._normalize_patterns(glob)
        if include_patterns and not any(
            self._matches_glob_pattern(entry_path, pattern) or self._matches_glob_pattern(filename, pattern)
            for pattern in include_patterns
        ):
            return False

        if self._is_excluded_path(entry_path, filename):
            return False

        exclude_patterns = self._normalize_patterns(exclude)
        if exclude_patterns and any(
            self._matches_glob_pattern(entry_path, pattern) or self._matches_glob_pattern(filename, pattern)
            for pattern in exclude_patterns
        ):
            return False

        return True

    async def _reject_if_excluded(self, requested_path: str) -> None:
        if self._is_excluded_path(requested_path, requested_path.rsplit("/", 1)[-1]):
            raise FilesystemToolError(f"Path '{requested_path}' is excluded by filesystem policy.")

    def _is_excluded_path(self, entry_path: str, filename: str | None = None) -> bool:
        if not self.exclude_patterns:
            return False

        candidates = [entry_path]
        if filename:
            candidates.append(filename)

        return any(
            self._matches_glob_pattern(candidate, pattern)
            for candidate in candidates
            for pattern in self.exclude_patterns
        )

    @staticmethod
    def _normalize_patterns(value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [item for item in value if isinstance(item, str) and item]

    @staticmethod
    def _matches_glob_pattern(value: str, pattern: str) -> bool:
        normalized_pattern = pattern.rstrip("/")
        if fnmatch(value, normalized_pattern):
            return True
        if normalized_pattern.endswith("/**"):
            return value == normalized_pattern[:-3].rstrip("/")
        return False

    @staticmethod
    def _checksum(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _join_display_path(base: str, relative_path: str) -> str:
        if relative_path in {"", "."}:
            return base
        return f"{base.rstrip('/')}/{relative_path}"

    @staticmethod
    def _join_rel(base: str, child: str) -> str:
        if base in {"", "."}:
            return child
        return f"{base}/{child}"

    @staticmethod
    def _build_diff(old_text: str, new_text: str, path_label: str) -> str:
        return "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=path_label,
                tofile=path_label,
            )
        )

    @staticmethod
    def _is_ignored(relative_path: str) -> bool:
        return any(part in DEFAULT_IGNORED_NAMES for part in relative_path.split("/"))

    @staticmethod
    def _parse_single_line_range(lines: Any | None) -> tuple[int, int] | None:
        if lines is None:
            return None
        if isinstance(lines, dict):
            start = lines.get("start")
            end = lines.get("end", start)
            if isinstance(start, int) and isinstance(end, int):
                return start, end
        if isinstance(lines, list) and len(lines) == 2 and all(isinstance(item, int) for item in lines):
            return int(lines[0]), int(lines[1])
        if isinstance(lines, str):
            chunk = lines.split(",", 1)[0].strip()
            if "-" in chunk:
                start_raw, end_raw = chunk.split("-", 1)
                if start_raw.strip().isdigit() and end_raw.strip().isdigit():
                    return int(start_raw.strip()), int(end_raw.strip())
            if chunk.isdigit():
                line_number = int(chunk)
                return line_number, line_number
        return None

    def _select_lines(self, text: str, lines: Any | None, *, offset: int = 0) -> str:
        source_lines = text.splitlines()
        if not source_lines:
            return ""

        selected_range = self._parse_single_line_range(lines)
        if selected_range is None:
            selected = list(enumerate(source_lines, start=1))
        else:
            start, end = selected_range
            selected = [(index, line) for index, line in enumerate(source_lines, start=1) if start <= index <= end]

        if offset > 0:
            selected = selected[offset:]

        return "\n".join(f"{index}: {line}" for index, line in selected)
