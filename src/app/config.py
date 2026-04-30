from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Manfred API"
    VERSION: str = "0.0.0-dev"
    DESCRIPTION: str = "Agent API"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 3000
    API_RELOAD: bool = True
    API_CORS_ORIGINS: str = ""
    API_CORS_ALLOW_LOCALHOST: bool = True
    DATABASE_URL: str = "sqlite:///./manfred.db"

    DEFAULT_AGENT: str = ".agent_data/agents/manfred.agent.md"
    WORKSPACE_PATH: str = ".agent_data"
    FS_ROOT: str = ""
    FS_ROOTS: str = (
        ".agent_data/agents, .agent_data/shared, .agent_data/skills, "
        ".agent_data/workflows, .agent_data/workspaces"
    )
    FS_EXCLUDE: str = ""
    MAX_FILE_SIZE: int = 524288
    MCP_CONFIG_PATH: str = ".mcp.json"
    MCP_TOOL_TIMEOUT_MS: int = 30000
    MAX_DELEGATION_DEPTH: int = 8

    OPEN_ROUTER_URL: str = "https://openrouter.ai/api/v1"
    OPEN_ROUTER_API_KEY: str = ""
    OPEN_ROUTER_LLM_MODEL: str = "openai/gpt-4o-mini"
    OPEN_ROUTER_SLM_MODEL: str = "openai/gpt-4o-mini"
    DEFAULT_USER_ID: str = "default-user"
    DEFAULT_USER_NAME: str = "Default User"

    #gemini? TODO

    #openai TODO
    
    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENVIRONMENT: str = "development"

    AI_DEVS_API_KEY: str = ""
    AI_DEVS_HUB_URL: str = "https://hub.ag3nts.org"

    def filesystem_roots(self) -> list[str]:
        if self.FS_ROOT.strip():
            return [self.FS_ROOT.strip()]
        roots = [item.strip() for item in self.FS_ROOTS.split(",") if item.strip()]
        if roots:
            return roots
        return []

    def filesystem_exclude_patterns(self) -> list[str]:
        return [item.strip() for item in self.FS_EXCLUDE.split(",") if item.strip()]
