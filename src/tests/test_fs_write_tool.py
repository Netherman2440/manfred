from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs_write_module = load_module(
    "filesystem_fs_write_tool",
    "app/agent/tools/file_system/fs_write.py",
)


class FsWriteToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_replace_returns_diff_without_writing(self) -> None:
        test_file = fs_write_module.WORKSPACE_ROOT / "fs-write-dry-run.txt"
        test_file.write_text("one\ntwo\nthree\n", encoding="utf-8")

        try:
            checksum = fs_write_module.short_checksum("one\ntwo\nthree\n")
            result = await fs_write_module.fs_write_tool.handler(
                {
                    "path": "fs-write-dry-run.txt",
                    "operation": "update",
                    "action": "replace",
                    "lines": "2",
                    "content": "updated",
                    "checksum": checksum,
                    "dry_run": True,
                }
            )
            current_content = test_file.read_text(encoding="utf-8")
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertTrue(result["ok"])
        self.assertFalse(result["output"]["applied"])
        self.assertIn("-two", result["output"]["diff"])
        self.assertIn("+updated", result["output"]["diff"])
        self.assertEqual(current_content, "one\ntwo\nthree\n")

    async def test_rejects_checksum_mismatch(self) -> None:
        test_file = fs_write_module.WORKSPACE_ROOT / "fs-write-mismatch.txt"
        test_file.write_text("alpha\nbeta\n", encoding="utf-8")

        try:
            result = await fs_write_module.fs_write_tool.handler(
                {
                    "path": "fs-write-mismatch.txt",
                    "operation": "update",
                    "action": "replace",
                    "lines": "1",
                    "content": "changed",
                    "checksum": "deadbeef0000",
                }
            )
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["code"], "checksum_mismatch")

    async def test_insert_and_delete_lines(self) -> None:
        test_file = fs_write_module.WORKSPACE_ROOT / "fs-write-edits.txt"
        test_file.write_text("first\nsecond\nthird\n", encoding="utf-8")

        try:
            insert_result = await fs_write_module.fs_write_tool.handler(
                {
                    "path": "fs-write-edits.txt",
                    "operation": "update",
                    "action": "insert_after",
                    "lines": "1",
                    "content": "between",
                }
            )
            delete_result = await fs_write_module.fs_write_tool.handler(
                {
                    "path": "fs-write-edits.txt",
                    "operation": "update",
                    "action": "delete_lines",
                    "lines": "3",
                }
            )
            final_content = test_file.read_text(encoding="utf-8")
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertTrue(insert_result["ok"])
        self.assertTrue(delete_result["ok"])
        self.assertEqual(final_content, "first\nbetween\nthird\n")


if __name__ == "__main__":
    unittest.main()
