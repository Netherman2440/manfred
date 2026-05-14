from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.domain import FunctionToolDefinition, ToolDefinition, WebSearchToolDefinition
from app.mcp import McpManager, parse_mcp_tool_name
from app.tools.registry import ToolRegistry

AGENT_EXTENSION = ".agent.md"
logger = logging.getLogger("app.services.agent_loader")


@dataclass(slots=True, frozen=True)
class AgentTemplate:
    agent_name: str
    model: str | None
    color: str | None
    description: str | None
    tools: list[str]
    system_prompt: str
    source_dir: Path


@dataclass(slots=True, frozen=True)
class LoadedAgent:
    agent_name: str
    model: str | None
    tools: list[ToolDefinition]
    system_prompt: str


class AgentLoader:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        mcp_manager: McpManager,
        repo_root: Path,
        workspace_path: str,
    ) -> None:
        self.tool_registry = tool_registry
        self.mcp_manager = mcp_manager
        self.repo_root = repo_root
        self.workspace_path = workspace_path

    def load_agent(self, agent_path: str | Path) -> LoadedAgent:
        file_path = self._resolve_agent_path(agent_path)
        template = self.load_agent_template(file_path)
        tools = self.resolve_tool_definitions(template.tools)
        return LoadedAgent(
            agent_name=template.agent_name,
            model=template.model,
            tools=tools,
            system_prompt=template.system_prompt,
        )

    def load_agent_by_name(self, agent_name: str) -> LoadedAgent:
        normalized_name = agent_name.strip()
        if (
            not normalized_name
            or normalized_name in {".", ".."}
            or Path(normalized_name).name != normalized_name
            or any(sep in normalized_name for sep in ("/", "\\"))
        ):
            raise ValueError("agent_name must be a non-empty string")

        return self.load_agent(self._agent_path_for_name(normalized_name))

    def load_agent_template(self, agent_path: str | Path) -> AgentTemplate:
        path = Path(agent_path)
        # Accept either a folder (agents/{name}/) or a file ({name}.agent.md)
        if not path.is_absolute():
            path = self.repo_root / path
        path = path.resolve()

        if path.is_dir():
            # Folder-based: look for {name}.agent.md inside
            folder_name = path.name
            file_path = path / f"{folder_name}{AGENT_EXTENSION}"
        else:
            file_path = path

        content = file_path.read_text(encoding="utf-8")
        metadata, system_prompt = self._split_frontmatter(content)

        raw_agent_name = metadata.get("agent_name") or metadata.get("name")
        agent_name = str(raw_agent_name or self._agent_name_from_path(file_path))
        agent_name = self._unquote(agent_name)
        model = metadata.get("model")
        if not isinstance(model, str) or not model.strip():
            model = None
        else:
            model = self._unquote(model.strip()) or None

        color = metadata.get("color")
        if not isinstance(color, str) or not color.strip():
            color = None
        else:
            color = self._unquote(color.strip()) or None

        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            description = None
        else:
            description = self._unquote(description.strip()) or None

        raw_tools = metadata.get("tools")
        tools = raw_tools if isinstance(raw_tools, list) else []

        return AgentTemplate(
            agent_name=agent_name,
            model=model,
            color=color,
            description=description,
            tools=[tool for tool in tools if isinstance(tool, str) and tool.strip()],
            system_prompt=system_prompt.strip(),
            source_dir=file_path.parent,
        )

    def resolve_tool_definitions(self, tool_names: list[str]) -> list[ToolDefinition]:
        resolved: list[ToolDefinition] = []
        registered_tools = {
            tool.name: tool for tool in self.tool_registry.list() if isinstance(tool, FunctionToolDefinition)
        }

        for tool_name in tool_names:
            if tool_name == "web_search":
                resolved.append(WebSearchToolDefinition())
                continue

            tool = registered_tools.get(tool_name)
            if tool is not None:
                resolved.append(tool)
                continue

            if parse_mcp_tool_name(tool_name) is None:
                continue

            mcp_tool = self.mcp_manager.get_tool(tool_name)
            if mcp_tool is None:
                logger.warning("mcp tool not found during agent load tool=%s", tool_name)
                continue

            resolved.append(
                FunctionToolDefinition(
                    name=mcp_tool.prefixed_name,
                    description=mcp_tool.description,
                    parameters=mcp_tool.input_schema,
                )
            )

        return resolved

    def _resolve_agent_path(self, agent_path: str | Path) -> Path:
        path = Path(agent_path)
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def _agent_path_for_name(self, agent_name: str) -> Path:
        return Path(self.workspace_path) / "agents" / agent_name / f"{agent_name}{AGENT_EXTENSION}"

    @staticmethod
    def _unquote(value: str) -> str:
        """Strip surrounding double or single quotes from a metadata value."""
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            return value[1:-1].replace('\\"', '"')
        if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            return value[1:-1].replace("\\'", "'")
        return value

    @staticmethod
    def _agent_name_from_path(agent_path: Path) -> str:
        if agent_path.name.endswith(AGENT_EXTENSION):
            return agent_path.name[: -len(AGENT_EXTENSION)]
        return agent_path.stem

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[dict[str, object], str]:
        if not content.startswith("---\n"):
            return {}, content

        closing_index = content.find("\n---\n", 4)
        if closing_index == -1:
            return {}, content

        raw_metadata = content[4:closing_index]
        body = content[closing_index + len("\n---\n") :]
        return AgentLoader._parse_frontmatter(raw_metadata), body

    @staticmethod
    def _parse_frontmatter(raw_metadata: str) -> dict[str, object]:
        metadata: dict[str, object] = {}
        current_list_key: str | None = None

        for raw_line in raw_metadata.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            if line.startswith("  - ") and current_list_key is not None:
                values = metadata.setdefault(current_list_key, [])
                if isinstance(values, list):
                    values.append(stripped[2:].strip())
                continue

            if ":" not in stripped:
                current_list_key = None
                continue

            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                current_list_key = None
                continue

            if value:
                metadata[key] = value
                current_list_key = None
                continue

            metadata[key] = []
            current_list_key = key

        return metadata


def render_agent_frontmatter(template: AgentTemplate) -> str:
    """Render deterministic frontmatter compatible with AgentLoader._parse_frontmatter.

    Key order: name, model, color, description, tools.
    Strings containing ':', '#', or quotes are wrapped in double-quotes.
    """

    def _quote_if_needed(value: str) -> str:
        if any(ch in value for ch in (":", "#", '"', "'", "\n", "\r", "\\")):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
            return f'"{escaped}"'
        return value

    lines: list[str] = ["---"]

    lines.append(f"name: {_quote_if_needed(template.agent_name)}")

    if template.model:
        lines.append(f"model: {_quote_if_needed(template.model)}")
    else:
        lines.append("model:")

    if template.color:
        lines.append(f"color: {_quote_if_needed(template.color)}")
    else:
        lines.append("color:")

    if template.description:
        lines.append(f"description: {_quote_if_needed(template.description)}")
    else:
        lines.append("description:")

    if template.tools:
        lines.append("tools:")
        for tool in template.tools:
            lines.append(f"  - {tool}")
    else:
        lines.append("tools:")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)
