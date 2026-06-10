"""`manfred` launcher: boot the backend (or attach to a running one) + the TUI.

Flow: ensure an app-home (``~/.manfred``) for the DB/workspace/key/logs; if a
backend is already healthy on the target URL, attach the TUI to it; otherwise
run migrations, spawn the backend as a child (pointed at the app-home via env
overrides, MCP disabled), wait for ``/health``, launch the TUI, and tear the
child down on exit.

Pure helpers live at the top so they can be unit-tested without side effects.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://localhost:3000"
HEALTH_TIMEOUT_S = 30.0


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def repo_root() -> Path:
    """Repo root (`manfred_backend/`) — launcher is at REPO/src/app/cli/launcher.py."""
    return Path(__file__).resolve().parents[3]


def app_home() -> Path:
    return Path(os.environ.get("MANFRED_HOME", Path.home() / ".manfred"))


def sqlite_url(db_path: Path) -> str:
    """Absolute sqlite URL (`sqlite:////abs/path`)."""
    return f"sqlite:///{db_path}"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Ignores blanks/comments; strips quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def build_backend_env(
    *,
    base_env: dict[str, str],
    file_env: dict[str, str],
    database_url: str,
    workspace_path: Path,
    mcp_config_path: Path,
) -> dict[str, str]:
    """Backend subprocess env: base env + app-home .env, then hard overrides."""
    env = dict(base_env)
    for key, value in file_env.items():
        env.setdefault(key, value)
    env["DATABASE_URL"] = database_url
    env["WORKSPACE_PATH"] = str(workspace_path)
    env["MCP_CONFIG_PATH"] = str(mcp_config_path)
    env["API_RELOAD"] = "false"
    return env


# --------------------------------------------------------------------------
# Side-effecting helpers
# --------------------------------------------------------------------------


def ensure_app_home(home: Path) -> dict[str, Path]:
    home.mkdir(parents=True, exist_ok=True)
    agent_data = home / "agent_data"
    logs = home / "logs"
    agent_data.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    return {
        "home": home,
        "db": home / "manfred.db",
        "agent_data": agent_data,
        "logs": logs,
        "env_file": home / ".env",
        # A path that does not exist → MCP config loader yields zero servers.
        "mcp_disabled": home / "mcp-disabled.json",
    }


def is_healthy(url: str, *, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/v1/health", timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def resolve_and_store_key(env_file: Path, *, interactive: bool = True) -> str | None:
    """Return the OpenRouter key from env or app-home .env, prompting once if missing."""
    existing = os.environ.get("OPEN_ROUTER_API_KEY")
    if existing:
        return existing
    file_env = parse_env_file(env_file)
    if file_env.get("OPEN_ROUTER_API_KEY"):
        return file_env["OPEN_ROUTER_API_KEY"]
    if not interactive or not sys.stdin.isatty():
        return None
    import getpass

    key = getpass.getpass("OpenRouter API key (leave blank to skip): ").strip()
    if not key:
        return None
    env_file.write_text(
        (env_file.read_text(encoding="utf-8") if env_file.is_file() else "") + f"OPEN_ROUTER_API_KEY={key}\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    return key


def run_migrations(*, src_dir: Path, database_url: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(src_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(src_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def spawn_backend(*, src_dir: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen[bytes]:
    log = log_path.open("ab")
    return subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=str(src_dir),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def wait_until_healthy(url: str, proc: subprocess.Popen[bytes], *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_healthy(url):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _tail(path: Path, lines: int = 20) -> str:
    if not path.is_file():
        return "(no log)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="manfred", description="Launch Manfred (backend + TUI)")
    parser.add_argument("--url", default=os.environ.get("MANFRED_API_URL", DEFAULT_URL))
    parser.add_argument("--agent", default=None, help="Agent to start with")
    parser.add_argument("--no-backend", action="store_true", help="Attach only; never spawn a backend")
    args = parser.parse_args()

    src_dir = repo_root() / "src"
    paths = ensure_app_home(app_home())
    url = args.url
    spawned: subprocess.Popen[bytes] | None = None

    if is_healthy(url):
        print(f"Attaching to running Manfred backend at {url}")
    elif args.no_backend:
        sys.exit(f"No backend reachable at {url} (--no-backend set).")
    else:
        key = resolve_and_store_key(paths["env_file"])
        if not key:
            print("warning: no OpenRouter API key — agent replies will fail until one is set.")
        database_url = sqlite_url(paths["db"])
        print("Running database migrations…")
        run_migrations(src_dir=src_dir, database_url=database_url)
        env = build_backend_env(
            base_env=dict(os.environ),
            file_env=parse_env_file(paths["env_file"]),
            database_url=database_url,
            workspace_path=paths["agent_data"],
            mcp_config_path=paths["mcp_disabled"],
        )
        log_path = paths["logs"] / "backend.log"
        print("Starting Manfred backend…")
        spawned = spawn_backend(src_dir=src_dir, env=env, log_path=log_path)
        if not wait_until_healthy(url, spawned, timeout=HEALTH_TIMEOUT_S):
            terminate(spawned)
            sys.exit(f"Backend failed to start within {HEALTH_TIMEOUT_S:.0f}s.\n--- {log_path} ---\n{_tail(log_path)}")

    try:
        from app.cli.app import ManfredCli

        ManfredCli(base_url=url, agent=args.agent).run()
    finally:
        if spawned is not None:
            terminate(spawned)


if __name__ == "__main__":
    main()
