"""
Filesystem Agent Service

Agent for handling filesystem interactions via a locally running MCP server.
"""

import logging
from typing import  Optional, AsyncGenerator, Dict, Any, Union
from datetime import datetime, timezone
import json
import os

from pydantic_ai import Agent, UnexpectedModelBehavior, CallToolsNode
from pydantic_ai.messages import (
    FunctionToolCallEvent, 
    FunctionToolResultEvent,
    ModelMessage, # For message_history
)
# from pydantic_ai.models.openai import OpenAIModel # Replaced with SafeOpenAIModel
from backend.ai.models import SafeOpenAIModel # Added for safer timestamp handling
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStdio
from mcp.shared.exceptions import McpError 
from mcp import StdioServerParameters

from backend.config import get_settings
from backend.ai.events import (
    EventType,
    AgentType, # Will need to add FILESYSTEM here later
    StatusType,
    StatusUpdateEvent,
    ToolCallRequestedEvent,
    ToolSuccessEvent,
    ToolErrorEvent,
    FinalStatusEvent,
    FatalErrorEvent,
)
from backend.services.connection_manager import get_connection_manager
from backend.services.connection_handlers.registry import get_handler
from backend.ai.utils.context_utils import _truncate_output, TOOL_RESULT_MAX_CHARS as DEFAULT_TRUNCATE_LIMIT

# Updated logger name
filesystem_agent_logger = logging.getLogger("ai.filesystem_agent")

# CONSTANTS
TOOL_RESULT_MAX_CHARS = 10000  # maximum characters to keep from a tool result

# Helper to truncate long strings clearly

def _truncate_output(content: Any, limit: int = TOOL_RESULT_MAX_CHARS) -> Any:
    """Truncate the given string if it exceeds *limit* characters, appending an indicator.

    Non-string content is returned unchanged so the caller can forward it as-is.
    """
    if not isinstance(content, str):
        return content  # Non-string results are returned unchanged
    if len(content) <= limit:
        return content
    truncated = content[:limit]
    return truncated + f"\n\n...[output truncated – original length {len(content)} characters]"

class FileSystemAgent:
    """Agent for interacting with Filesystem MCP server using stdio."""
    def __init__(self, notebook_id: str):
        filesystem_agent_logger.info(f"Initializing FileSystemAgent for notebook_id: {notebook_id}")
        self.settings = get_settings()
        # Using the same AI model settings as GitHub agent for now
        self.model = SafeOpenAIModel( # Changed from OpenAIModel to SafeOpenAIModel
                "openai/gpt-4.1",
                provider=OpenAIProvider(
                    base_url='https://openrouter.ai/api/v1',
                    api_key=self.settings.openrouter_api_key,
                ),
        )
        self.notebook_id = notebook_id
        self.agent = None
        filesystem_agent_logger.info(f"FileSystemAgent initialized successfully (Agent instance created later).")

    async def _get_stdio_server(self) -> Optional[MCPServerStdio]:
        """Fetches default Filesystem connection, gets handler, and creates MCPServerStdio instance."""
        try:
            connection_manager = get_connection_manager()
            # Get the default filesystem connection
            default_conn = await connection_manager.get_default_connection("filesystem") # <-- Changed type
            if not default_conn:
                filesystem_agent_logger.error("No default Filesystem connection found.")
                return None
            if not default_conn.config:
                 filesystem_agent_logger.error(f"Default Filesystem connection {default_conn.id} has no config.")
                 return None

            # Get the handler and stdio parameters
            handler = get_handler("filesystem") # <-- Changed type
            if not handler: # Added check
                 filesystem_agent_logger.error("Filesystem connection handler not found.")
                 return None
                 
            stdio_params: StdioServerParameters = handler.get_stdio_params(default_conn.config)

            filesystem_agent_logger.info(f"Retrieved StdioServerParameters. Command: {stdio_params.command} Args: {stdio_params.args}")
            # Create the MCPServerStdio instance needed by the agent
            return MCPServerStdio(command=stdio_params.command, args=stdio_params.args, env=stdio_params.env)

        except ValueError as ve: # Catch errors from get_handler or get_stdio_params
             filesystem_agent_logger.error(f"Configuration error getting Filesystem stdio params: {ve}", exc_info=True)
             return None
        except Exception as e:
            filesystem_agent_logger.error(f"Error creating MCPServerStdio instance: {e}", exc_info=True)
            return None

    def _read_system_prompt(self) -> str:
        """Reads the system prompt from the dedicated file."""
        # Updated prompt file path
        prompt_file_path = os.path.join(os.path.dirname(__file__), "prompts", "filesystem_agent_system_prompt.txt")
        try:
            with open(prompt_file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            filesystem_agent_logger.error(f"System prompt file not found at: {prompt_file_path}")
            return "You are a helpful AI assistant interacting with a Filesystem MCP server."
        except Exception as e:
            filesystem_agent_logger.error(f"Error reading system prompt file {prompt_file_path}: {e}", exc_info=True)
            return "You are a helpful AI assistant interacting with a Filesystem MCP server."

    def _initialize_agent(self, stdio_server: MCPServerStdio) -> Agent:
        """Initializes the Pydantic AI Agent with Filesystem specific configuration."""
        system_prompt = self._read_system_prompt()

        agent = Agent(
            self.model,
            mcp_servers=[stdio_server],
            system_prompt=system_prompt,
        )
        filesystem_agent_logger.info(f"Agent instance created with MCPServerStdio.")
        return agent

    # Removed _run_single_attempt as its logic is now directly in run_query's attempt loop.

    async def run_query(
        self,
        description: str,
        session_id: str,
        notebook_id: str
    ) -> AsyncGenerator[Any, None]:
        """Run a query (natural language request) against the Filesystem MCP server via stdio, yielding status updates and individual tool results/errors."""
        filesystem_agent_logger.info(f"Running Filesystem query. Original description: '{description}'")
        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE,
            status=StatusType.STARTING,
            agent_type=AgentType.FILESYSTEM,
            message="Initializing Filesystem connection...",
            attempt=None,
            max_attempts=None,
            reason=None,
            step_id=None,
            original_plan_step_id=None,
            session_id=session_id,
            notebook_id=notebook_id
        )
        
        stdio_server = await self._get_stdio_server()
        if not stdio_server:
            error_msg = "Failed to configure Filesystem MCP stdio server. Check default connection and configuration."
            filesystem_agent_logger.error(error_msg)
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_ERROR,
                agent_type=AgentType.FILESYSTEM,
                error=error_msg,
                session_id=session_id,
                notebook_id=notebook_id
            )
            return
            
        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE,
            status=StatusType.CONNECTION_READY, 
            agent_type=AgentType.FILESYSTEM,
            message="Filesystem connection established.",
            attempt=None,
            max_attempts=None,
            reason=None,
            step_id=None,
            original_plan_step_id=None,
            session_id=session_id,
            notebook_id=notebook_id
        )
        
        try:
            agent = self._initialize_agent(stdio_server)
            yield StatusUpdateEvent(
                type=EventType.STATUS_UPDATE,
                status=StatusType.AGENT_CREATED, 
                agent_type=AgentType.FILESYSTEM,
                message="Filesystem agent ready.",
                attempt=None,
                max_attempts=None,
                reason=None,
                step_id=None,
                original_plan_step_id=None,
                session_id=session_id,
                notebook_id=notebook_id
            )
        except Exception as init_err:
            error_msg = f"Failed to initialize Filesystem Agent: {init_err}"
            filesystem_agent_logger.error(error_msg, exc_info=True)
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_ERROR,
                agent_type=AgentType.FILESYSTEM,
                error=error_msg,
                session_id=session_id,
                notebook_id=notebook_id
            )
            return
            
        current_time_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        base_description = f"Current time is {current_time_utc}. User query: {description}"
        current_description = base_description
        
        max_attempts = 2 # Same max attempts as GitHub agent
        last_error = None
        attempt_completed = 0
        success_occurred = False
        accumulated_message_history: list[ModelMessage] = [] # Initialize message history

        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE,
            status=StatusType.STARTING_ATTEMPTS, 
            agent_type=AgentType.FILESYSTEM,
            message=f"Attempting Filesystem query (max {max_attempts} attempts)...",
            max_attempts=max_attempts,
            attempt=None,
            reason=None,
            step_id=None,
            original_plan_step_id=None,
            session_id=session_id,
            notebook_id=notebook_id
        )

        try:
            for attempt in range(max_attempts):
                attempt_completed = attempt + 1
                filesystem_agent_logger.info(f"Filesystem Query Attempt {attempt_completed}/{max_attempts}")
                yield StatusUpdateEvent(
                    type=EventType.STATUS_UPDATE, status=StatusType.ATTEMPT_START, 
                    agent_type=AgentType.FILESYSTEM,
                    attempt=attempt_completed, max_attempts=max_attempts, 
                    message=None, reason=None, step_id=None, original_plan_step_id=None,
                    session_id=session_id,
                    notebook_id=notebook_id
                )
                attempt_failed = False
                # Renamed last_error to be attempt-specific for clarity in retry logic
                last_error_for_attempt = None 
                agent_produced_final_result = False # Flag to track if agent finished cleanly in this attempt

                try:
                    async with agent.run_mcp_servers(): # MCP server management should wrap agent.iter
                        filesystem_agent_logger.info(f"Attempt {attempt_completed}: MCP Server context entered.")
                        # Pass accumulated_message_history to agent.iter
                        async with agent.iter(current_description, message_history=accumulated_message_history) as agent_run:
                            filesystem_agent_logger.info(f"Attempt {attempt_completed}: agent.iter called. History length: {len(accumulated_message_history)}")

                            # --- Core agent interaction logic ---
                        pending_tool_calls: Dict[str, Dict[str, Any]] = {}
                        
                        yield StatusUpdateEvent(
                            type=EventType.STATUS_UPDATE,
                            status=StatusType.AGENT_ITERATING, # Moved here from _run_single_attempt
                            agent_type=AgentType.FILESYSTEM,
                            attempt=attempt_completed,
                            message="Agent is processing...",
                            max_attempts=None, # max_attempts is known by run_query
                            reason=None,
                            step_id=None,
                            original_plan_step_id=None,
                            session_id=session_id,
                            notebook_id=notebook_id
                        )

                        try: # This try block is for errors within the agent.iter() and node.stream()
                            async for node in agent_run: # agent_run is from agent.iter with history
                                if isinstance(node, CallToolsNode):
                                    filesystem_agent_logger.info(f"Attempt {attempt_completed}: Processing CallToolsNode, streaming events...")
                                    try:
                                        async with node.stream(agent_run.ctx) as handle_stream:
                                            async for event in handle_stream:
                                                if isinstance(event, FunctionToolCallEvent):
                                                    tool_call_id = event.part.tool_call_id
                                                    tool_name = getattr(event.part, 'tool_name', None)
                                                    tool_args = getattr(event.part, 'args', {})
                                                    if not tool_name:
                                                        filesystem_agent_logger.warning(f"Attempt {attempt_completed}: ToolCallPart missing 'tool_name'. Part: {event.part!r}")
                                                        tool_name = "UnknownTool"
                                                    
                                                    if isinstance(tool_args, str):
                                                        try:
                                                            tool_args = json.loads(tool_args)
                                                        except json.JSONDecodeError as json_err:
                                                            filesystem_agent_logger.error(f"Attempt {attempt_completed}: Failed to parse tool_args JSON string: {tool_args}. Error: {json_err}")
                                                            tool_args = {} 
                                                    elif not isinstance(tool_args, dict):
                                                        filesystem_agent_logger.warning(f"Attempt {attempt_completed}: tool_args is not a dict or valid JSON string: {type(tool_args)}. Defaulting to empty dict.")
                                                        tool_args = {}

                                                    pending_tool_calls[tool_call_id] = {
                                                        "tool_name": tool_name, 
                                                        "tool_args": tool_args
                                                    }
                                                    yield ToolCallRequestedEvent(
                                                        type=EventType.TOOL_CALL_REQUESTED,
                                                        status=StatusType.TOOL_CALL_REQUESTED,
                                                        agent_type=AgentType.FILESYSTEM,
                                                        attempt=attempt_completed,
                                                        tool_call_id=tool_call_id,
                                                        tool_name=tool_name,
                                                        tool_args=tool_args,
                                                        original_plan_step_id=None,
                                                        session_id=session_id,
                                                        notebook_id=notebook_id
                                                    )
                                                
                                                elif isinstance(event, FunctionToolResultEvent):
                                                    tool_call_id = event.tool_call_id
                                                    # original_tool_content = event.result.content # Old way

                                                    if tool_call_id in pending_tool_calls:
                                                        call_info = pending_tool_calls.pop(tool_call_id)
                                                        tool_arguments = call_info["tool_args"] # Arguments used when tool was called
                                                        original_tool_content = event.result.content # Get original content

                                                        # Truncate the result that pydantic-ai will use for the next LLM call
                                                        truncated_content_for_llm = _truncate_output(original_tool_content, limit=DEFAULT_TRUNCATE_LIMIT)
                                                        
                                                        if isinstance(original_tool_content, str) and \
                                                           isinstance(truncated_content_for_llm, str) and \
                                                           len(original_tool_content) > len(truncated_content_for_llm):
                                                            filesystem_agent_logger.info(
                                                                f"Attempt {attempt_completed}: Truncating tool result for '{call_info['tool_name']}' (ID: {tool_call_id}). "
                                                                f"Original length: {len(original_tool_content)}, Truncated length: {len(truncated_content_for_llm)}."
                                                            )
                                                        
                                                        event.result.content = truncated_content_for_llm
                                                        
                                                        app_event_tool_result: Any
                                                        tool_name_from_call = call_info["tool_name"]
                                                        tool_args_from_call = call_info["tool_args"]

                                                        if tool_name_from_call == "read_file":
                                                            path_arg = tool_args_from_call.get("path") if isinstance(tool_args_from_call, dict) else None
                                                            if path_arg:
                                                                app_event_tool_result = {
                                                                    "tool_name": "read_file",
                                                                    "path": path_arg,
                                                                    "content_preview": truncated_content_for_llm, # Pass truncated as preview for our event
                                                                                                                # original_tool_content (full) is NOT included here to keep event small
                                                                }
                                                                filesystem_agent_logger.info(f"Prepared structured result for read_file: {path_arg}")
                                                            else:
                                                                filesystem_agent_logger.warning(f"read_file tool call missing 'path' in args: {tool_args_from_call}. Falling back to sending (potentially truncated) content preview as result.")
                                                                app_event_tool_result = truncated_content_for_llm # Fallback, less ideal
                                                        elif tool_name_from_call == "search_files":
                                                            # search_files usually returns a list of paths or structured data (original_tool_content).
                                                            # This data is typically not large raw file content, so passing it as is in our event is fine.
                                                            app_event_tool_result = original_tool_content
                                                        else:
                                                            # For other tools, pass the original, untruncated result from the MCP tool call
                                                            # into our application's ToolSuccessEvent. The LLM history part (event.result.content)
                                                            # has already been set to the truncated version if the original_tool_content was a string.
                                                            app_event_tool_result = original_tool_content
                                                        
                                                        # Yield a ToolSuccessEvent for our application's event stream.
                                                        # This event should also contain the (potentially) truncated result.
                                                        yield ToolSuccessEvent(
                                                            type=EventType.TOOL_SUCCESS,
                                                            status=StatusType.TOOL_SUCCESS,
                                                            agent_type=AgentType.FILESYSTEM,
                                                            attempt=attempt_completed,
                                                            tool_call_id=tool_call_id,
                                                            tool_name=call_info["tool_name"],
                                                            tool_args=tool_args_from_call, # Use the stored arguments
                                                            tool_result=app_event_tool_result, # Pass the new structured/original content
                                                            original_plan_step_id=None,
                                                            session_id=session_id,
                                                            notebook_id=notebook_id
                                                        )
                                                        success_occurred = True 
                                                        filesystem_agent_logger.info(f"Attempt {attempt_completed}: Yielded success for tool: {call_info['tool_name']} (ID: {tool_call_id}) with (potentially) truncated result sent to LLM.")
                                                    else:
                                                        filesystem_agent_logger.warning(f"Attempt {attempt_completed}: Received result for unknown/processed ID: {tool_call_id}")
                                    
                                    except McpError as mcp_err_stream: # Renamed to avoid conflict
                                        error_str = str(mcp_err_stream)
                                        filesystem_agent_logger.warning(f"MCPError during CallToolsNode stream in attempt {attempt_completed}: {error_str}")
                                        mcp_tool_call_id = getattr(mcp_err_stream, 'tool_call_id', None)
                                        failed_tool_info = pending_tool_calls.get(mcp_tool_call_id, {}) if mcp_tool_call_id else {}
                                        yield ToolErrorEvent(
                                            type=EventType.TOOL_ERROR, status=StatusType.MCP_ERROR,
                                            agent_type=AgentType.FILESYSTEM, attempt=attempt_completed,
                                            tool_call_id=mcp_tool_call_id, tool_name=failed_tool_info.get("tool_name"),
                                            tool_args=failed_tool_info.get("tool_args"), error=f"MCP Tool Error: {error_str}",
                                            message=None, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id
                                        )
                                        raise mcp_err_stream # Re-raise to be caught by outer try-except in this attempt

                                    except Exception as stream_err_inner: # Renamed
                                        filesystem_agent_logger.error(f"Attempt {attempt_completed}: Error during CallToolsNode stream: {stream_err_inner}", exc_info=True)
                                        yield ToolErrorEvent(
                                            type=EventType.TOOL_ERROR, status=StatusType.ERROR,
                                            agent_type=AgentType.FILESYSTEM, attempt=attempt_completed,
                                            tool_call_id=None, tool_name=None, tool_args=None,
                                            error=f"Stream Processing Error: {stream_err_inner}", message=None,
                                            original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id
                                        )
                                        raise stream_err_inner # Re-raise
                            
                            # This part is reached if agent.iter completes without internal exceptions from node processing
                            run_result = agent_run.result 
                            filesystem_agent_logger.info(f"Attempt {attempt_completed}: Agent iteration finished. Raw final result: {run_result}")
                            if not attempt_failed: # If no tool errors occurred during streaming
                                agent_produced_final_result = True

                        # --- Handle exceptions from the agent.iter() or node.stream() logic ---
                        except McpError as mcp_err: # This catches McpError re-raised from inner block
                            error_str = str(mcp_err)
                            filesystem_agent_logger.warning(f"Attempt {attempt_completed} caught MCPError: {error_str}")
                            last_error_for_attempt = f"MCP Tool Error: {error_str}"
                            attempt_failed = True
                            # Note: The ToolErrorEvent for McpError is yielded within the stream processing block
                        except UnexpectedModelBehavior as e:
                            filesystem_agent_logger.error(f"Attempt {attempt_completed} caught UnexpectedModelBehavior: {e}", exc_info=True)
                            last_error_for_attempt = f"Agent run failed due to unexpected model behavior: {str(e)}"
                            attempt_failed = True
                            yield ToolErrorEvent( 
                                type=EventType.TOOL_ERROR, status=StatusType.MODEL_ERROR,
                                agent_type=AgentType.FILESYSTEM, attempt=attempt_completed,
                                error=last_error_for_attempt, 
                                tool_call_id=None, tool_name=None, tool_args=None, message=None,
                                original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id
                            )
                        except Exception as e:
                            # General error handling (including the timestamp error case)
                            is_timestamp_error = isinstance(e, TypeError) and "'NoneType' object cannot be interpreted as an integer" in str(e)
                            error_msg = "TypeError: OpenAI API response likely missing 'created' timestamp." if is_timestamp_error else f"Agent iteration failed unexpectedly: {str(e)}"
                            error_status = StatusType.TIMESTAMP_ERROR if is_timestamp_error else StatusType.GENERAL_ERROR_RUN
                            filesystem_agent_logger.error(f"Attempt {attempt_completed} caught general error: {error_msg}", exc_info=True)
                            
                            last_error_for_attempt = error_msg # Use specific message
                            attempt_failed = True

                            yield ToolErrorEvent( 
                                type=EventType.TOOL_ERROR,
                                status=error_status, # Use specific status
                                agent_type=AgentType.FILESYSTEM,
                                attempt=attempt_completed,
                                error=error_msg, # Use specific message
                                tool_call_id=None, tool_name=None, tool_args=None, message=None,
                                original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id
                            )
                        finally:
                            # Capture history after the agent_run block finishes or if an error occurs within it.
                            raw_history = agent_run.ctx.state.message_history[:]
                            # Truncate any very large message contents (especially read_file outputs)
                            for _msg in raw_history:
                                _cnt = getattr(_msg, "content", None)
                                if isinstance(_cnt, str):  # Only truncate textual content
                                    setattr(_msg, "content", _truncate_output(_cnt, limit=DEFAULT_TRUNCATE_LIMIT))
                            accumulated_message_history = raw_history
                            filesystem_agent_logger.info(
                                f"Attempt {attempt_completed} (finally): Captured message history of length {len(accumulated_message_history)} (after truncation)."
                            )
                            
                            yield StatusUpdateEvent( # Consistent with other agents
                                type=EventType.STATUS_UPDATE,
                                status=StatusType.AGENT_RUN_COMPLETE, 
                                agent_type=AgentType.FILESYSTEM, 
                                attempt=attempt_completed,
                                message=None, max_attempts=None, reason=None, step_id=None,
                                original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id
                            )
                            filesystem_agent_logger.info(f"Attempt {attempt_completed}: Exiting core agent interaction block.")
                        # --- End core agent interaction wrap ---

                # --- Handle fatal errors managing MCP connection itself ---
                except Exception as mcp_mgmt_err:
                    filesystem_agent_logger.error(f"Fatal error managing MCP server for attempt {attempt_completed}: {mcp_mgmt_err}", exc_info=True)
                    last_error = f"Fatal MCP management error: {str(mcp_mgmt_err)}" # Update overall last_error
                    yield FatalErrorEvent(
                        type=EventType.FATAL_ERROR,
                        status=StatusType.FATAL_MCP_ERROR,
                        agent_type=AgentType.FILESYSTEM,
                        error=last_error,
                        session_id=session_id,
                        notebook_id=notebook_id
                    )
                    break # Exit attempt loop due to fatal MCP issue

                # --- Decide whether to break or retry based on the attempt's outcome ---
                if agent_produced_final_result and not attempt_failed:
                    filesystem_agent_logger.info(f"Agent completed successfully on attempt {attempt_completed}. Exiting loop.")
                    break # Agent finished its flow cleanly.

                elif attempt_failed:
                     last_error = last_error_for_attempt # Update overall last error for final reporting
                     
                     # Check if the error is the specific timestamp error OR context length error
                     is_context_length_error = "maximum context" in str(last_error_for_attempt).lower()
                     is_timestamp_error_msg = last_error_for_attempt == "TypeError: OpenAI API response likely missing 'created' timestamp."

                     if is_timestamp_error_msg:
                         filesystem_agent_logger.error(f"Persistent timestamp error encountered on attempt {attempt_completed}. Not retrying further for this error. Error: {last_error_for_attempt}")
                         break # Break the loop immediately for this specific persistent error
                     
                     if is_context_length_error:
                         filesystem_agent_logger.error(f"Context length error encountered on attempt {attempt_completed}. Not retrying further for this error. Error: {last_error_for_attempt}")
                         break # Also break immediately for context length errors as retrying likely won't help

                     if attempt < max_attempts - 1:
                         # Retry only if an error occurred and we have attempts left (and it's not timestamp/context)
                         # Make error context added to prompt more concise
                         error_context_for_prompt = f"\n\nINFO: Attempt {attempt_completed} failed. Retrying..." # Avoid putting full error back in prompt
                         current_description += error_context_for_prompt
                         yield StatusUpdateEvent(
                             type=EventType.STATUS_UPDATE, status=StatusType.RETRYING, 
                             agent_type=AgentType.FILESYSTEM,
                             attempt=attempt_completed, 
                             reason=f"error: {str(last_error_for_attempt)[:100]}...", # Provide brief reason
                             message=None, max_attempts=max_attempts, step_id=None, original_plan_step_id=None,
                             session_id=session_id,
                             notebook_id=notebook_id
                         )
                         continue # Move to next attempt
                     else:
                         filesystem_agent_logger.error(f"Error on final attempt {max_attempts}: {last_error_for_attempt}")
                         break # Exit loop: final attempt failed

                # This case handles reaching max attempts without clean completion or error on the last try.
                # It might indicate the agent is stuck or the task is unachievable within limits.
                elif attempt >= max_attempts - 1:
                    filesystem_agent_logger.warning(f"Reached max attempts ({max_attempts}) without the agent explicitly completing successfully in the final attempt.")
                    last_error = last_error or "Max attempts reached without successful agent completion."
                    break # Exit loop after max attempts
                
                # Added safeguard: If none of the above conditions match (shouldn't happen), log and break.
                else:
                     filesystem_agent_logger.error(f"Attempt {attempt_completed}: Reached unexpected state in loop control. Breaking.")
                     last_error = last_error or "Unexpected loop state."
                     break


        except Exception as e:
            filesystem_agent_logger.error(f"Fatal error during Filesystem query processing (outside attempt loop): {e}", exc_info=True)
            last_error = f"Fatal query processing error: {str(e)}" # Update overall last error
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_ERROR,
                agent_type=AgentType.FILESYSTEM,
                error=last_error,
                session_id=session_id,
                notebook_id=notebook_id
            )
            # No break needed, exception exits the block
        finally:
            filesystem_agent_logger.info("Exiting FileSystemAgent.run_query method's main try/except/finally block.")

        # --- Final status reporting based on overall success or last error ---
        if success_occurred and not last_error: # Adjusted condition slightly for clarity
             filesystem_agent_logger.info(f"Filesystem query finished after {attempt_completed} attempts with tool success and no final error.")
             yield FinalStatusEvent(
                 type=EventType.FINAL_STATUS,
                 status=StatusType.FINISHED_SUCCESS,
                 agent_type=AgentType.FILESYSTEM,
                 attempts=attempt_completed,
                 message=None, # Can add final agent result here if needed later
                 session_id=session_id,
                 notebook_id=notebook_id
             )
        elif last_error:
            # Determine the most appropriate final status based on the last error
            final_status = StatusType.FINISHED_ERROR 
            if "Fatal" in last_error: # Check if it was a fatal error
                # Status might already be FATAL_ERROR/FATAL_MCP_ERROR from yield, 
                # but we ensure the final message reflects it.
                 final_status = StatusType.FINISHED_ERROR 
            
            final_error_msg = f"Filesystem query finished after {attempt_completed} attempts. Last error: {last_error}"
            filesystem_agent_logger.error(final_error_msg)
            
            # Yield a final error status event
            yield FinalStatusEvent( # Using FinalStatusEvent for terminal errors too
                type=EventType.FINAL_STATUS,
                status=final_status, 
                agent_type=AgentType.FILESYSTEM,
                attempts=attempt_completed,
                message=final_error_msg, # Include error in message
                session_id=session_id,
                notebook_id=notebook_id
            )
            # Optionally, could still yield a ToolErrorEvent if more detail needed, but FinalStatusEvent might suffice
            # yield ToolErrorEvent(type=EventType.TOOL_ERROR, status=final_status, ...) 
        else: # Case: No success occurred, but also no specific error recorded (e.g., max attempts reached quietly)
            final_error_msg = f"Filesystem query finished after {attempt_completed} attempts without reported success or error."
            filesystem_agent_logger.warning(final_error_msg)
            yield FinalStatusEvent( # Use FinalStatusEvent for this ambiguous end state too
                type=EventType.FINAL_STATUS,
                status=StatusType.FINISHED_NO_RESULT, # Or potentially FINISHED_MAX_ATTEMPTS?
                agent_type=AgentType.FILESYSTEM,
                attempts=attempt_completed,
                message=final_error_msg,
                session_id=session_id,
                notebook_id=notebook_id
            )
            # Optionally yield ToolErrorEvent if needed
            # yield ToolErrorEvent(type=EventType.TOOL_ERROR, status=StatusType.FINISHED_NO_RESULT, ...)
