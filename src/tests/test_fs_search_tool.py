from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
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


fs_search_module = load_module(
    "filesystem_fs_search_tool",
    "app/agent/tools/file_system/fs_search.py",
)


class FsSearchToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_searches_filenames_and_content(self) -> None:
        root = fs_search_module.WORKSPACE_ROOT / "fs-search-suite"
        nested = root / "nested"
        nested.mkdir(parents=True, exist_ok=True)
        (root / "needle-plan.txt").write_text("hello world\nneedle alpha\n", encoding="utf-8")
        (nested / "beta-notes.txt").write_text("beta only\n", encoding="utf-8")
        (nested / "gamma.txt").write_text("contains needle line\n", encoding="utf-8")

        try:
            result = await fs_search_module.fs_search_tool.handler(
                {
                    "path": "fs-search-suite",
                    "pattern": "needle",
                    "target": "all",
                    "pattern_mode": "literal",
                }
            )
        finally:
            if root.exists():
                shutil.rmtree(root)

        self.assertTrue(result["ok"])
        paths = [entry["path"] for entry in result["output"]["results"]]
        self.assertEqual(
            paths,
            [
                "fs-search-suite/needle-plan.txt",
                "fs-search-suite/needle-plan.txt",
                "fs-search-suite/nested/gamma.txt",
            ],
        )
        self.assertEqual(result["output"]["count"], 3)

    async def test_rejects_invalid_regex_pattern(self) -> None:
        result = await fs_search_module.fs_search_tool.handler(
            {
                "pattern": "(a+)+",
                "pattern_mode": "regex",
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["argument"], "pattern")

    async def test_treats_blank_path_as_workspace_root(self) -> None:
        test_file = fs_search_module.WORKSPACE_ROOT / "blank-path-marker.txt"
        test_file.write_text("workspace root marker\n", encoding="utf-8")

        try:
            result = await fs_search_module.fs_search_tool.handler(
                {
                    "path": "",
                    "pattern": "blank-path-marker",
                    "target": "filename",
                }
            )
        finally:
            if test_file.exists():
                test_file.unlink()

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["count"], 1)
        self.assertEqual(result["output"]["results"][0]["path"], "blank-path-marker.txt")


if __name__ == "__main__":
    unittest.main()
