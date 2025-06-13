from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings"""
    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    # CORS settings
    cors_origins: list[str] = ["*"]
    # Authentication settings (for future use)
    auth_enabled: bool = False
    # AI settings
    openrouter_api_key: str = ""
    ai_model: str = "anthropic/claude-3.7-sonnet"
    sherlog_env: str = ""
    # Logging settings
    environment: str = "development"
    # Connection storage settings
    connection_storage_type: str = "file"  # Options: file, env, db, none
    connection_file_path: str = "./data/connections.json"
    # Database settings
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "sherlog"
    db_user: str = "sherlog"
    db_password: str = "sherlog"
    db_type: str = "sqlite"  # Options: sqlite, postgresql
    db_file: str = "./data/sherlog.db"
    # Redis settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None # Optional password
    chat_session_ttl: int = 3600 # Default TTL for chat sessions in Redis (1 hour)
    # AWS settings (for S3 storage)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    # Cell execution settings
    python_cell_timeout: int = 30  # seconds
    python_cell_max_memory: int = 1024  # MB
    # Query execution settings
    default_query_timeout: int = 30  # seconds
    
    # LogAI MCP Server settings
    logai_mcp_enabled: bool = True
    logai_mcp_command: str = "docker"  # Command to run LogAI MCP
    logai_mcp_image: str = "ghcr.io/getsherlog/mcp-sherlog-log-analysis:latest"
    logai_mcp_github_token: Optional[str] = None  # GitHub token for GitHub operations
    logai_mcp_working_dir: str = "/workspace"  # Working directory inside container
    logai_mcp_mount_dir: Optional[str] = None  # Host directory to mount
    logai_mcp_extra_args: list[str] = []  # Extra docker arguments
    
    # LogAI MCP Integration settings (v0.1.6)
    logai_mcp_grafana_url: Optional[str] = None
    logai_mcp_grafana_token: Optional[str] = None
    logai_mcp_prometheus_url: Optional[str] = None
    logai_mcp_loki_url: Optional[str] = None
    logai_mcp_aws_access_key: Optional[str] = None
    logai_mcp_aws_secret_key: Optional[str] = None
    logai_mcp_aws_region: str = "us-east-1"
    logai_mcp_sentry_auth_token: Optional[str] = None
    logai_mcp_sentry_org: Optional[str] = None
    logai_mcp_mixpanel_token: Optional[str] = None
    logai_mcp_external_mcp_servers: list[dict] = []
    
    # Environment settings
    environment_vars: dict = {}
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="SHERLOG_",
    )
    
    @property
    def database_url(self) -> str:
        """Get the database URL based on db_type"""
        if self.db_type == "sqlite":
            return f"sqlite:///{self.db_file}"
        elif self.db_type == "postgresql":
            return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

@lru_cache
def get_settings() -> Settings:
    return Settings()