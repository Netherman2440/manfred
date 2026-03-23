from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.agent.tools import filesystem_tools


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs_manage_module = load_module(
    "filesystem_fs_manage_tool",
    "app/agent/tools/file_system/fs_manage.py",
)


class FsManageToolTest(unittest.IsolatedAsyncioTestCase):
    def test_active_filesystem_registry_exposes_only_fs_tools(self) -> None:
        self.assertEqual(
            [tool.definition.name for tool in filesystem_tools],
            ["fs_read", "fs_search", "fs_write", "fs_manage"],
        )

    async def test_deletes_empty_directory_and_blocks_non_empty_directory(self) -> None:
        root = fs_manage_module.WORKSPACE_ROOT / "fs-manage-delete"
        empty_dir = root / "empty"
        full_dir = root / "full"
        empty_dir.mkdir(parents=True, exist_ok=True)
        full_dir.mkdir(parents=True, exist_ok=True)
        (full_dir / "note.txt").write_text("hello\n", encoding="utf-8")

        try:
            delete_empty = await fs_manage_module.fs_manage_tool.handler(
                {"action": "delete", "path": "fs-manage-delete/empty"}
            )
            delete_full = await fs_manage_module.fs_manage_tool.handler(
                {"action": "delete", "path": "fs-manage-delete/full"}
            )
        finally:
            if root.exists():
                shutil.rmtree(root)

        self.assertTrue(delete_empty["ok"])
        self.assertFalse(delete_full["ok"])
        self.assertEqual(delete_full["details"]["code"], "directory_not_empty")

    async def test_blocks_symlink_escape(self) -> None:
        symlink_path = fs_manage_module.WORKSPACE_ROOT / "fs-manage-link"
        outside_root = Path("/tmp/manfred-fs-manage-outside")
        outside_root.mkdir(parents=True, exist_ok=True)

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
            symlink_path.symlink_to(outside_root, target_is_directory=True)

            result = await fs_manage_module.fs_manage_tool.handler({"action": "stat", "path": "fs-manage-link/secret.txt"})
        finally:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
            if outside_root.exists():
                outside_root.rmdir()

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["code"], "path_escape")


if __name__ == "__main__":
    unittest.main()
