from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.services.filesystem.types import FilesystemMount, ResolvedFilesystemPath


def build_filesystem_mounts(
    *,
    repo_root: Path,
    fs_roots: list[str],
    workspace_path: str | None = None,
) -> list[FilesystemMount]:
    mounts: list[FilesystemMount] = []
    seen: set[Path] = set()
    workspace_root = _resolve_workspace_root(repo_root=repo_root, workspace_path=workspace_path)

    for raw_root in fs_roots:
        raw_path = Path(raw_root)
        absolute_root = (repo_root / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        if absolute_root in seen:
            continue

        mount_name = _build_mount_name(
            raw_path=raw_path,
            absolute_root=absolute_root,
            repo_root=repo_root,
            workspace_root=workspace_root,
        )
        mount_name = mount_name.rstrip("/") or "."
        mounts.append(FilesystemMount(name=mount_name, root=absolute_root))
        seen.add(absolute_root)

    mounts.sort(key=lambda mount: len(mount.name), reverse=True)
    return mounts


class FilesystemPathResolver:
    def __init__(self, mounts: list[FilesystemMount], *, workspace_root: str | None = None) -> None:
        self._mounts = mounts
        self._resolved_roots = {mount.name: mount.root.resolve() for mount in mounts}
        self._workspace_root = self._normalize_workspace_root_name(workspace_root)

    @property
    def mounts(self) -> list[FilesystemMount]:
        return list(self._mounts)

    def resolve(self, requested_path: str) -> ResolvedFilesystemPath:
        normalized_path = self.normalize_virtual_path(requested_path)
        if normalized_path == ".":
            raise ValueError("'.' is only supported by root-aware operations.")

        mount = self._find_mount(normalized_path)
        if mount is None:
            allowed_roots = ", ".join(sorted(item.name for item in self._mounts))
            raise ValueError(f"Path '{requested_path}' is outside configured filesystem roots: {allowed_roots}")

        relative_path = "."
        if normalized_path != mount.name:
            relative_path = normalized_path[len(mount.name) :].lstrip("/")

        relative_posix = PurePosixPath(relative_path)
        absolute_path = (mount.root / relative_posix).resolve(strict=False)
        root_path = self._resolved_roots[mount.name]
        if not absolute_path.is_relative_to(root_path):
            raise ValueError(f"Path '{requested_path}' escapes the allowed mount '{mount.name}'.")

        return ResolvedFilesystemPath(
            mount=mount,
            requested_path=normalized_path,
            relative_path=relative_posix,
            absolute_path=absolute_path,
        )

    def build_mount_root(self, mount: FilesystemMount) -> ResolvedFilesystemPath:
        return ResolvedFilesystemPath(
            mount=mount,
            requested_path=mount.name,
            relative_path=PurePosixPath("."),
            absolute_path=self._resolved_roots[mount.name],
        )

    def normalize_virtual_path(self, path: str) -> str:
        normalized = str(path or "").strip().replace("\\", "/")
        if not normalized:
            raise ValueError("path must be a non-empty string")
        if normalized == ".":
            return "."
        if normalized.startswith("/"):
            raise ValueError("Absolute paths are not allowed.")

        pure_path = PurePosixPath(normalized)
        parts = [part for part in pure_path.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise ValueError("Parent path segments ('..') are not allowed.")

        normalized_path = "/".join(parts) or "."
        workspace_root = self._workspace_root
        if workspace_root and (
            normalized_path == workspace_root or normalized_path.startswith(f"{workspace_root}/")
        ):
            normalized_path = normalized_path[len(workspace_root) :].lstrip("/") or "."

        return normalized_path

    def _find_mount(self, normalized_path: str) -> FilesystemMount | None:
        for mount in self._mounts:
            if normalized_path == mount.name or normalized_path.startswith(f"{mount.name}/"):
                return mount
        return None

    @staticmethod
    def _normalize_workspace_root_name(workspace_root: str | None) -> str | None:
        normalized = str(workspace_root or "").strip().replace("\\", "/").strip("/")
        if not normalized or normalized == ".":
            return None
        pure_path = PurePosixPath(normalized)
        parts = [part for part in pure_path.parts if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            return None
        return "/".join(parts)


def _resolve_workspace_root(*, repo_root: Path, workspace_path: str | None) -> Path | None:
    normalized = str(workspace_path or "").strip()
    if not normalized:
        return None

    workspace = Path(normalized)
    return (repo_root / workspace).resolve() if not workspace.is_absolute() else workspace.resolve()


def _build_mount_name(
    *,
    raw_path: Path,
    absolute_root: Path,
    repo_root: Path,
    workspace_root: Path | None,
) -> str:
    if workspace_root is not None:
        try:
            relative_to_workspace = absolute_root.relative_to(workspace_root).as_posix()
        except ValueError:
            relative_to_workspace = None
        if relative_to_workspace is not None:
            return relative_to_workspace or "."

    if raw_path.is_absolute():
        try:
            return absolute_root.relative_to(repo_root).as_posix()
        except ValueError:
            return absolute_root.name or absolute_root.as_posix()

    return raw_path.as_posix()
