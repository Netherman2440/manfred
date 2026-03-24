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


fs_read_module = load_module(
    "filesystem_fs_read_tool",
    "app/agent/tools/file_system/fs_read.py",
)


class FsReadToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_reads_text_file_with_line_numbers_and_checksum(self) -> None:
        test_file = fs_read_module.WORKSPACE_ROOT / "fs-read-checksum.txt"
        test_file.write_text("alpha\nbeta\n", encoding="utf-8")

        try:
            result = await fs_read_module.fs_read_tool.handler({"path": "fs-read-checksum.txt"})
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["path"], "fs-read-checksum.txt")
        self.assertEqual(result["output"]["type"], "file")
        self.assertEqual(result["output"]["checksum"], "e49c81e2d2f8")
        self.assertEqual(result["output"]["content"], "1: alpha\n2: beta")

    async def test_reads_partial_line_range(self) -> None:
        test_file = fs_read_module.WORKSPACE_ROOT / "fs-read-range.txt"
        test_file.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

        try:
            result = await fs_read_module.fs_read_tool.handler({"path": "fs-read-range.txt", "lines": "2-3"})
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["line_start"], 2)
        self.assertEqual(result["output"]["line_end"], 3)
        self.assertEqual(result["output"]["content"], "2: two\n3: three")

    async def test_blocks_path_traversal(self) -> None:
        result = await fs_read_module.fs_read_tool.handler({"path": "../outside.txt"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["code"], "path_escape")
        self.assertEqual(result["details"]["path"], "../outside.txt")

    async def test_treats_blank_path_as_workspace_root(self) -> None:
        result = await fs_read_module.fs_read_tool.handler({"path": "", "depth": 1})

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["path"], ".")
        self.assertEqual(result["output"]["type"], "directory")


if __name__ == "__main__":
    unittest.main()
