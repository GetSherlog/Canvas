"""
Workspace Connection Handler for LogAI MCP Server
"""

import logging
from typing import Dict, Optional, List, Any, Tuple, Literal
from pydantic import BaseModel, Field, field_validator

from .base import MCPConnectionHandler
from backend.core.types import MCPToolInfo
from .registry import register_handler
from mcp import StdioServerParameters

logger = logging.getLogger(__name__)


# Define the StdioParams type alias
StdioParams = StdioServerParameters


class TestConnectionResult(BaseModel):
    """Result of a connection test"""
    valid: bool
    message: str


class WorkspaceConnectionConfig(BaseModel):
    """Configuration for the unified workspace (LogAI MCP server)"""
    
    type: Literal["logai_workspace"] = Field(default="logai_workspace", description="Connection type identifier")
    github_token: Optional[str] = Field(None, description="GitHub Personal Access Token")
    filesystem_paths: List[str] = Field(..., description="Filesystem paths to mount")
    working_dir: str = Field(default="/workspace", description="Working directory in container")
    extra_args: Optional[str] = Field(None, description="Extra Docker arguments")
    
    @field_validator('filesystem_paths')
    @classmethod
    def validate_paths(cls, v: List[str]) -> List[str]:
        """Ensure at least one valid path is provided"""
        valid_paths = [p.strip() for p in v if p.strip()]
        if not valid_paths:
            raise ValueError("At least one filesystem path is required")
        return valid_paths


# API Models for use in the connections route
class WorkspaceConnectionCreate(WorkspaceConnectionConfig):
    """Model for creating a workspace connection"""
    pass


class WorkspaceConnectionUpdate(BaseModel):
    """Model for updating a workspace connection"""
    type: Literal["logai_workspace"] = Field(default="logai_workspace", description="Connection type identifier")
    github_token: Optional[str] = Field(None, description="GitHub Personal Access Token")
    filesystem_paths: Optional[List[str]] = Field(None, description="Filesystem paths to mount")
    working_dir: Optional[str] = Field(None, description="Working directory in container")
    extra_args: Optional[str] = Field(None, description="Extra Docker arguments")
    
    @field_validator('filesystem_paths')
    @classmethod
    def validate_paths(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Ensure at least one valid path is provided if paths are specified"""
        if v is None:
            return v
        valid_paths = [p.strip() for p in v if p.strip()]
        if not valid_paths:
            raise ValueError("At least one filesystem path is required")
        return valid_paths


class WorkspaceConnectionTest(WorkspaceConnectionConfig):
    """Model for testing a workspace connection"""
    pass


class WorkspaceConnectionHandler(MCPConnectionHandler):
    """Handler for the unified workspace configuration"""
    
    def get_connection_type(self) -> str:
        return "logai_workspace"
    
    def get_display_name(self) -> str:
        return "Workspace Configuration"
    
    def get_description(self) -> str:
        return "Configure your unified workspace with GitHub, filesystem, Python, and log analysis capabilities"
    
    async def prepare_config(self, connection_id: Optional[str], input_data: BaseModel, existing_config: Optional[Dict] = None) -> Dict[str, Any]:
        """Prepare configuration for storage"""
        if not isinstance(input_data, (WorkspaceConnectionCreate, WorkspaceConnectionUpdate, WorkspaceConnectionTest)):
            raise ValueError("Invalid input data type")
        
        # Convert the Pydantic model to dict
        config_dict = input_data.model_dump(exclude_unset=True, exclude={'type'})
        
        # If updating, merge with existing config
        if existing_config:
            existing_config.update(config_dict)
            return existing_config
        
        return config_dict
    
    async def test_connection(self, config_to_test: Dict[str, Any]) -> Tuple[bool, str]:
        """Test the workspace configuration"""
        # Convert dict to model for validation
        try:
            config = WorkspaceConnectionConfig(**config_to_test, type="logai_workspace")
        except Exception as e:
            return False, f"Invalid configuration: {str(e)}"
        
        # Basic validation - just check that paths are provided
        if not config.filesystem_paths:
            return False, "At least one filesystem path is required"
        
        # Could add more validation here (e.g., check if paths exist, validate GitHub token)
        # For now, just return success if basic validation passes
        return True, f"Workspace configuration valid with {len(config.filesystem_paths)} filesystem path(s)"
    
    def get_stdio_params(self, db_config: Dict[str, Any]) -> StdioParams:
        """Get stdio parameters for the LogAI MCP server"""
        # Convert dict to model for easier access
        config = WorkspaceConnectionConfig(**db_config, type="logai_workspace")
        
        # Get settings for the LogAI MCP server
        from backend.config import get_settings
        settings = get_settings()
        
        import os
        env = os.environ.copy()
        
        # Add GitHub token if provided
        if config.github_token:
            env["GITHUB_TOKEN"] = config.github_token
        
        # Add all LogAI MCP integration environment variables
        if settings.logai_mcp_grafana_url:
            env["GRAFANA_URL"] = settings.logai_mcp_grafana_url
        if settings.logai_mcp_grafana_token:
            env["GRAFANA_TOKEN"] = settings.logai_mcp_grafana_token
        if settings.logai_mcp_prometheus_url:
            env["PROMETHEUS_URL"] = settings.logai_mcp_prometheus_url
        if settings.logai_mcp_loki_url:
            env["LOKI_URL"] = settings.logai_mcp_loki_url
        if settings.logai_mcp_aws_access_key:
            env["AWS_ACCESS_KEY_ID"] = settings.logai_mcp_aws_access_key
        if settings.logai_mcp_aws_secret_key:
            env["AWS_SECRET_ACCESS_KEY"] = settings.logai_mcp_aws_secret_key
        if settings.logai_mcp_aws_region:
            env["AWS_DEFAULT_REGION"] = settings.logai_mcp_aws_region
        if settings.logai_mcp_sentry_auth_token:
            env["SENTRY_AUTH_TOKEN"] = settings.logai_mcp_sentry_auth_token
        if settings.logai_mcp_sentry_org:
            env["SENTRY_ORG"] = settings.logai_mcp_sentry_org
        if settings.logai_mcp_mixpanel_token:
            env["MIXPANEL_TOKEN"] = settings.logai_mcp_mixpanel_token
        
        # Build Docker arguments
        docker_args = ["run", "--rm", "-i"]
        
        # Add Docker socket for nested operations
        docker_args.extend(["--volume=/var/run/docker.sock:/var/run/docker.sock"])
        
        # Add network mode for external service access
        docker_args.extend(["--network", "host"])
        
        # Mount filesystem paths
        for path in config.filesystem_paths:
            if path.strip():
                docker_args.extend(["-v", f"{path}:{path}:ro"])
        
        # Add working directory if different from default
        if config.working_dir and config.working_dir != "/workspace":
            docker_args.extend(["-w", config.working_dir])
        
        # Add extra arguments if provided
        if config.extra_args:
            # Parse extra args (could be space-separated or newline-separated)
            extra_args_list = config.extra_args.replace('\n', ' ').split()
            docker_args.extend(extra_args_list)
        
        # Add the image
        docker_args.append(settings.logai_mcp_image)
        
        return StdioParams(
            command=settings.logai_mcp_command,
            args=docker_args,
            env=env
        )
    
    
    def get_create_model(self):
        """Return the Pydantic model for creating connections of this type"""
        return WorkspaceConnectionCreate
    
    def get_update_model(self):
        """Return the Pydantic model for updating connections of this type"""
        return WorkspaceConnectionUpdate
    
    def get_test_model(self):
        """Return the Pydantic model for testing connections of this type"""
        return WorkspaceConnectionTest
    
    def get_sensitive_fields(self) -> List[str]:
        """Return list of fields that should be redacted in API responses"""
        return ['github_token']
    
    async def execute_tool_call(self, tool_name: str, tool_args: Dict[str, Any], db_config: Dict[str, Any], correlation_id: Optional[str] = None) -> Any:
        """Execute a tool call through the MCP server"""
        # This would typically create an MCP client and execute the tool
        # For now, we'll raise NotImplementedError as this is handled elsewhere
        raise NotImplementedError("Tool execution is handled by the investigation system")
    


# Register the handler
handler_instance = WorkspaceConnectionHandler()
register_handler(handler_instance)