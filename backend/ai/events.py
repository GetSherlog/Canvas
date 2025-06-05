"""
Simplified Event Models for Agno Migration

This file is dramatically simplified from the original 500+ line complex event system.
We now use simple dict-based streaming with Agno instead of 40+ complex event types.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime, timezone

# Keep only the basic enums that might still be referenced during migration
class AgentType(str, Enum):
    INVESTIGATION_PLANNER = "investigation_planner"
    CHAT = "chat_agent"
    UNKNOWN = "unknown"

class StatusType(str, Enum):
    STARTING = "starting"
    AGENT_ITERATING = "agent_iterating"
    SUCCESS = "success"
    ERROR = "error"
    COMPLETE = "complete"
    FATAL_ERROR = "fatal_error"
    
# Simple base event for backwards compatibility
class BaseEvent(BaseModel):
    """Simple base event for backwards compatibility during migration"""
    session_id: Optional[str] = Field(None, description="Session ID")
    notebook_id: Optional[str] = Field(None, description="Notebook ID")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# Simple status event for backwards compatibility  
class StatusUpdateEvent(BaseEvent):
    """Simple status event for backwards compatibility during migration"""
    status: StatusType = Field(..., description="Status code")
    agent_type: Optional[AgentType] = Field(None, description="Agent type")
    message: Optional[str] = Field(None, description="Status message")
    attempt: Optional[int] = Field(None, description="Attempt number")
    max_attempts: Optional[int] = Field(None, description="Max attempts")
    reason: Optional[str] = Field(None, description="Reason for status")
    step_id: Optional[str] = Field(None, description="Step ID")
    original_plan_step_id: Optional[str] = Field(None, description="Original plan step ID")
