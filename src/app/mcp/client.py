from __future__ import annotations

import asyncio
import json
import logging
import os
from asyncio.subprocess import PIPE, Process
from pathlib import Path
from time import perf_counter
from typing import Any

from app.mcp.config import load_mcp_config
from app.mcp.types import McpConfig, McpServerConfig, McpServerStatus, McpToolInfo, parse_mcp_tool_name
from app.runtime.cancellation import CancellationRequestedError


logger = logging.getLogger("app.mcp")

_MCP_PROTOCOL_VERSION = "2024-11-05"
_TERMINATION_TIMEOUT_SECONDS = 5.0


class McpClientError(RuntimeError):
    pass


class _StdioMcpSession:
    def __init__(
        self,
        *,
        server_name: str,
        server_config: McpServerConfig,
        repo_root: Path,
        request_timeout_seconds: float,
        client_name: str,
        client_version: str,
    ) -> None:
        self.server_name = server_name
        self.server_config = server_config
        self.repo_root = repo_root
        self.request_timeout_seconds = request_timeout_seconds
        self.client_name = client_name
        self.client_version = client_version

        self._process: Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._request_id = 0
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        env = os.environ.copy()
        env.update(self.server_config.env)

        self._process = await asyncio.create_subprocess_exec(
            self.server_config.command,
            *self.server_config.args,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            cwd=self.server_config.cwd or str(self.repo_root),
            env=env,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self.client_name,
                        "version": self.client_version,
                    },
                },
            )
            await self._notify("notifications/initialized", {})
        except Exception:
            await self.close()
            raise

    async def list_tools(self) -> list[McpToolInfo]:
        result = await self._request("tools/list", {})
        tools_payload = result.get("tools", [])
        if not isinstance(tools_payload, list):
            raise McpClientError(f"MCP server '{self.server_name}' returned invalid tools list.")

        tools: list[McpToolInfo] = []
        for raw_tool in tools_payload:
            if not isinstance(raw_tool, dict):
                continue

            original_name = raw_tool.get("name")
            if not isinstance(original_name, str) or not original_name:
                continue

            input_schema = raw_tool.get("inputSchema") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}

            description = raw_tool.get("description")
            tools.append(
                McpToolInfo(
                    server=self.server_name,
                    original_name=original_name,
                    prefixed_name=f"{self.server_name}__{original_name}",
                    description=description if isinstance(description, str) else "",
                    input_schema=dict(input_schema),
                )
            )

        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        signal: object | None = None,
    ) -> str:
        request_task = asyncio.create_task(
            self._request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": arguments,
                },
            )
        )
        result = await self._await_with_cancellation(request_task, signal=signal)

        if bool(result.get("isError")):
            message = self._extract_result_text(result)
            raise McpClientError(message or "MCP tool returned an error.")

        structured_content = result.get("structuredContent")
        if structured_content is not None:
            return json.dumps(structured_content, ensure_ascii=True)

        text = self._extract_result_text(result)
        if text:
            return text

        content = result.get("content")
        return json.dumps(content if content is not None else result, ensure_ascii=True)

    @staticmethod
    async def _await_with_cancellation(
        task: asyncio.Task[dict[str, Any]],
        *,
        signal: object | None = None,
    ) -> dict[str, Any]:
        if signal is None:
            return await task

        signal.raise_if_cancelled()
        cancel_task = asyncio.create_task(signal.wait())
        done, pending = await asyncio.wait(
            {task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for pending_task in pending:
            pending_task.cancel()

        if cancel_task in done:
            if not task.done():
                task.cancel()
            raise CancellationRequestedError("MCP tool execution cancelled.")

        return task.result()

    async def close(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        for task in tasks:
            task.cancel()

        if self._process is None:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            return

        process = self._process
        self._process = None

        stdin = process.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()

        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=_TERMINATION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        else:
            await process.wait()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reader_loop(self) -> None:
        process = self._require_process()
        stdout = process.stdout
        if stdout is None:
            raise McpClientError(f"MCP server '{self.server_name}' stdout is not available.")

        try:
            while True:
                message = await self._read_message(stdout)
                if "method" in message:
                    if message.get("id") is not None:
                        await self._send_error(
                            message_id=message["id"],
                            code=-32601,
                            error_message="Server requests are not supported by this client.",
                        )
                    continue

                response_id = message.get("id")
                if isinstance(response_id, int):
                    future = self._pending.pop(response_id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue

                if response_id is not None:
                    await self._send_error(
                        message_id=response_id,
                        code=-32600,
                        error_message="Unsupported response id.",
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)

    async def _stderr_loop(self) -> None:
        process = self._require_process()
        stderr = process.stderr
        if stderr is None:
            return

        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                message = line.decode("utf-8", errors="replace").rstrip()
                if message:
                    logger.info("mcp stderr server=%s message=%s", self.server_name, message)
        except asyncio.CancelledError:
            raise

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            self._request_id += 1
            request_id = self._request_id
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._pending[request_id] = future
            try:
                await self._write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
            except Exception:
                self._pending.pop(request_id, None)
                raise

        try:
            message = await asyncio.wait_for(future, timeout=self.request_timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise McpClientError(
                f"MCP server '{self.server_name}' timed out for method '{method}'."
            ) from exc

        error_payload = message.get("error")
        if isinstance(error_payload, dict):
            error_message = error_payload.get("message")
            raise McpClientError(
                str(error_message or f"MCP request '{method}' failed for server '{self.server_name}'.")
            )

        result = message.get("result")
        if not isinstance(result, dict):
            raise McpClientError(
                f"MCP server '{self.server_name}' returned invalid result for method '{method}'."
            )
        return result

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def _send_error(self, *, message_id: Any, code: int, error_message: str) -> None:
        try:
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": code,
                        "message": error_message,
                    },
                }
            )
        except Exception:
            logger.exception("failed to send MCP error response for server=%s", self.server_name)

    async def _write_message(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        stdin = process.stdin
        if stdin is None:
            raise McpClientError(f"MCP server '{self.server_name}' stdin is not available.")

        body = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        stdin.write(body)
        await stdin.drain()

    async def _read_message(self, stdout: asyncio.StreamReader) -> dict[str, Any]:
        line = await stdout.readline()
        if not line:
            raise McpClientError(f"MCP server '{self.server_name}' closed the stream.")

        try:
            payload = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise McpClientError(f"MCP server '{self.server_name}' sent invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise McpClientError(f"MCP server '{self.server_name}' sent invalid JSON-RPC payload.")
        return payload

    def _fail_pending(self, exc: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    def _require_process(self) -> Process:
        if self._process is None:
            raise McpClientError(f"MCP server '{self.server_name}' is not running.")
        return self._process

    @staticmethod
    def _extract_result_text(result: dict[str, Any]) -> str:
        content = result.get("content")
        if not isinstance(content, list):
            return ""

        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
        return "\n".join(text_parts)


class StdioMcpManager:
    def __init__(
        self,
        *,
        repo_root: Path,
        config_path: Path,
        client_name: str,
        client_version: str,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.repo_root = repo_root
        self.config_path = config_path
        self.client_name = client_name
        self.client_version = client_version
        self.request_timeout_seconds = request_timeout_seconds

        self._config: McpConfig | None = None
        self._sessions: dict[str, _StdioMcpSession] = {}
        self._statuses: dict[str, McpServerStatus] = {}
        self._tools_by_name: dict[str, McpToolInfo] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self._config = load_mcp_config(self.config_path)
        self._statuses = {
            server_name: "disconnected"
            for server_name in self._config.mcp_servers
        }
        logger.info(
            "mcp start config_path=%s servers=%s",
            self.config_path,
            ",".join(sorted(self._config.mcp_servers)) or "-",
        )

        for server_name, server_config in self._config.mcp_servers.items():
            session = _StdioMcpSession(
                server_name=server_name,
                server_config=server_config,
                repo_root=self.repo_root,
                request_timeout_seconds=self.request_timeout_seconds,
                client_name=self.client_name,
                client_version=self.client_version,
            )
            try:
                await session.start()
                tools = await session.list_tools()
            except Exception as exc:
                logger.exception("mcp connect failed server=%s error=%s", server_name, exc)
                await session.close()
                continue

            self._sessions[server_name] = session
            self._statuses[server_name] = "connected"
            for tool in tools:
                self._tools_by_name[tool.prefixed_name] = tool

            logger.info(
                "mcp connected server=%s tools=%s",
                server_name,
                ",".join(tool.prefixed_name for tool in tools) or "-",
            )

        self._started = True

    async def close(self) -> None:
        sessions = list(self._sessions.items())
        self._sessions = {}
        self._tools_by_name = {}
        if self._config is not None:
            self._statuses = {
                server_name: "disconnected"
                for server_name in self._config.mcp_servers
            }
        self._started = False

        for server_name, session in sessions:
            try:
                await session.close()
                logger.info("mcp closed server=%s", server_name)
            except Exception:
                logger.exception("mcp close failed server=%s", server_name)

    def servers(self) -> list[str]:
        if self._config is None:
            return []
        return sorted(self._config.mcp_servers)

    def server_status(self, name: str) -> McpServerStatus:
        return self._statuses.get(name, "disconnected")

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None:
        return parse_mcp_tool_name(prefixed_name)

    def list_tools(self) -> list[McpToolInfo]:
        return sorted(self._tools_by_name.values(), key=lambda tool: tool.prefixed_name)

    def list_server_tools(self, server_name: str) -> list[McpToolInfo]:
        return [
            tool
            for tool in self.list_tools()
            if tool.server == server_name
        ]

    def get_tool(self, prefixed_name: str) -> McpToolInfo | None:
        return self._tools_by_name.get(prefixed_name)

    async def call_tool(
        self,
        prefixed_name: str,
        arguments: dict[str, Any],
        signal: object | None = None,
    ) -> str:
        del signal
        parsed_name = self.parse_name(prefixed_name)
        if parsed_name is None:
            raise McpClientError(f"Invalid MCP tool name: {prefixed_name}")

        server_name, tool_name = parsed_name
        session = self._sessions.get(server_name)
        if session is None:
            raise McpClientError(f"MCP server not connected: {server_name}")

        started_at = perf_counter()
        try:
            output = await session.call_tool(tool_name, arguments)
        except Exception:
            duration_ms = max(0, int((perf_counter() - started_at) * 1000))
            logger.exception(
                "mcp call failed server=%s tool=%s duration_ms=%s",
                server_name,
                tool_name,
                duration_ms,
            )
            raise

        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        logger.info("mcp call server=%s tool=%s duration_ms=%s", server_name, tool_name, duration_ms)
        return output


__all__ = [
    "McpClientError",
    "StdioMcpManager",
]
