from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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


download_file_module = load_module(
    "files_download_tool",
    "app/agent/tools/files/download_file.py",
)
search_files_module = load_module(
    "files_search_tool",
    "app/agent/tools/files/search_files.py",
)


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get(self, key: str, default: str | None = None) -> str | None:
        if key.lower() == "content-type":
            return self._content_type
        return default

    def get_content_charset(self) -> str:
        return "utf-8"


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self._body = body
        self.headers = FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FileToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_download_file_saves_text_into_downloads_directory(self) -> None:
        target_path = download_file_module.resolve_tool_path("downloads/report.txt")
        if target_path.exists():
            target_path.unlink()

        def fake_urlopen(req, timeout):
            self.assertEqual(timeout, 30.0)
            self.assertEqual(req.full_url, "https://example.com/files/report.txt?token=123")
            return FakeResponse(b"hello from download")

        with patch.object(download_file_module.request, "urlopen", side_effect=fake_urlopen):
            result = await download_file_module.download_file_tool.handler(
                {"url": "https://example.com/files/report.txt?token=123"}
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["path"], "downloads/report.txt")
        self.assertTrue(result["output"]["is_text"])
        self.assertEqual(result["output"]["preview"], "hello from download")
        self.assertTrue(target_path.exists())
        self.assertEqual(target_path.read_text(encoding="utf-8"), "hello from download")

        target_path.unlink()

    async def test_search_files_returns_relative_paths_with_exact_query_matches(self) -> None:
        test_dir = search_files_module.WORKSPACE_ROOT / "search-files-test"
        test_dir.mkdir(exist_ok=True)

        matching_root = test_dir / "match-root.txt"
        nested_dir = test_dir / "nested"
        nested_dir.mkdir(exist_ok=True)
        matching_nested = nested_dir / "match-nested.txt"
        non_matching = nested_dir / "no-match.txt"

        query = "exact needle"
        matching_root.write_text(f"prefix {query} suffix", encoding="utf-8")
        matching_nested.write_text(query, encoding="utf-8")
        non_matching.write_text("exact\nneedle", encoding="utf-8")

        try:
            result = await search_files_module.search_files_tool.handler({"query": query})
        finally:
            for path in [matching_root, matching_nested, non_matching]:
                if path.exists():
                    path.unlink()
            if nested_dir.exists():
                nested_dir.rmdir()
            if test_dir.exists():
                test_dir.rmdir()

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["output"]["matches"],
            [
                "search-files-test/match-root.txt",
                "search-files-test/nested/match-nested.txt",
            ],
        )
        self.assertEqual(result["output"]["query"], query)


if __name__ == "__main__":
    unittest.main()
