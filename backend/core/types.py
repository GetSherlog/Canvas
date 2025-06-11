from uuid import UUID, uuid4
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from backend.core.dependency import ToolCallID # Assuming ToolCallID is here


class ToolCallRecord(BaseModel):
    """
    Represents the state and result of a specific tool call execution.
    
    Attributes:
        id: Unique identifier for this specific tool call execution instance.
        parent_cell_id: ID of the cell that initiated or contains this tool call.
        pydantic_ai_tool_call_id: The tool_call_id provided by pydantic-ai (from ToolCallPart).
        tool_name: The name of the tool being called.
        parameters: Parsed parameters for the tool call. May contain ToolOutputReference.
        status: Execution status (e.g., pending, running, success, error).
        started_at: Timestamp when execution started.
        completed_at: Timestamp when execution finished.
        result: The primary result content returned by the tool (from ToolReturnPart content).
        error: Error message if the tool execution failed.
        named_outputs: Dictionary to store potentially multiple named outputs from the tool, 
                       used for dependency resolution.
    """
    id: ToolCallID = Field(default_factory=uuid4)
    parent_cell_id: UUID
    pydantic_ai_tool_call_id: str
    tool_name: str
    parameters: Dict[str, Any]
    status: str = "pending" 
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    named_outputs: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True # Allow ToolOutputReference in parameters 


# --- Simplified Tool Info Structure --- 
class MCPToolInfo(BaseModel):
    """Basic information about a tool provided by an MCP server."""
    name: str
    description: Optional[str] = None
    inputSchema: Dict[str, Any] # Raw JSON Schema from MCP

# --- End Simplified Tool Info Structure --- 