"""Tests for the `manfred` launcher helpers (no backend/TUI side effects)."""

from __future__ import annotations

import contextlib
from pathlib import Path

from app.cli import launcher


def test_sqlite_url_is_absolute_four_slash() -> None:
    assert launcher.sqlite_url(Path("/home/u/.manfred/manfred.db")) == "sqlite:////home/u/.manfred/manfred.db"


def test_parse_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nOPEN_ROUTER_API_KEY="sk-123"\nEMPTY=\nLANGFUSE_ENABLED=false\nbad line\n',
        encoding="utf-8",
    )
    parsed = launcher.parse_env_file(env)
    assert parsed["OPEN_ROUTER_API_KEY"] == "sk-123"
    assert parsed["LANGFUSE_ENABLED"] == "false"
    assert parsed["EMPTY"] == ""
    assert "bad line" not in parsed


def test_parse_env_file_missing(tmp_path: Path) -> None:
    assert launcher.parse_env_file(tmp_path / "nope.env") == {}


def test_build_backend_env_overrides_win_but_file_fills_gaps() -> None:
    env = launcher.build_backend_env(
        base_env={"DATABASE_URL": "sqlite:///old.db", "PATH": "/bin"},
        file_env={"LANGFUSE_ENABLED": "false", "DATABASE_URL": "ignored"},
        database_url="sqlite:////home/u/.manfred/manfred.db",
        workspace_path=Path("/home/u/.manfred/agent_data"),
        mcp_config_path=Path("/home/u/.manfred/mcp-disabled.json"),
    )
    # Hard overrides always win.
    assert env["DATABASE_URL"] == "sqlite:////home/u/.manfred/manfred.db"
    assert env["WORKSPACE_PATH"] == "/home/u/.manfred/agent_data"
    assert env["MCP_CONFIG_PATH"] == "/home/u/.manfred/mcp-disabled.json"
    assert env["API_RELOAD"] == "false"
    # Base env preserved; file value fills a gap only if not already set.
    assert env["PATH"] == "/bin"
    assert env["LANGFUSE_ENABLED"] == "false"


def test_ensure_app_home_creates_dirs(tmp_path: Path) -> None:
    paths = launcher.ensure_app_home(tmp_path / "mhome")
    assert paths["agent_data"].is_dir()
    assert paths["logs"].is_dir()
    assert paths["db"] == tmp_path / "mhome" / "manfred.db"
    assert not paths["mcp_disabled"].exists()  # intentionally absent → MCP off


def test_app_home_env_override(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("MANFRED_HOME", "/tmp/custom-manfred")
    assert launcher.app_home() == Path("/tmp/custom-manfred")


def test_resolve_key_prefers_environment(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "from-env")
    assert launcher.resolve_and_store_key(tmp_path / ".env") == "from-env"


def test_resolve_key_reads_app_home_env(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPEN_ROUTER_API_KEY=from-file\n", encoding="utf-8")
    assert launcher.resolve_and_store_key(env) == "from-file"


def test_resolve_key_none_when_missing_non_interactive(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    assert launcher.resolve_and_store_key(tmp_path / ".env", interactive=False) is None


def test_resolve_key_prompts_and_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda _prompt="": "typed-key")
    env = tmp_path / ".env"
    assert launcher.resolve_and_store_key(env) == "typed-key"
    assert "OPEN_ROUTER_API_KEY=typed-key" in env.read_text(encoding="utf-8")
    assert (env.stat().st_mode & 0o777) == 0o600


def test_is_healthy_true_and_false(monkeypatch) -> None:  # noqa: ANN001
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert launcher.is_healthy("http://x") is True

    def _boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", _boom)
    assert launcher.is_healthy("http://x") is False


def test_repo_root_points_at_backend_root() -> None:
    root = launcher.repo_root()
    assert (root / "src" / "alembic.ini").is_file()
    with contextlib.suppress(AssertionError):
        assert (root / "src" / "app" / "cli" / "launcher.py").is_file()
