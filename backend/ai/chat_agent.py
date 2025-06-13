"""
Simplified Chat Agent using Agno - completely replaces complex Pydantic AI system
"""
import logging
import time
from typing import Any, Optional
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import UUID

from backend.ai.chat_router import ChatRouter
from backend.services.notebook_manager import NotebookManager
from pydantic import BaseModel

chat_agent_logger = logging.getLogger("ai.chat_agent")

class ChatMessage(BaseModel):
    """Simple chat message model"""
    role: str  # "user" or "model" 
    content: str
    timestamp: str
    id: Optional[str] = None
    agent: Optional[str] = None

def to_chat_message(data: Any) -> ChatMessage:
    """Convert various data formats to ChatMessage"""
    if isinstance(data, ChatMessage):
        return data
    elif isinstance(data, dict):
        # Get content and handle None case properly
        content = data.get("content")
        if content is None:
            content = ""
        else:
            content = str(content)
        
        return ChatMessage(
            role=data.get("role", "model"),
            content=content,
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            id=data.get("id"),
            agent=data.get("agent", "investigation")
        )
    else:
        # Handle other response types by converting to dict-like format
        content = "" if data is None else str(data)
        return ChatMessage(
            role="model",
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent="investigation"
        )

class ChatAgentService:
    """
    Completely simplified chat agent using ONLY Agno
    Now uses ChatRouter for intelligent query routing
    """
    
    def __init__(self, notebook_id: str, notebook_manager: NotebookManager):
        self.notebook_id = notebook_id
        self.notebook_manager = notebook_manager
        self.chat_router = ChatRouter(notebook_id, notebook_manager)
        
        chat_agent_logger.info(f"ChatAgentService initialized with ChatRouter for notebook {notebook_id}")
    
    async def initialize(self, db_session):
        """Initialize the service with database session"""
        try:
            notebook_uuid = UUID(self.notebook_id)
            _ = await self.notebook_manager.get_notebook(
                db=db_session, notebook_id=notebook_uuid
            )
                
            chat_agent_logger.info(f"ChatAgentService initialized successfully for notebook {self.notebook_id}")
            
        except Exception as e:
            chat_agent_logger.error(f"Failed to initialize ChatAgentService: {e}", exc_info=True)
            raise

    async def handle_message(
        self,
        prompt: str,
        session_id: str,
        message_history: Optional[list[Any]] = None,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Process a user message using ChatRouter for intelligent routing.
        
        Simple queries are handled by a lightweight agent, complex queries
        are routed to the InvestigationSystem.
        """
        chat_agent_logger.info(f"Handling message in session {session_id}: '{prompt}'")
        start_time = time.time()
        
        try:
            # Use ChatRouter to handle the message
            async for event_type, event_data in self.chat_router.handle_message(
                prompt=prompt,
                session_id=session_id,
                message_history=message_history
            ):
                # Pass through all events from the router
                yield event_type, event_data
            
            # Log success metrics
            response_time = time.time() - start_time
            chat_agent_logger.info(
                f"Message handled successfully in session {session_id}",
                extra={'session_id': session_id, 'response_time_ms': int(response_time * 1000)}
            )
            
        except Exception as e:
            response_time = time.time() - start_time
            chat_agent_logger.error(
                f"Error handling message in session {session_id}: {e}",
                extra={'session_id': session_id, 'error': str(e), 'response_time_ms': int(response_time * 1000)},
                exc_info=True
            )
            
            # Send error response
            yield "error", {
                "role": "error",
                "content": f"Failed to process message: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            raise
    
    def _get_notebook_context(self) -> str:
        """Get simple notebook context - no complex summarization needed"""
        # TODO: Implement simple context extraction if needed
        return ""
    
    def _create_simple_response(self, message: str, status: str) -> tuple[str, Any]:
        """Create a simple response - replaces complex event creation"""
        # Create a simple response object that can be converted to ChatMessage
        response_data = {
            "role": "model",
            "content": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": "investigation",
            "status": status
        }
        
        return status, response_data

# Keep the old class name for backwards compatibility during migration
SimpleChatAgentService = ChatAgentService
