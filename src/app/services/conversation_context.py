from app.db.repositories.agent_repository import AgentRepository
from app.db.repositories.session_repository import SessionRepository
from app.db.repositories.user_repository import UserRepository
from app.domain import Agent, Session, User, prepare_agent_for_next_turn
from app.workspaces import AgentTemplateLoader


class ConversationContextService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        agent_template_loader: AgentTemplateLoader,
        default_user_id: str,
        default_user_name: str,
        root_agent_template_name: str,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._agent_repository = agent_repository
        self._agent_template_loader = agent_template_loader
        self._default_user_id = default_user_id
        self._default_user_name = default_user_name
        self._root_agent_template_name = root_agent_template_name

    def ensure_default_user(self) -> User:
        user = self._user_repository.get_by_id(self._default_user_id)
        if user is not None:
            return user

        return self._user_repository.create(
            name=self._default_user_name,
            user_id=self._default_user_id,
        )

    def load_or_create_session(self, session_id: str | None, user: User) -> Session:
        if session_id:
            session = self._session_repository.get_by_id(session_id)
            if session is not None:
                return session

        return self._session_repository.create(user_id=user.id)

    def load_or_create_root_agent(self, session: Session) -> Agent:
        root_template = self._agent_template_loader.load(self._root_agent_template_name)
        agent_config = root_template.to_agent_config()

        if session.root_agent_id:
            agent = self._agent_repository.get_by_id(session.root_agent_id)
            if agent is not None:
                prepared_agent = prepare_agent_for_next_turn(agent, config=agent_config)
                return self._agent_repository.update(prepared_agent)

        agent = self._agent_repository.create(
            session_id=session.id,
            config=agent_config,
        )

        updated_session = Session(
            id=session.id,
            user_id=session.user_id,
            root_agent_id=agent.id,
            status=session.status,
            summary=session.summary,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        self._session_repository.update(updated_session)
        return agent
