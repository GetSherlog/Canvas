"""
Chat API Endpoints - Simplified for Agno

This module implements the chat API endpoints for interacting with the AI agent.
Completely refactored to use simple Agno streaming instead of complex Pydantic AI events.
"""

import json
import logging
import time
from typing import Dict, List, Tuple, Optional, Any
from uuid import uuid4, UUID
from datetime import datetime, timezone
import sqlite3
import shutil
from pathlib import Path as PyPath

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form, Path, File, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.ai.chat_agent import (
    ChatAgentService,
    ChatMessage,
    to_chat_message,
)
from backend.db.chat_db import ChatDatabase
from backend.db.database import get_db, get_async_db_session, get_db_session
from backend.db.models import UploadedFile
from backend.services.notebook_manager import NotebookManager, get_notebook_manager
from backend.services.connection_manager import ConnectionManager, get_connection_manager
from backend.services.redis_client import get_redis_client
from backend.config import Settings, get_settings
import redis.asyncio as redis
from redis.exceptions import RedisError

# Initialize logger
chat_logger = logging.getLogger("routes.chat")

# Add correlation ID filter to the logger
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

chat_logger.addFilter(CorrelationIdFilter())

# Create router
router = APIRouter()

# Updated Dependency: Get managers, not the service directly
async def get_managers(
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    connection_manager: ConnectionManager = Depends(get_connection_manager)
) -> Tuple[NotebookManager, ConnectionManager]:
    return notebook_manager, connection_manager

# Dependency to get chat database
async def get_chat_db(request: Request) -> ChatDatabase:
    """Get the chat database from the app state"""
    return request.app.state.chat_db

MAX_CELL_HISTORY = 5
MAX_SUMMARY_LENGTH = 150 # Max chars for code/output summaries

def summarize_cell(cell_dict: Dict) -> str:
    """Creates a concise summary string for a notebook cell dictionary, focusing on results."""
    cell_type = cell_dict.get('type', 'unknown').capitalize()
    content = cell_dict.get('content', '')
    result = cell_dict.get('result')
    error = None
    output_summary = None

    if isinstance(result, dict):
        error = result.get('error')
        output = result.get('output', result.get('content')) # Use 'content' as fallback within result

        if error:
            error_str = str(error)
            if len(error_str) > MAX_SUMMARY_LENGTH:
                error_summary = error_str[:MAX_SUMMARY_LENGTH] + "..."
            else:
                error_summary = error_str
            # Clean summary
            cleaned_error = error_summary.replace("\n", " ").strip()
            return f"Failed {cell_type} Query: {cleaned_error}" 
        elif output:
            output_str = str(output)
            if len(output_str) > MAX_SUMMARY_LENGTH:
                output_summary = output_str[:MAX_SUMMARY_LENGTH] + "..."
            else:
                output_summary = output_str
            # Clean summary
            cleaned_output = output_summary.replace("\n", " ").strip()
            return f"Successful {cell_type} Query: {cleaned_output}"

    # Handle Markdown or cells without error/output in result dict
    if cell_type.lower() == 'markdown':
        if content:
            if len(content) > MAX_SUMMARY_LENGTH:
                content_summary = content[:MAX_SUMMARY_LENGTH] + "..."
            else:
                content_summary = content
            cleaned_content = content_summary.replace("\n", " ").strip()
            return cleaned_content
        else:
            return f"Empty Markdown Cell"
    
    # Fallback for other cell types if no error/output was processed
    # or result wasn't a dict
    status = cell_dict.get('status', cell_dict.get('metadata', {}).get('status', 'unknown'))
    return f"{cell_type} Cell (Status: {status}) - No result/error summary available."

class CreateSessionRequest(BaseModel):
    """Request to create a new chat session"""
    notebook_id: str = Field(description="The ID of the notebook to associate with the chat session")


class CreateSessionResponse(BaseModel):
    """Response for creating a new chat session"""
    session_id: str


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    request: Request, # Need access to request.app.state
    request_data: CreateSessionRequest,
    chat_db: ChatDatabase = Depends(get_chat_db),
    redis: redis.Redis = Depends(get_redis_client),
    managers: Tuple[NotebookManager, ConnectionManager] = Depends(get_managers), # Get managers
    settings: Settings = Depends(get_settings)
) -> Dict:
    """
    Finds an existing chat session for the notebook or creates a new one.
    Ensures DB session, Redis cache, and Agent cache are consistent.

    Returns:
        The existing or newly created session ID.
    """
    start_time = time.time()
    notebook_id = request_data.notebook_id
    correlation_id = str(uuid4())
    chat_logger.info(f"Request to get/create session for notebook {notebook_id}", extra={'correlation_id': correlation_id})

    try:
        # 1. Check for existing session in DB
        existing_session = await chat_db.get_session_by_notebook_id(notebook_id)

        if existing_session:
            session_id = existing_session["id"]
            chat_logger.info(f"Found existing session {session_id} for notebook {notebook_id}", extra={'correlation_id': correlation_id})

            # Ensure Redis cache is updated/refreshed
            redis_key = f"chat_session:{session_id}:notebook_id"
            try:
                await redis.set(redis_key, notebook_id, ex=settings.chat_session_ttl)
                chat_logger.info(f"Refreshed Redis cache for existing session {session_id}", extra={'correlation_id': correlation_id})
            except RedisError as e_redis:
                chat_logger.warning(f"Failed to refresh Redis cache for existing session {session_id}: {e_redis}", extra={'correlation_id': correlation_id}, exc_info=True)
                # Continue even if Redis fails, DB is source of truth

            # Ensure Agent is initialized and cached (it might have been evicted)
            chat_agents_cache = request.app.state.chat_agents
            if session_id not in chat_agents_cache:
                chat_logger.warning(f"Agent for existing session {session_id} not found in cache. Re-initializing.", extra={'correlation_id': correlation_id})
                try:
                    notebook_manager, connection_manager = managers
                    agent_instance = ChatAgentService(notebook_id, notebook_manager)
                    # Use the proper context manager for database session
                    async with get_db_session() as init_db:
                        await agent_instance.initialize(init_db)
                    chat_agents_cache[session_id] = agent_instance
                    chat_logger.info(f"Re-initialized and cached agent for existing session {session_id}", extra={'correlation_id': correlation_id})
                except Exception as e_agent_init:
                    chat_logger.error(f"Failed to re-initialize agent for existing session {session_id}: {e_agent_init}", extra={'correlation_id': correlation_id}, exc_info=True)
                    # If agent init fails, we might still return the session ID, but log the error
                    # Or raise 500? Let's raise for now, as the agent is crucial.
                    raise HTTPException(status_code=500, detail=f"Failed to initialize agent for existing session {session_id}")
            else:
                 chat_logger.info(f"Agent for existing session {session_id} already in cache.", extra={'correlation_id': correlation_id})

            process_time = time.time() - start_time
            chat_logger.info(
                f"Returning existing session {session_id}",
                extra={
                    'correlation_id': correlation_id,
                    'session_id': session_id,
                    'notebook_id': notebook_id,
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            return {"session_id": session_id}

        else:
            # 2. Create a new session if none exists
            session_id = str(uuid4())
            chat_logger.info(f"No existing session found for notebook {notebook_id}. Creating new session {session_id}", extra={'correlation_id': correlation_id})

            try:
                # Create session in DB (Handles potential UNIQUE constraint violation)
                await chat_db.create_session(session_id, notebook_id)
                chat_logger.info(f"Created new session {session_id} in DB for notebook {notebook_id}", extra={'correlation_id': correlation_id})
            except sqlite3.IntegrityError:
                 # This might happen in a race condition if another request created the session just now.
                 # Re-query the DB to get the session ID that was created.
                 chat_logger.warning(f"IntegrityError on create for notebook {notebook_id}. Re-querying.", extra={'correlation_id': correlation_id})
                 existing_session_after_race = await chat_db.get_session_by_notebook_id(notebook_id)
                 if existing_session_after_race:
                     session_id = existing_session_after_race["id"]
                     chat_logger.info(f"Found session {session_id} after IntegrityError for notebook {notebook_id}", extra={'correlation_id': correlation_id})
                     # Proceed as if we found the session initially (ensure caches)
                 else:
                     # This case is strange - IntegrityError but session not found? Log and raise.
                     chat_logger.error(f"IntegrityError occurred but session for notebook {notebook_id} still not found.", extra={'correlation_id': correlation_id})
                     raise HTTPException(status_code=500, detail="Failed to create or retrieve chat session due to potential race condition.")
            except Exception as e_db_create:
                chat_logger.error(f"Failed to create session {session_id} in DB: {e_db_create}", extra={'correlation_id': correlation_id}, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to save new chat session: {str(e_db_create)}")

            # Store info in Redis
            redis_key = f"chat_session:{session_id}:notebook_id"
            try:
                await redis.set(redis_key, notebook_id, ex=settings.chat_session_ttl)
                chat_logger.info(f"Stored new session info in Redis for session {session_id}", extra={'correlation_id': correlation_id})
            except RedisError as e_redis_set:
                 chat_logger.warning(f"Failed to set Redis cache for new session {session_id}: {e_redis_set}", extra={'correlation_id': correlation_id}, exc_info=True)
                 # Continue even if Redis fails for creation

            # Create, Initialize, and Cache Agent
            notebook_manager, connection_manager = managers
            chat_agents_cache = request.app.state.chat_agents
            try:
                chat_logger.info(f"Creating and initializing ChatAgentService for new session {session_id}", extra={'correlation_id': correlation_id})
                # Simplified: only pass notebook_id and notebook_manager
                agent_instance = ChatAgentService(notebook_id, notebook_manager)
                # Use the proper context manager for database session
                async with get_db_session() as init_db:
                    await agent_instance.initialize(init_db)
                chat_agents_cache[session_id] = agent_instance
                chat_logger.info(f"Cached ChatAgentService instance for new session {session_id}", extra={'correlation_id': correlation_id})
            except Exception as e_agent_create:
                 chat_logger.error(f"Failed to initialize agent for new session {session_id}: {e_agent_create}", extra={'correlation_id': correlation_id}, exc_info=True)
                 # If agent init fails for a NEW session, it's critical. Raise 500.
                 # Potentially delete the DB session record? Or leave it for retry?
                 # Let's raise for now.
                 raise HTTPException(status_code=500, detail=f"Failed to initialize agent for new session {session_id}")

            process_time = time.time() - start_time
            chat_logger.info(
                f"Created new session {session_id}",
                extra={
                    'correlation_id': correlation_id,
                    'session_id': session_id,
                    'notebook_id': notebook_id,
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            return {"session_id": session_id}

    except Exception as e:
        process_time = time.time() - start_time
        chat_logger.error(
            f"Unhandled error in create_session for notebook {notebook_id}",
            extra={
                'correlation_id': correlation_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to create or retrieve chat session: {str(e)}")


# Duplicate removed: the handler below is superseded by an updated version later in the file.
# @router.get("/sessions/{session_id}/messages")  # Commented to disable duplicate route
async def _get_session_messages_duplicate_removed(
    session_id: str,
    chat_db: ChatDatabase = Depends(get_chat_db)
) -> Response:
    """
    Get all messages for a chat session
    
    Returns:
        Newline-delimited JSON messages
    """
    start_time = time.time()
    
    try:
        # Verify the session exists
        session = await chat_db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
        
        # Get messages from the database
        messages = await chat_db.get_messages(session_id)
        
        process_time = time.time() - start_time
        chat_logger.info(
            f"Retrieved chat session messages",
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'message_count': len(messages),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        # Convert to ChatMessage format and serialize as newline-delimited JSON
        chat_messages = [json.dumps(to_chat_message(msg).model_dump()) for msg in messages]
        return Response(
            content="\n".join(chat_messages),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-cache"
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        process_time = time.time() - start_time
        chat_logger.error(
            f"Error getting chat session messages",
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to get chat messages: {str(e)}")


# --- Agent Dependency --- 
async def get_chat_agent_for_session(
    request: Request, # Required parameter first
    session_id: str = Path(...),
    # Use async DB session for initialization
    db: AsyncSession = Depends(get_async_db_session),
    # Other dependencies with defaults
    managers: Tuple[NotebookManager, ConnectionManager] = Depends(get_managers),
    chat_db: ChatDatabase = Depends(get_chat_db),
    redis: redis.Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_settings)
) -> ChatAgentService:
    """Dependency to retrieve (or initialize) a cached ChatAgentService instance - simplified for Agno."""
    chat_agents_cache = getattr(request.app.state, 'chat_agents', {})
    agent = chat_agents_cache.get(session_id)

    if agent:
        chat_logger.info(f"Retrieved cached agent for session {session_id}")
        return agent

    # --- Cache Miss Handling --- 
    chat_logger.warning(f"Agent cache miss for session {session_id}. Attempting recovery.")
    notebook_id = None
    redis_key = f"chat_session:{session_id}:notebook_id"
    try:
        notebook_id_str = await redis.get(redis_key)
        if not notebook_id_str:
            chat_logger.info(f"Session {session_id} not in Redis cache, checking DB.")
            session_data = await chat_db.get_session(session_id)
            if session_data:
                notebook_id_str = session_data.get('notebook_id') if isinstance(session_data, dict) else getattr(session_data, 'notebook_id', None)
                if notebook_id_str:
                    # Try to repopulate cache (best effort)
                    try: await redis.set(redis_key, notebook_id_str, ex=settings.chat_session_ttl)
                    except RedisError as e_set: chat_logger.warning(f"Failed repopulating Redis cache for {session_id}: {e_set}")
            
        if notebook_id_str:
            notebook_id = notebook_id_str # Keep as string for initialize method
        else:
            chat_logger.error(f"Session {session_id} not found in Redis or DB during agent recovery.")
            raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found or invalid.")
            
    except RedisError as e_get:
        chat_logger.error(f"Redis error during agent recovery for {session_id}: {e_get}", exc_info=True)
        # Decide if we should try DB anyway? For now, fail if Redis errors during recovery check.
        raise HTTPException(status_code=503, detail="Session cache unavailable during agent recovery.")
    except Exception as e_recov:
        chat_logger.error(f"Unexpected error during agent recovery check for {session_id}: {e_recov}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to verify session for agent recovery.")

    # If we found the notebook_id, initialize the agent JIT - simplified for Agno
    chat_logger.info(f"Re-initializing agent for session {session_id} (notebook: {notebook_id}) due to cache miss.")
    try:
        notebook_manager, connection_manager = managers
        # Simplified: only pass notebook_id and notebook_manager
        agent = ChatAgentService(notebook_id, notebook_manager)
        # Use the proper context manager for database session
        async with get_db_session() as init_db:
            await agent.initialize(init_db)
        chat_agents_cache[session_id] = agent # Store the newly initialized agent
        request.app.state.chat_agents = chat_agents_cache # Ensure cache is updated on app state
        return agent
    except Exception as init_err:
        chat_logger.error(f"Failed to re-initialize agent for session {session_id} after cache miss: {init_err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initialize chat agent instance.")
# --- End Agent Dependency --- 


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str, # Keep session_id for context/logging if needed
    prompt: str = Form(...),
    chat_db: ChatDatabase = Depends(get_chat_db),
    # Use AsyncSession dependency for async manager call
    db: AsyncSession = Depends(get_async_db_session), 
    chat_agent: ChatAgentService = Depends(get_chat_agent_for_session)
) -> StreamingResponse:
    """
    Send a message to the chat agent and stream the response.
    Relies on cached ChatAgentService instance provided by dependency.
    """
    start_time = time.time()
    request_id = str(uuid4())
    try:
        history_from_db = await chat_db.get_messages(session_id)
    except Exception as e:
        chat_logger.error(f"Error retrieving history for session {session_id}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve message history.")

    # Fetch and Summarize Cell History
    cell_history_context = None
    try:
        notebook_manager = chat_agent.notebook_manager
        # Await the async manager call
        notebook = await notebook_manager.get_notebook(db=db, notebook_id=UUID(chat_agent.notebook_id)) 
        if notebook and notebook.cell_order:
            recent_cell_ids = notebook.cell_order[-MAX_CELL_HISTORY:]
            recent_cells_dicts = [notebook.cells[cell_id].model_dump() 
                                  for cell_id in recent_cell_ids 
                                  if cell_id in notebook.cells] 
            summaries = [summarize_cell(cell_dict) for cell_dict in recent_cells_dicts]
            if summaries:
                 cell_history_context = "Recent Cell History:\n" + "\n".join(summaries)
            else:
                 cell_history_context = "Found notebook but no recent cells to summarize."
        elif notebook:
             chat_logger.debug(f"Notebook {notebook.id} found, but it has no cells.")
             cell_history_context = None 

        if cell_history_context:
            chat_logger.debug(f"Generated cell history context for session {session_id}:\\n{cell_history_context}")
    except (KeyError, ValueError) as e: # Catch potential UUID conversion error too
        notebook_id_for_log = chat_agent.notebook_id if chat_agent and chat_agent.notebook_id else "<UNKNOWN>"
        chat_logger.warning(f"Notebook {notebook_id_for_log} not found or invalid UUID when fetching cell history: {e}")
        # Don't prepend error messages either
        cell_history_context = None # Set to None on error

    # Only prepend context if it was successfully generated (i.e., not None)
    if cell_history_context:
        prompt_to_use = f"{cell_history_context}\\n\\nUser Prompt:\\n{prompt}"
    else:
        prompt_to_use = prompt # Use the original user prompt

    # --- End Fetch and Summarize Cell History ---

    # Construct the user message object using the potentially unmodified prompt
    user_message = ChatMessage(
        role="user",
        content=prompt_to_use,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    # --- Prepare history FOR THE AGENT (including the new user message) ---
    # Ensure history_from_db contains ModelMessage objects (or compatible dicts)
    # Assuming chat_db.get_messages returns serializable dicts that can be validated
    # This part might need adjustment based on actual chat_db return type
    try:
        # Add the new user_message to the history we pass to the agent
        history_for_agent = history_from_db + [user_message.model_dump()]
        chat_logger.info(f"History prepared for agent. Total messages: {len(history_for_agent)}")
        if history_for_agent:
             chat_logger.info(f"Last message for agent: {history_for_agent[-1]}")

    except Exception as hist_prep_error:
        chat_logger.error(f"Error preparing history for agent: {hist_prep_error}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to prepare chat history.")
    # --- End Prepare History --- 

    # Simple adapter to handle database compatibility during migration
    def adapt_message_for_db(chat_message: ChatMessage) -> Dict[str, Any]:
        """Convert ChatMessage to format expected by database during migration"""
        return {
            "role": chat_message.role,
            "content": chat_message.content,
            "timestamp": chat_message.timestamp,
            "id": chat_message.id,
            "agent": chat_message.agent
        }

    # Save the user message (with context) to the database asynchronously *before* calling agent
    # This ensures it's persisted even if the agent call fails midway
    try:
        # Convert our ChatMessage to a format the database expects
        # TODO: Update ChatDatabase to accept simple message format during complete Pydantic AI migration
        await chat_db.add_message(session_id, adapt_message_for_db(user_message))  # type: ignore
        chat_logger.info(f"User message saved to DB for session {session_id}")
    except Exception as e:
        # Log error but proceed? Or raise? If DB save fails, history might be inconsistent.
        # Let's raise for now to ensure data integrity.
        chat_logger.error(f"Critical error saving user message for session {session_id}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save user message to history.")

    chat_logger.info(
        f"Processing message for session {session_id}",
        extra={
            'correlation_id': request_id,
            'session_id': session_id,
            'prompt': prompt,
            'history_length': len(history_from_db), # Log length before adding current prompt
            'context_added': bool(cell_history_context) # Indicate cell context was added
        }
    )

    async def stream_response():
        nonlocal start_time # Allow modification for response time logging
        message_buffer: List[Tuple[str, ChatMessage]] = [] # Buffer for DB saving

        try:
            # Pass the UPDATED history INCLUDING the current user message
            async for status_type, response_part in chat_agent.handle_message(
                prompt=prompt_to_use, # Pass the prompt string WITH context
                session_id=session_id,
                message_history=history_for_agent # Pass the history WITH the latest user message
            ):
                # --- Handle Clarification Response --- 
                if status_type == "clarification":
                    chat_logger.info(f"Handling clarification response for session {session_id}")
                    # Convert response to ChatMessage for streaming
                    chat_message = to_chat_message(response_part)
                    # Serialize and encode for streaming
                    try:
                        stream_content = json.dumps(chat_message.model_dump()) + "\n"
                        yield stream_content.encode('utf-8')
                        chat_logger.debug(f"Streamed clarification: {stream_content.strip()} for session {session_id}")
                    except TypeError as e:
                        chat_logger.error(f"Serialization error for clarification message: {e} - {chat_message}", exc_info=True)
                        error_msg = json.dumps({"role": "error", "content": f"Serialization error: {e}", "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n"
                        yield error_msg.encode('utf-8')
                    # Save clarification response to DB (it wasn't saved before)
                    try:
                         # TODO: Update ChatDatabase to accept simple message format during complete Pydantic AI migration
                         await chat_db.add_message(session_id, adapt_message_for_db(chat_message))  # type: ignore
                    except Exception as db_err:
                         chat_logger.error(f"Error saving clarification response for session {session_id}", exc_info=True)
                    # End stream after yielding clarification
                    return 
                # --- End Handle Clarification Response --- 

                # Buffer non-clarification messages for potential DB saving later if needed
                # message_buffer.append((status_type, response_part))
                
                # Convert response to ChatMessage for streaming
                chat_message = to_chat_message(response_part)
                
                # Ensure chat_message content is JSON serializable before streaming
                try:
                    # --- ADD DETAILED LOGGING --- 
                    dumped_message = chat_message.model_dump()
                    # Log based on the converted ChatMessage
                    chat_logger.info(f"STREAMING: Type={type(response_part)}, Role={dumped_message.get('role')}, Agent={dumped_message.get('agent')}, Content Preview: {str(dumped_message.get('content'))[:100]}")
                    # --- END LOGGING --- 

                    stream_content = json.dumps(dumped_message) + "\n"
                    yield stream_content.encode('utf-8')
                    # chat_logger.debug(...) # Keep debug logging if desired
                except TypeError as e:
                    chat_logger.error(f"Serialization error for response part: {e} - {response_part}", exc_info=True)
                    error_msg = json.dumps({"role": "error", "content": f"Serialization error: {e}", "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n"
                    yield error_msg.encode('utf-8')
            # After streaming finishes, save all buffered model responses to DB
            # We removed buffering for now as clarification is handled separately
            # for _, response_to_save in message_buffer:
            #      try:
            #         await chat_db.add_message(session_id, response_to_save)
            #      except Exception as e:
            #          chat_logger.error(f"Error saving buffered model response for session {session_id}", exc_info=True)
            #          # Log error but continue saving others

            process_time = time.time() - start_time
            chat_logger.info(
                f"Completed chat message stream",
                extra={
                    'correlation_id': request_id,
                    'session_id': session_id,
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )

        except Exception as e:
            process_time = time.time() - start_time
            chat_logger.error(
                f"Error during chat stream",
                extra={
                    'correlation_id': request_id,
                    'session_id': session_id,
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'processing_time_ms': round(process_time * 1000, 2)
                },
                exc_info=True
            )
            # Stream an error message to the client
            error_message_obj = ChatMessage(
                role="error", # Custom role for errors
                content=f"An error occurred: {str(e)}",
                timestamp=datetime.now(timezone.utc).isoformat()
            ).model_dump()
            try:
                error_msg_json = json.dumps(error_message_obj) + "\n" # Renamed
                yield error_msg_json.encode('utf-8') # Encode to bytes
            except Exception as serialization_error:
                 chat_logger.error(f"Failed to serialize error message: {serialization_error}", exc_info=True)


    return StreamingResponse(
        stream_response(), 
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    request: Request, # Need request to access app state
    session_id: str,
    chat_db: ChatDatabase = Depends(get_chat_db),
    redis: redis.Redis = Depends(get_redis_client) # Inject Redis client
) -> None:
    """
    Delete a chat session from DB, Redis, and the agent cache.
    """
    start_time = time.time()
    
    try:
        # 1. Delete from Agent Cache (best effort)
        chat_agents_cache = getattr(request.app.state, 'chat_agents', {})
        if session_id in chat_agents_cache:
            del chat_agents_cache[session_id]
            chat_logger.info(f"Removed agent instance for session {session_id} from cache.")
        else:
            chat_logger.info(f"Agent instance for session {session_id} not found in cache during deletion.")
        # Ensure the cache on app.state is updated if it was copied
        request.app.state.chat_agents = chat_agents_cache 

        # 2. Delete from Redis (best effort, ignore if key doesn't exist)
        redis_key = f"chat_session:{session_id}:notebook_id"
        try:
            deleted_count = await redis.delete(redis_key)
            if deleted_count > 0:
                 chat_logger.info(f"Deleted session info from Redis for session {session_id}")
            else:
                 chat_logger.info(f"Session info for {session_id} not found in Redis (already expired or deleted).")
        except RedisError as e:
             chat_logger.error(f"Redis error deleting key {redis_key} for session {session_id}: {e}", exc_info=True)
             # Decide if this should halt the process or just be logged

        # 3. Verify the session exists in DB before cleaning messages
        session = await chat_db.get_session(session_id)
        if not session:
            # If not in DB, and wasn't in Redis (or Redis failed), it's effectively gone.
            # Still return 204 as the goal is deletion.
            chat_logger.warning(f"Chat session {session_id} not found in DB during delete operation.")
            # Optionally raise 404 if strict existence is required:
            # raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
            return # Exit early if not found in DB

        # 4. Clear messages from DB
        await chat_db.clear_session_messages(session_id)
        
        # 5. Delete session record from DB (if applicable)
        # ... (DB delete_session logic remains the same) ...

        process_time = time.time() - start_time
        chat_logger.info(
            f"Deleted chat session state from Cache, Redis and DB", # Updated log
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
    except RedisError as e: # Use the imported RedisError
        chat_logger.error(f"Redis error deleting key {redis_key} for session {session_id}: {e}", exc_info=True)
        # Decide if this should halt the process or just be logged
        # Raising an error might be appropriate if Redis state is critical
        raise HTTPException(status_code=500, detail="Failed to clean up session state.")

    except Exception as e:
        process_time = time.time() - start_time
        chat_logger.error(
            f"Error deleting chat session {session_id}", # Updated log
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete chat session: {str(e)}")


# Removed commented-out unified_chat endpoint for now

# Removed commented-out unified_chat endpoint for now 

# --- Pydantic Models for File Upload ---
class FileUploadResponse(BaseModel):
    id: UUID
    session_id: str
    notebook_id: Optional[UUID] = None
    filename: str
    filepath: str # This will be the relative path as stored in DB
    file_type: Optional[str] = None
    size: Optional[int] = None
    created_at: datetime
    message: str = "File uploaded successfully"

@router.post("/sessions/{session_id}/files", response_model=FileUploadResponse)
async def upload_file_to_session(
    session_id: str = Path(...),
    file: UploadFile = File(...),
    notebook_id_str: Optional[str] = Form(None), # Receive as string, convert to UUID later
    chat_db: ChatDatabase = Depends(get_chat_db), # For session validation
    db: AsyncSession = Depends(get_async_db_session),
    settings: Settings = Depends(get_settings)
):
    """
    Upload a file and associate it with a chat session.
    Optionally, link it to a notebook_id.
    """
    correlation_id = str(uuid4())
    chat_logger.info(
        f"File upload request for session {session_id}, filename: {file.filename}",
        extra={'correlation_id': correlation_id}
    )

    # 1. Validate session
    session_data = await chat_db.get_session(session_id)
    if not session_data:
        chat_logger.warning(f"Session {session_id} not found for file upload.", extra={'correlation_id': correlation_id})
        raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")

    notebook_uuid: Optional[UUID] = None
    if notebook_id_str:
        try:
            notebook_uuid = UUID(notebook_id_str)
        except ValueError:
            chat_logger.warning(f"Invalid notebook_id format: {notebook_id_str}", extra={'correlation_id': correlation_id})
            raise HTTPException(status_code=400, detail="Invalid notebook_id format.")

    # 2. Define storage path and create directory
    # Using /app/uploads as discussed
    base_upload_dir = PyPath("/app/uploads")
    session_upload_dir = base_upload_dir / session_id
    try:
        session_upload_dir.mkdir(parents=True, exist_ok=True)
        chat_logger.info(f"Ensured upload directory exists: {session_upload_dir}", extra={'correlation_id': correlation_id})
    except Exception as e:
        chat_logger.error(f"Could not create upload directory {session_upload_dir}: {e}", exc_info=True, extra={'correlation_id': correlation_id})
        raise HTTPException(status_code=500, detail="Could not create upload directory.")

    file_location = session_upload_dir / (file.filename or f"upload_{uuid4()}") # Handle case where filename might be None

    # 3. Save the file
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
        file_size = file_location.stat().st_size
        chat_logger.info(f"File {file.filename} saved to {file_location}, size: {file_size} bytes", extra={'correlation_id': correlation_id})
    except Exception as e:
        chat_logger.error(f"Could not save uploaded file {file.filename} to {file_location}: {e}", exc_info=True, extra={'correlation_id': correlation_id})
        raise HTTPException(status_code=500, detail=f"Could not save file: {file.filename}")
    finally:
        await file.close() # Ensure the UploadFile is closed

    # 4. Create database record
    try:
        db_uploaded_file = UploadedFile(
            session_id=session_id,
            notebook_id=notebook_uuid,
            filename=file.filename or "",
            filepath=str(file_location.relative_to(base_upload_dir)), # Store relative path
            file_type=file.content_type,
            size=file_size,
            # created_at and updated_at have defaults
        )
        db.add(db_uploaded_file)
        await db.commit()
        await db.refresh(db_uploaded_file)
        chat_logger.info(f"Saved file metadata to DB for {file.filename}, ID: {db_uploaded_file.id}", extra={'correlation_id': correlation_id})
        
        # Use getattr to avoid static-analysis confusion with SQLAlchemy attributes
        _id = getattr(db_uploaded_file, "id")
        _sess = getattr(db_uploaded_file, "session_id")
        _nb_id_raw = getattr(db_uploaded_file, "notebook_id")
        _fname = getattr(db_uploaded_file, "filename")
        _fpath = getattr(db_uploaded_file, "filepath")
        _ftype = getattr(db_uploaded_file, "file_type")
        _fsize = getattr(db_uploaded_file, "size")
        _created = getattr(db_uploaded_file, "created_at")

        return FileUploadResponse(
            id=UUID(str(_id)),
            session_id=str(_sess),
            notebook_id=UUID(str(_nb_id_raw)) if _nb_id_raw else None,
            filename=str(_fname),
            filepath=str(_fpath),
            file_type=str(_ftype) if _ftype else None,
            size=int(_fsize) if _fsize is not None else None,
            created_at=_created,
        )
    except Exception as e:
        chat_logger.error(f"Database error saving file metadata for {file.filename}: {e}", exc_info=True, extra={'correlation_id': correlation_id})
        # Attempt to delete the orphaned file if DB save fails
        try:
            file_location.unlink(missing_ok=True)
        except Exception as del_err:
            chat_logger.error(f"Failed to delete orphaned file {file_location} after DB error: {del_err}", extra={'correlation_id': correlation_id})
        raise HTTPException(status_code=500, detail="Could not save file metadata to database.")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    chat_db: ChatDatabase = Depends(get_chat_db)
) -> Response:
    """
    Get all messages for a chat session
    
    Returns:
        Newline-delimited JSON messages
    """
    start_time = time.time()
    
    try:
        # Verify the session exists
        session = await chat_db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
        
        # Get messages from the database
        messages = await chat_db.get_messages(session_id)
        
        process_time = time.time() - start_time
        chat_logger.info(
            f"Retrieved chat session messages",
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'message_count': len(messages),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        # Convert to ChatMessage format and serialize as newline-delimited JSON
        chat_messages = [json.dumps(to_chat_message(msg).model_dump()) for msg in messages]
        return Response(
            content="\n".join(chat_messages),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-cache"
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        process_time = time.time() - start_time
        chat_logger.error(
            f"Error getting chat session messages",
            extra={
                'correlation_id': str(uuid4()),
                'session_id': session_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to get chat messages: {str(e)}") 