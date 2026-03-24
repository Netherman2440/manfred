from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain import AgentConfig, ToolRegistry


@dataclass(slots=True, frozen=True)
class AgentTemplate:
    name: str
    model: str
    tool_names: tuple[str, ...]
    system_prompt: str

    def to_agent_config(self) -> AgentConfig:
        return AgentConfig(
            model=self.model,
            task=self.system_prompt,
            tool_names=self.tool_names,
        )


class AgentTemplateLoader:
    def __init__(
        self,
        *,
        templates_dir: Path,
        tool_registry: ToolRegistry,
        default_model: str,
    ) -> None:
        self._templates_dir = templates_dir
        self._tool_registry = tool_registry
        self._default_model = default_model

    def load(self, name: str) -> AgentTemplate:
        template_name = name.strip()
        if template_name == "":
            raise ValueError("Agent template name must not be empty.")

        template_path = self._templates_dir / f"{template_name}.agent.md"
        if not template_path.exists():
            raise ValueError(f"Agent template not found: {template_name}")

        content = template_path.read_text(encoding="utf-8")
        metadata, system_prompt = self._parse_template(content)
        resolved_name = self._require_string(metadata, "name", fallback=template_name)
        model = self._require_string(metadata, "model", fallback=self._default_model)
        tool_names = self._require_string_list(metadata, "tools")

        for tool_name in tool_names:
            if self._tool_registry.get(tool_name) is None:
                raise ValueError(
                    f"Agent template '{resolved_name}' references unknown tool: {tool_name}"
                )

        if system_prompt.strip() == "":
            raise ValueError(f"Agent template '{resolved_name}' has an empty system prompt.")

        return AgentTemplate(
            name=resolved_name,
            model=model,
            tool_names=tool_names,
            system_prompt=system_prompt.strip(),
        )

    @staticmethod
    def _parse_template(content: str) -> tuple[dict[str, object], str]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("Agent template must start with YAML-style frontmatter.")

        metadata_lines: list[str] = []
        body_start = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                body_start = index + 1
                break
            metadata_lines.append(lines[index])

        if body_start is None:
            raise ValueError("Agent template frontmatter is not closed.")

        metadata = AgentTemplateLoader._parse_frontmatter_lines(metadata_lines)
        body = "\n".join(lines[body_start:])
        return metadata, body

    @staticmethod
    def _parse_frontmatter_lines(lines: list[str]) -> dict[str, object]:
        metadata: dict[str, object] = {}
        current_list_key: str | None = None

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#"):
                continue

            if stripped.startswith("- "):
                if current_list_key is None:
                    raise ValueError("Invalid frontmatter list entry without a parent key.")
                items = metadata.setdefault(current_list_key, [])
                if not isinstance(items, list):
                    raise ValueError(f"Frontmatter key '{current_list_key}' must be a list.")
                items.append(AgentTemplateLoader._strip_quotes(stripped[2:].strip()))
                continue

            if ":" not in line:
                raise ValueError(f"Invalid frontmatter line: {line}")

            key, raw_value = line.split(":", 1)
            normalized_key = key.strip()
            value = raw_value.strip()

            if value == "":
                metadata[normalized_key] = []
                current_list_key = normalized_key
                continue

            metadata[normalized_key] = AgentTemplateLoader._strip_quotes(value)
            current_list_key = None

        return metadata

    @staticmethod
    def _require_string(metadata: dict[str, object], key: str, *, fallback: str | None = None) -> str:
        value = metadata.get(key, fallback)
        if not isinstance(value, str) or value.strip() == "":
            raise ValueError(f"Agent template field '{key}' must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _require_string_list(metadata: dict[str, object], key: str) -> tuple[str, ...]:
        value = metadata.get(key)
        if not isinstance(value, list) or not value:
            raise ValueError(f"Agent template field '{key}' must be a non-empty list.")

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or item.strip() == "":
                raise ValueError(f"Agent template field '{key}' must contain non-empty strings.")
            normalized.append(item.strip())
        return tuple(normalized)

    @staticmethod
    def _strip_quotes(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value
