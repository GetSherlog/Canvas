"""
Cell-Creating Tool Wrappers

This module provides tool wrappers that automatically create notebook cells
when tools are called by Agno agents.
"""
import logging
from typing import Any, Optional, Callable, TYPE_CHECKING
import asyncio
from functools import wraps
import aiohttp

from agno.tools.mcp import MCPTools
from backend.config import get_settings

if TYPE_CHECKING:
    from backend.services.notebook_manager import NotebookManager

logger = logging.getLogger("ai.cell_creating_tools")


class CellCreatingMCPTools:
    """
    Wrapper around MCPTools that creates notebook cells for each tool call.
    Uses HTTP API calls to create cells to avoid async context issues.
    """
    
    def __init__(
        self, 
        mcp_tools: MCPTools,
        notebook_id: str,
        agent_type: str = "unknown"
    ):
        self.mcp_tools = mcp_tools
        self.notebook_id = notebook_id
        self.agent_type = agent_type
        self.settings = get_settings()
        
        # API endpoint for creating cells
        self.api_base_url = f"http://localhost:{self.settings.api_port}/api/v1"
        
        # Wrap all tool methods
        self._wrap_tools()
    
    def _wrap_tools(self):
        """Wrap all tool methods to create cells"""
        # Try to get available tools from the MCP instance
        # Since MCPTools might not have 'available_tools', we'll use a different approach
        # We'll wrap methods that look like tools (callable and not private)
        for attr_name in dir(self.mcp_tools):
            if not attr_name.startswith('_'):  # Skip private methods
                attr = getattr(self.mcp_tools, attr_name, None)
                if attr and callable(attr) and not isinstance(attr, type):
                    # This looks like a tool method
                    wrapped_tool = self._create_cell_wrapper(attr_name, attr)
                    setattr(self, attr_name, wrapped_tool)
    
    def _create_cell_wrapper(self, tool_name: str, original_tool: Callable):
        """Create a wrapper function that creates a cell when the tool is called"""
        
        @wraps(original_tool)
        async def wrapper(*args, **kwargs):
            # Capture tool arguments
            tool_args = {
                "args": list(args) if args else [],
                "kwargs": kwargs if kwargs else {}
            }
            
            # Create the cell via HTTP API before executing the tool
            cell_id = None
            try:
                async with aiohttp.ClientSession() as session:
                    # Use the new endpoint to create a cell from tool call
                    url = f"{self.api_base_url}/notebooks/{self.notebook_id}/cells/from-tool"
                    payload = {
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "agent_type": self.agent_type,
                        "metadata": {
                            "status": "executing"
                        }
                    }
                    
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            data = await response.json()
                            cell_id = data.get("id")
                            logger.info(f"Created cell {cell_id} for tool {tool_name}")
                        else:
                            logger.error(f"Failed to create cell via API: {response.status}")
            
            except Exception as e:
                logger.error(f"Failed to create cell for tool {tool_name}: {e}")
                # Continue with tool execution even if cell creation fails
            
            # Execute the original tool
            result = None
            error = None
            try:
                # Handle both sync and async tools
                if asyncio.iscoroutinefunction(original_tool):
                    result = await original_tool(*args, **kwargs)
                else:
                    result = original_tool(*args, **kwargs)
                    
            except Exception as e:
                error = str(e)
                logger.error(f"Tool {tool_name} execution failed: {e}")
                raise
            
            finally:
                # Update the cell with the result via HTTP API
                if cell_id:
                    try:
                        async with aiohttp.ClientSession() as session:
                            url = f"{self.api_base_url}/notebooks/{self.notebook_id}/cells/{cell_id}"
                            
                            # Prepare the result for JSON serialization
                            serializable_result = result
                            if not isinstance(result, (str, int, float, bool, list, dict, type(None))):
                                serializable_result = str(result)
                            
                            payload = {
                                "result": {
                                    "content": serializable_result,
                                    "error": error
                                },
                                "metadata": {
                                    "tool_name": tool_name,
                                    "agent_type": self.agent_type,
                                    "status": "error" if error else "success"
                                }
                            }
                            
                            async with session.patch(url, json=payload) as response:
                                if response.status == 200:
                                    logger.info(f"Updated cell {cell_id} with result")
                                else:
                                    logger.error(f"Failed to update cell via API: {response.status}")
                            
                    except Exception as e:
                        logger.error(f"Failed to update cell {cell_id} with result: {e}")
            
            return result
        
        return wrapper
    
    def __getattr__(self, name):
        """Forward any other attribute access to the wrapped MCPTools"""
        return getattr(self.mcp_tools, name)


def create_cell_creating_tools(
    tools: Any,
    notebook_id: str,
    notebook_manager: Optional["NotebookManager"] = None,  # Kept for compatibility
    agent_type: str = "unknown"
) -> Any:
    """
    Wrap tools to create cells when called.
    
    Args:
        tools: The tools to wrap (MCPTools or callable)
        notebook_id: The notebook to create cells in
        notebook_manager: The notebook manager instance (optional, not used with HTTP API)
        agent_type: The type of agent using these tools
    
    Returns:
        Wrapped tools that create cells
    """
    if isinstance(tools, MCPTools):
        return CellCreatingMCPTools(tools, notebook_id, agent_type)
    elif callable(tools):
        # For simple callable tools, wrap them directly
        return _create_simple_cell_wrapper(tools, notebook_id, agent_type)
    else:
        # For other tool types (like ReasoningTools), return as-is
        return tools


def _create_simple_cell_wrapper(
    tool: Callable,
    notebook_id: str,
    agent_type: str
) -> Callable:
    """Wrap a simple callable tool to create cells"""
    settings = get_settings()
    api_base_url = f"http://localhost:{settings.api_port}/api/v1"
    
    @wraps(tool)
    async def wrapper(*args, **kwargs):
        # Similar implementation as CellCreatingMCPTools._create_cell_wrapper
        tool_name = tool.__name__
        tool_args = {
            "args": list(args) if args else [],
            "kwargs": kwargs if kwargs else {}
        }
        
        # Create cell via API
        cell_id = None
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{api_base_url}/notebooks/{notebook_id}/cells/from-tool"
                payload = {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "agent_type": agent_type,
                    "metadata": {"status": "executing"}
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        cell_id = data.get("id")
                        logger.info(f"Created cell {cell_id} for tool {tool_name}")
        except Exception as e:
            logger.error(f"Failed to create cell for tool {tool_name}: {e}")
        
        # Execute tool
        result = None
        error = None
        try:
            if asyncio.iscoroutinefunction(tool):
                result = await tool(*args, **kwargs)
            else:
                result = tool(*args, **kwargs)
        except Exception as e:
            error = str(e)
            raise
        finally:
            # Update cell with result
            if cell_id:
                try:
                    async with aiohttp.ClientSession() as session:
                        url = f"{api_base_url}/notebooks/{notebook_id}/cells/{cell_id}"
                        serializable_result = result
                        if not isinstance(result, (str, int, float, bool, list, dict, type(None))):
                            serializable_result = str(result)
                        
                        payload = {
                            "result": {"content": serializable_result, "error": error},
                            "metadata": {
                                "tool_name": tool_name,
                                "agent_type": agent_type,
                                "status": "error" if error else "success"
                            }
                        }
                        
                        async with session.patch(url, json=payload) as response:
                            if response.status == 200:
                                logger.info(f"Updated cell {cell_id} with result")
                except Exception as e:
                    logger.error(f"Failed to update cell {cell_id}: {e}")
        
        return result
    
    return wrapper