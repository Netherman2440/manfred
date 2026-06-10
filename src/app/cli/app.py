"""Textual TUI for Manfred — scrolling-REPL chat with live streaming."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, RichLog, Static

from app.cli.client import Attachment, ManfredClient, ManfredClientError, StreamEvent

_ATTACHMENT_RE = re.compile(r"@(\S+)")

_BANNER = r"""
 __  __    _    _   _ _____ ____  _____ ____
|  \/  |  / \  | \ | |  ___|  _ \| ____|  _ \
| |\/| | / _ \ |  \| | |_  | |_) |  _| | | | |
| |  | |/ ___ \| |\  |  _| |  _ <| |___| |_| |
|_|  |_/_/   \_\_| \_|_|   |_| \_\_____|____/
"""
_COMMANDS = {
    "/new": "Start a fresh session",
    "/sessions": "List past sessions",
    "/resume": "/resume <n> — resume a past session",
    "/agent": "/agent [name] — list or switch agent",
    "/model": "Show the active agent's model",
    "/summarize": "Summarize the current session",
    "/cancel": "Cancel the in-flight run",
    "/clear": "Clear the screen",
    "/help": "Show this help",
    "/quit": "Exit",
}


class ManfredCli(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #log { height: 1fr; border: none; padding: 0 1; }
    #status { height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #prompt { height: auto; }
    #sigil { width: auto; padding: 0 1; color: $accent; }
    Input { border: none; }
    """

    BINDINGS = [("escape", "cancel", "Cancel run"), ("ctrl+c", "quit", "Quit")]
    # The built-in command palette (ctrl+p) is unused here; disable it so it
    # can't intercept keys or surprise the user.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, *, base_url: str, agent: str | None = None) -> None:
        super().__init__()
        self._client = ManfredClient(base_url)
        self._base_url = base_url
        self._user_id = "default-user"
        self._agent_name = agent
        self._session_id: str | None = None
        self._sessions_cache: list[dict[str, Any]] = []
        self._running = False
        self._assistant_buffer = ""
        # Pending human prompt the next input answers: (agent_id, call_id) or None.
        self._waiting: tuple[str, str] | None = None
        # Last error text shown this run, to avoid double-printing on failed runs
        # (a failed run emits both an `error` event and `agent.failed`).
        self._last_error: str | None = None

    def compose(self) -> ComposeResult:
        log = RichLog(id="log", wrap=True, markup=True, highlight=True)
        log.can_focus = False
        yield log
        yield Static("", id="status")
        with Horizontal(id="prompt"):
            yield Static("›", id="sigil")
            yield Input(placeholder="Message Manfred…  (/help for commands)", id="input")

    def _show_banner(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(Text(_BANNER, style="bold magenta"))

    async def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        self._show_banner()
        self._write_system(f"Manfred CLI → {self._base_url}")
        if not await self._client.health():
            self._write_error("Backend not reachable. Start it with `uv run python -m app.main` and retry.")
            self._set_status("offline")
            return
        try:
            me = await self._client.me()
            self._user_id = me.get("id", self._user_id)
            agents = await self._client.list_agents()
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        names = [a["name"] for a in agents]
        if self._agent_name is None:
            self._agent_name = names[0] if names else "manfred"
        self._write_system(
            f"Signed in as {me.get('name', self._user_id)} · agent: {self._agent_name} · "
            f"available: {', '.join(names) or 'none'}"
        )
        self._set_status("ready")

    # ---- input dispatch --------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        self.query_one("#input", Input).value = ""
        if not raw:
            return
        if raw.startswith("/"):
            await self._handle_command(raw)
            return
        if self._waiting is not None:
            await self._answer_waiting(raw)
            return
        if self._running:
            await self._queue_message(raw)
            return
        await self._send_message(raw)

    # ---- commands --------------------------------------------------------

    async def _handle_command(self, raw: str) -> None:
        parts = raw.split()
        cmd, args = parts[0], parts[1:]
        if cmd == "/quit":
            await self._client.aclose()
            self.exit()
        elif cmd == "/clear":
            self.query_one("#log", RichLog).clear()
        elif cmd == "/help":
            for name, desc in _COMMANDS.items():
                self._write_system(f"  {name:<11} {desc}")
        elif cmd == "/new":
            self._session_id = None
            self._waiting = None
            self.query_one("#log", RichLog).clear()
            self._show_banner()
            self._write_system("Started a new session.")
            self._set_status("ready")
        elif cmd == "/agent":
            await self._cmd_agent(args)
        elif cmd == "/model":
            await self._cmd_model()
        elif cmd == "/sessions":
            await self._cmd_sessions()
        elif cmd == "/resume":
            await self._cmd_resume(args)
        elif cmd == "/summarize":
            await self._cmd_summarize()
        elif cmd == "/cancel":
            await self.action_cancel()
        else:
            self._write_error(f"Unknown command: {cmd} (try /help)")

    async def _cmd_agent(self, args: list[str]) -> None:
        try:
            agents = await self._client.list_agents()
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        names = [a["name"] for a in agents]
        if not args:
            for a in agents:
                marker = "→" if a["name"] == self._agent_name else " "
                self._write_system(f" {marker} {a['name']} — {a.get('description', '')}")
            return
        target = args[0]
        if target not in names:
            self._write_error(f"No such agent: {target}. Available: {', '.join(names)}")
            return
        self._agent_name = target
        self._session_id = None
        self._write_system(f"Switched to agent '{target}' (new session).")
        self._set_status("ready")

    async def _cmd_model(self) -> None:
        try:
            agents = await self._client.list_agents()
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        for a in agents:
            if a["name"] == self._agent_name:
                self._write_system(f"{self._agent_name} model: {a.get('model', 'unknown')}")
                return
        self._write_system(f"Agent {self._agent_name} not found in catalog.")

    async def _cmd_sessions(self) -> None:
        try:
            sessions = await self._client.list_sessions(self._user_id)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        self._sessions_cache = sessions
        if not sessions:
            self._write_system("No past sessions.")
            return
        for i, s in enumerate(sessions, start=1):
            title = s.get("title") or s.get("last_message_preview") or "(untitled)"
            self._write_system(
                f" {i:>2}. [{s.get('root_agent_status', '?')}] {s.get('root_agent_name', '?')} · {title[:60]}"
            )
        self._write_system("Use /resume <n> to open one.")

    async def _cmd_resume(self, args: list[str]) -> None:
        if not self._sessions_cache:
            await self._cmd_sessions()
        if not args or not args[0].isdigit():
            self._write_error("Usage: /resume <n> (run /sessions first)")
            return
        index = int(args[0]) - 1
        if not (0 <= index < len(self._sessions_cache)):
            self._write_error("Out of range.")
            return
        session = self._sessions_cache[index]
        try:
            detail = await self._client.session_detail(self._user_id, session["id"])
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        self._session_id = session["id"]
        self._agent_name = detail.get("root_agent", {}).get("name", self._agent_name)
        self.query_one("#log", RichLog).clear()
        self._write_system(f"Resumed session {session['id'][:8]} · agent {self._agent_name}")
        self._render_transcript(detail.get("items", []))
        root = detail.get("root_agent", {})
        self._set_status(root.get("status", "ready"))
        self._enter_waiting_from_list(root.get("id"), root.get("waiting_for", []))

    async def _cmd_summarize(self) -> None:
        if not self._session_id:
            self._write_error("No active session to summarize.")
            return
        try:
            result = await self._client.summarize(self._session_id)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        status = result.get("status")
        if status == "no_unobserved":
            self._write_system("Nothing new to summarize.")
        else:
            preview = result.get("observations_preview") or result.get("detail") or status
            self._write_system(f"Summary [{status}]: {preview}")

    async def action_cancel(self) -> None:
        if not self._running or not self._session_id:
            return
        try:
            await self._client.cancel(self._session_id)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        self.workers.cancel_all()
        self._finalize_run("cancelled")

    # ---- sending / streaming --------------------------------------------

    async def _send_message(self, text: str) -> None:
        message, attachments = self._extract_attachments(text)
        self._write_user(text, attachments)
        self._running = True
        self._assistant_buffer = ""
        self._last_error = None
        self._set_status("…thinking")
        self._stream_run(message, attachments)

    @work(exclusive=True)
    async def _stream_run(self, message: str, attachments: list[Attachment]) -> None:
        try:
            async for event in self._client.stream_chat(
                message=message,
                session_id=self._session_id,
                agent_name=self._agent_name,
                attachments=attachments,
            ):
                self._on_stream_event(event)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            self._finalize_run("failed")

    def _on_stream_event(self, event: StreamEvent) -> None:
        kind = event.event
        data = event.data
        if kind == "session":
            self._session_id = data.get("session_id", self._session_id)
        elif kind == "text_delta":
            self._assistant_buffer += data.get("delta", "")
            self._set_status("…writing")
        elif kind == "text_done":
            self._commit_assistant_text(data.get("text", self._assistant_buffer))
            self._assistant_buffer = ""
        elif kind == "function_call_done":
            self._write_tool_call(data.get("name", "?"), data.get("arguments") or {})
        elif kind == "tool.completed":
            self._write_tool_result(data.get("name", "?"), data.get("output") or {}, is_error=False)
        elif kind == "tool.failed":
            self._write_tool_result(data.get("name", "?"), {"error": data.get("error")}, is_error=True)
        elif kind == "agent.waiting":
            self._handle_agent_waiting(data.get("waiting_for", []))
        elif kind == "agent.completed":
            self._finalize_run("completed")
        elif kind == "agent.failed":
            error = data.get("error", "Run failed.")
            if error != self._last_error:
                self._write_error(error)
            self._finalize_run("failed")
        elif kind == "agent.cancelled":
            self._finalize_run("cancelled")
        elif kind == "error":
            self._write_error(data.get("error", "Stream error."))
            self._finalize_run("failed")

    def _handle_agent_waiting(self, entries: list[dict[str, Any]]) -> None:
        if self._assistant_buffer:
            self._commit_assistant_text(self._assistant_buffer)
            self._assistant_buffer = ""
        self._enter_waiting_from_list(self._current_agent_id(entries), entries)

    def _enter_waiting_from_list(self, agent_id: str | None, entries: list[dict[str, Any]]) -> None:
        human = next((e for e in entries if e.get("type") == "human"), None)
        target = human or (entries[0] if entries else None)
        if target is None or agent_id is None:
            self._finalize_run("completed")
            return
        question = target.get("description") or f"{target.get('name', 'agent')} needs input"
        self._write_prompt(question)
        self._waiting = (agent_id, target["call_id"])
        self._running = False
        self._set_status("waiting · type your answer")
        self.query_one("#input", Input).placeholder = "Your answer…"

    @staticmethod
    def _current_agent_id(entries: list[dict[str, Any]]) -> str | None:
        for entry in entries:
            if entry.get("agent_id"):
                return entry["agent_id"]
        return None

    async def _answer_waiting(self, answer: str) -> None:
        assert self._waiting is not None
        agent_id, call_id = self._waiting
        self._waiting = None
        self.query_one("#input", Input).placeholder = "Message Manfred…  (/help for commands)"
        self._write_user(answer, [])
        self._running = True
        self._set_status("…thinking")
        self._deliver_run(agent_id, call_id, answer)

    @work(exclusive=True)
    async def _deliver_run(self, agent_id: str, call_id: str, answer: str) -> None:
        try:
            response = await self._client.deliver(agent_id, call_id=call_id, output=answer)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            self._finalize_run("failed")
            return
        self._render_chat_response(response)

    async def _queue_message(self, text: str) -> None:
        if not self._session_id:
            self._write_error("No active run to queue against.")
            return
        try:
            result = await self._client.queue(self._session_id, text)
        except ManfredClientError as exc:
            self._write_error(str(exc))
            return
        position = result.get("queue_position", "?")
        self._write_system(f"[queued #{position}] {text}")

    # ---- rendering -------------------------------------------------------

    def _render_chat_response(self, response: dict[str, Any]) -> None:
        for item in response.get("output", []):
            itype = item.get("type")
            if itype == "text":
                self._commit_assistant_text(item.get("text", ""))
            elif itype == "function_call":
                self._write_tool_call(item.get("name", "?"), item.get("arguments") or {})
            elif itype == "function_call_output":
                self._write_tool_result(
                    item.get("name", "?"),
                    _coerce_output(item.get("output")),
                    is_error=bool(item.get("is_error")),
                )
        status = response.get("status", "completed")
        if status == "waiting":
            self._enter_waiting_from_list(response.get("agent_id"), response.get("waiting_for", []))
        else:
            if response.get("error"):
                self._write_error(response["error"])
            self._finalize_run(status)

    def _render_transcript(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            itype = item.get("type")
            if itype == "message":
                role = item.get("role")
                content = item.get("content", "")
                if role == "user":
                    self._write_user(content, item.get("attachments", []))
                elif role == "assistant":
                    self._commit_assistant_text(content)
                else:
                    self._write_system(content)
            elif itype == "function_call":
                self._write_tool_call(item.get("name", "?"), item.get("arguments") or {})
            elif itype == "function_call_output":
                self._write_tool_result(
                    item.get("name", "?"),
                    item.get("tool_result") or {},
                    is_error=bool(item.get("is_error")),
                )

    def _commit_assistant_text(self, text: str) -> None:
        if not text.strip():
            return
        log = self.query_one("#log", RichLog)
        log.write(Text("manfred", style="bold magenta"))
        log.write(Markdown(text))

    def _write_user(self, text: str, attachments: list[Any]) -> None:
        log = self.query_one("#log", RichLog)
        line = Text("you  ", style="bold cyan")
        line.append(text, style="white")
        log.write(line)
        for att in attachments:
            name = att.file_name if isinstance(att, Attachment) else att.get("file_name", "file")
            log.write(Text(f"     📎 {name}", style="dim"))

    def _write_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        args = ", ".join(f"{k}={_short(v)}" for k, v in arguments.items())
        self.query_one("#log", RichLog).write(Text(f"  ⚙ {name}({args})", style="yellow"))

    def _write_tool_result(self, name: str, output: dict[str, Any], *, is_error: bool) -> None:
        if is_error:
            value = output.get("error", output)
            self.query_one("#log", RichLog).write(Text(f"    ✗ {_short(value, 200)}", style="red"))
            return
        value = output.get("output", output) if isinstance(output, dict) else output
        self.query_one("#log", RichLog).write(Text(f"    → {_short(value, 200)}", style="green"))

    def _write_prompt(self, question: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(Text("manfred asks", style="bold magenta"))
        log.write(Markdown(question))

    def _write_system(self, text: str) -> None:
        self.query_one("#log", RichLog).write(Text(text, style="dim italic"))

    def _write_error(self, text: str) -> None:
        self._last_error = text
        self.query_one("#log", RichLog).write(Text(f"⚠ {text}", style="bold red"))

    def _finalize_run(self, status: str) -> None:
        if self._assistant_buffer:
            self._commit_assistant_text(self._assistant_buffer)
            self._assistant_buffer = ""
        self._running = False
        self._set_status(status)

    def _set_status(self, status: str) -> None:
        session = self._session_id[:8] if self._session_id else "new"
        self.query_one("#status", Static).update(f"agent: {self._agent_name}  ·  session: {session}  ·  {status}")

    # ---- helpers ---------------------------------------------------------

    def _extract_attachments(self, text: str) -> tuple[str, list[Attachment]]:
        attachments: list[Attachment] = []
        kept_tokens: list[str] = []
        for token in text.split():
            match = _ATTACHMENT_RE.fullmatch(token)
            if match:
                path = Path(match.group(1)).expanduser()
                if path.is_file():
                    attachments.append(Attachment.from_path(path))
                    continue
                self._write_error(f"Attachment not found: {path}")
            kept_tokens.append(token)
        return " ".join(kept_tokens), attachments


def _short(value: Any, limit: int = 60) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _coerce_output(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {"output": output}
        return parsed if isinstance(parsed, dict) else {"output": parsed}
    return {"output": output}
