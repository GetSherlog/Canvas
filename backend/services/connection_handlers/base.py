"""
Base class/interface for MCP Connection Handlers
"""

from abc import ABC, abstractmethod
from typing import Type, Dict, Tuple, List, Optional, Any
from pydantic import BaseModel

from mcp import StdioServerParameters


class MCPConnectionHandler(ABC):
    """Abstract Base Class for handling specific MCP connection types."""

    @abstractmethod
    def get_connection_type(self) -> str:
        """Return the unique string identifier for this connection type (e.g., 'grafana')."""
        pass

    @abstractmethod
    def get_create_model(self) -> Type[BaseModel]:
        """Return the Pydantic model class used for validating connection creation data."""
        pass

    # Optional: Provide separate models if update/test differs significantly
    # Otherwise, subclasses can just return the create model or raise NotImplementedError
    def get_update_model(self) -> Type[BaseModel]:
        """Return the Pydantic model class used for validating connection update data."""
        # Default implementation assumes update uses the same fields as create, minus type/name potentially
        # Subclasses should override if the structure is different.
        # This might need refinement based on actual update logic.
        raise NotImplementedError("Update model not defined for this handler")

    def get_test_model(self) -> Type[BaseModel]:
        """Return the Pydantic model class used for validating connection test data."""
        # Default implementation assumes test uses the same structure as create.
        # Subclasses should override if different.
        raise NotImplementedError("Test model not defined for this handler")

    @abstractmethod
    async def prepare_config(self, connection_id: Optional[str], input_data: BaseModel, existing_config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Takes validated input data (from create/update models), an optional existing config,
        and returns the structured configuration dictionary to be stored in the database.
        This includes preparing commands, args, env vars, storing tokens securely (ideally encrypted),
        and performing any necessary transformations.
        Should raise ValueError on configuration errors not caught by Pydantic.
        Args:
            connection_id: The ID of the connection if updating, None otherwise.
            input_data: The validated Pydantic model instance from the request.
            existing_config: The current config from the DB if updating.

        Returns:
            The prepared configuration dictionary for DB storage.
        """
        pass

    @abstractmethod
    async def test_connection(self, config_to_test: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Takes a prepared configuration dictionary (potentially with temporary credentials)
        and attempts to validate the connection (e.g., by initiating an MCP session).

        Args:
            config_to_test: A dictionary representing the connection config to test.
                          This might be derived from prepare_config output or directly from a test request.

        Returns:
            Tuple (is_valid: bool, message: str)
        """
        pass

    @abstractmethod
    def get_stdio_params(self, db_config: Dict[str, Any]) -> StdioServerParameters:
        """
        Takes the configuration dictionary as stored in the database and constructs
        the StdioServerParameters needed to launch the MCP server process.

        Args:
            db_config: The configuration dictionary retrieved from the database.

        Returns:
            An instance of StdioServerParameters.
        """
        pass

    @abstractmethod
    def get_sensitive_fields(self) -> List[str]:
        """Return a list of top-level keys within the stored DB config that should be redacted."""
        pass

    @abstractmethod
    async def execute_tool_call(self, tool_name: str, tool_args: Dict[str, Any], db_config: Dict[str, Any], correlation_id: Optional[str] = None) -> Any:
        """
        Executes a specific tool call via the MCP server associated with this handler.

        Args:
            tool_name: The name of the tool to call.
            tool_args: The arguments for the tool call.
            db_config: The configuration dictionary retrieved from the database for this connection.
            correlation_id: Optional correlation ID for logging.

        Returns:
            The result from the MCP tool call.
            
        Raises:
            ValueError: If configuration is invalid (e.g., missing params).
            ConnectionError: If MCP server connection fails.
            McpError: If the tool call itself fails within the MCP server.
            Exception: For other unexpected errors.
        """
        pass

    # Optional helper for common validation patterns?
    # async def _run_mcp_validation(self, params: StdioServerParameters) -> Tuple[bool, str]:
    #     # Common logic for stdio_client, initialize, list_tools could go here
    #     pass

    async def post_create_actions(self, connection_config: Any) -> None: # Using Any to avoid circular import with ConnectionConfig from manager
        """
        Optional actions to perform after a connection has been successfully created and saved.
        For example, triggering initial data indexing.
        By default, does nothing. Subclasses can override.
        """
        pass
