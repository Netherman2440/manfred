from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app.db.models import AgentModel
from app.db.models.session import SessionModel
from app.domain import User
from app.services.agent_loader import AgentLoader, AgentTemplate, render_agent_frontmatter
from app.services.filesystem import WorkspaceLayoutService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AgentTemplateError(Exception):
    pass


class AgentTemplateNotFound(AgentTemplateError):
    pass


class AgentTemplateExists(AgentTemplateError):
    pass


class AgentTemplateInvalid(AgentTemplateError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentTemplateSummary:
    name: str
    color: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class AgentTemplateDetail:
    name: str
    color: str | None
    description: str | None
    model: str | None
    system_prompt: str
    tools: list[str]


@dataclass(frozen=True, slots=True)
class AgentTemplateInput:
    name: str
    color: str | None
    description: str | None
    model: str | None
    tools: list[str]
    system_prompt: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
AGENT_EXTENSION = ".agent.md"


class AgentTemplateService:
    NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
    RESERVED_NAMES = frozenset({"default", "agents", "shared", "skills", "workflows", "workspaces", "."})

    def __init__(
        self,
        *,
        agent_loader: AgentLoader,
        workspace_layout_service: WorkspaceLayoutService,
        db_session: DbSession,
    ) -> None:
        self.agent_loader = agent_loader
        self.workspace_layout_service = workspace_layout_service
        self.db_session = db_session

    def _agents_dir(self, user: User) -> Path:
        layout = self.workspace_layout_service.ensure_user_workspace(user)
        return layout.root / "agents"

    def list_templates(self, user: User) -> list[AgentTemplateSummary]:
        agents_dir = self._agents_dir(user)
        summaries: list[AgentTemplateSummary] = []
        if not agents_dir.exists():
            return summaries

        for entry in sorted(agents_dir.iterdir()):
            if not entry.is_dir():
                continue
            agent_file = entry / f"{entry.name}{AGENT_EXTENSION}"
            if not agent_file.exists():
                continue
            try:
                template = self.agent_loader.load_agent_template(agent_file)
                summaries.append(
                    AgentTemplateSummary(
                        name=template.agent_name,
                        color=template.color,
                        description=template.description,
                    )
                )
            except Exception:
                logger.warning("Skipping unreadable agent %s", agent_file, exc_info=True)
                continue

        return summaries

    def get_template(self, user: User, name: str) -> AgentTemplateDetail | None:
        self._validate_name(name)
        agents_dir = self._agents_dir(user)
        agent_dir = agents_dir / name
        if not agent_dir.exists():
            return None
        agent_file = agent_dir / f"{name}{AGENT_EXTENSION}"
        if not agent_file.exists():
            return None
        template = self.agent_loader.load_agent_template(agent_file)
        return self._to_detail(template)

    def create_template(self, user: User, payload: AgentTemplateInput) -> AgentTemplateDetail:
        self._validate_payload(payload)

        agents_dir = self._agents_dir(user)
        agent_dir = agents_dir / payload.name
        if agent_dir.exists():
            raise AgentTemplateExists(f"Agent already exists: {payload.name}")

        agent_dir.mkdir(parents=True, exist_ok=False)
        self._write_agent_file(agent_dir, payload)

        template = self.agent_loader.load_agent_template(agent_dir / f"{payload.name}{AGENT_EXTENSION}")
        return self._to_detail(template)

    def update_template(self, user: User, name: str, payload: AgentTemplateInput) -> AgentTemplateDetail:
        logger.info("update_template name=%s color=%s model=%s", name, payload.color, payload.model)
        self._validate_name(name)
        if payload.name != name:
            raise AgentTemplateInvalid("name", "Rename not supported — name must match URL path parameter.")

        self._validate_payload(payload)

        agents_dir = self._agents_dir(user)
        agent_dir = agents_dir / name
        if not agent_dir.exists():
            raise AgentTemplateNotFound(f"Agent not found: {name}")

        self._write_agent_file(agent_dir, payload, atomic=True)

        agent_file = agent_dir / f"{name}{AGENT_EXTENSION}"
        template = self.agent_loader.load_agent_template(agent_file)
        logger.info(
            "update_template after reload name=%s color=%s model=%s file=%s",
            template.agent_name,
            template.color,
            template.model,
            agent_file,
        )
        return self._to_detail(template)

    def delete_template(self, user: User, name: str) -> None:
        self._validate_name(name)
        agents_dir = self._agents_dir(user)
        agent_dir = agents_dir / name
        if not agent_dir.exists():
            raise AgentTemplateNotFound(f"Agent not found: {name}")

        # Delete DB records first so a filesystem failure leaves DB clean.
        # If rmtree fails after a successful commit, the folder becomes orphaned
        # but can be cleaned up manually without data loss.
        try:
            user_session_ids = [
                row.id for row in self.db_session.query(SessionModel.id).filter(SessionModel.user_id == user.id).all()
            ]
            self.db_session.query(AgentModel).filter(
                AgentModel.agent_name == name,
                AgentModel.session_id.in_(user_session_ids),
            ).delete(synchronize_session=False)
            self.db_session.commit()
        except Exception:
            self.db_session.rollback()
            raise
        shutil.rmtree(agent_dir)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_name(self, name: str) -> None:
        if not self.NAME_PATTERN.match(name):
            raise AgentTemplateInvalid(
                "name",
                "Name must match ^[a-z][a-z0-9_-]{0,47}$ (lowercase, starts with letter, max 48 chars).",
            )
        if name in self.RESERVED_NAMES:
            raise AgentTemplateInvalid("name", f"Name '{name}' is reserved.")

    def _validate_payload(self, payload: AgentTemplateInput) -> None:
        self._validate_name(payload.name)

        if payload.color is not None and not _COLOR_PATTERN.match(payload.color):
            raise AgentTemplateInvalid("color", "Color must be #RRGGBB hex string or null.")

        if payload.model is not None and not payload.model.strip():
            raise AgentTemplateInvalid("model", "Model must be a non-empty string or null.")

    def _write_agent_file(
        self,
        agent_dir: Path,
        payload: AgentTemplateInput,
        *,
        atomic: bool = False,
    ) -> None:
        template = AgentTemplate(
            agent_name=payload.name,
            model=payload.model,
            color=payload.color,
            description=payload.description,
            tools=list(payload.tools),
            system_prompt=payload.system_prompt,
            source_dir=agent_dir,
        )
        content = render_agent_frontmatter(template) + payload.system_prompt

        target_file = agent_dir / f"{payload.name}{AGENT_EXTENSION}"
        logger.debug(
            "_write_agent_file target=%s atomic=%s color=%s prompt_len=%d",
            target_file,
            atomic,
            payload.color,
            len(payload.system_prompt),
        )
        if atomic:
            tmp_file = target_file.with_suffix(".tmp")
            tmp_file.write_text(content, encoding="utf-8")
            os.replace(tmp_file, target_file)
        else:
            target_file.write_text(content, encoding="utf-8")
        logger.info("_write_agent_file done target=%s", target_file)

    @staticmethod
    def _to_detail(template: AgentTemplate) -> AgentTemplateDetail:
        return AgentTemplateDetail(
            name=template.agent_name,
            color=template.color,
            description=template.description,
            model=template.model,
            system_prompt=template.system_prompt,
            tools=list(template.tools),
        )
