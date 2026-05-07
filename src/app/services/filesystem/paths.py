from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.services.filesystem.types import FilesystemMount, ResolvedFilesystemPath


def build_mounts(
    *,
    mount_names: list[str],
    fs_root: Path,
) -> list[FilesystemMount]:
    mounts = [FilesystemMount(name=name, root=fs_root) for name in mount_names]
    mounts.append(FilesystemMount(name="workspace", root=fs_root))
    return mounts


class FilesystemPathResolver:
    def __init__(self, mounts: list[FilesystemMount]) -> None:
        self._mounts = mounts
        self._resolved_roots = {mount.name: mount.root.resolve() for mount in mounts}

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

        return "/".join(parts) or "."

    def _find_mount(self, normalized_path: str) -> FilesystemMount | None:
        for mount in self._mounts:
            if normalized_path == mount.name or normalized_path.startswith(f"{mount.name}/"):
                return mount
        return None
