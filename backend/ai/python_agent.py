"""
Python Agent Service

Agent for handling Python code execution via a locally running MCP server.
"""

import logging
from typing import  Optional, AsyncGenerator, Dict, Any, Union, List
from datetime import datetime, timezone
import json
import os
import re
import uuid

from pydantic_ai import Agent, UnexpectedModelBehavior, CallToolsNode
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from backend.ai.models import SafeOpenAIModel, FileDataRef, PythonAgentInput
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStdio
from mcp import StdioServerParameters
from backend.services.notebook_manager import NotebookManager
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.ai.events import (
    EventType,
    AgentType,
    StatusType,
    StatusUpdateEvent,
    ToolCallRequestedEvent,
    ToolSuccessEvent,
    ToolErrorEvent,
    FinalStatusEvent,
    FatalErrorEvent,
)
python_agent_logger = logging.getLogger("ai.python_agent")

IMPORTED_DATA_BASE_PATH = "data/imported_datasets"


class PythonAgent:
    """Agent for interacting with Python MCP server using stdio."""
    def __init__(self, notebook_id: str, notebook_manager: Optional[NotebookManager] = None):
        python_agent_logger.info(f"Initializing PythonAgent (notebook_id will be from input)")
        self.settings = get_settings()
        self.model = SafeOpenAIModel(
                "openai/gpt-4.1",
                provider=OpenAIProvider(
                    base_url='https://openrouter.ai/api/v1',
                    api_key=self.settings.openrouter_api_key,
                ),
        )
        self.agent = None
        self.notebook_manager: Optional[NotebookManager] = notebook_manager

    async def _prepare_local_file(
        self, 
        data_ref: FileDataRef, 
        notebook_id: str, 
        session_id: str
    ) -> str:
        """
        Ensures the CSV data is available as a local file and returns its path.
        Currently assumes data_ref.type is 'content_string'.
        If data_ref.type is 'fsmcp_path', it's the responsibility of the
        StepProcessor to resolve it to content before calling PythonAgent, or
        if type is 'local_staged_path', the value is the already prepared path.
        """
        python_agent_logger.warning("_prepare_local_file called, but its primary invocation path from run_query for data_references has been removed. Ensure this is intended.")
        if data_ref.type == "local_staged_path":
            # Value is the path to the already staged file. Validate and return.
            local_path = data_ref.value
            if not os.path.exists(local_path):
                err_msg = f"Local staged file path provided does not exist: {local_path}"
                python_agent_logger.error(err_msg)
                raise FileNotFoundError(err_msg)
            python_agent_logger.info(f"Using already staged local file: {local_path}")
            return local_path
        elif data_ref.type == "direct_host_path":
            # Value is an absolute path on the host, provided by the Filesystem MCP (npx mode).
            # This path should be directly usable by Python code (e.g., pandas).
            direct_host_path = data_ref.value
            python_agent_logger.info(f"Received FileDataRef type 'direct_host_path'. Path: {direct_host_path} (original: {data_ref.original_filename or 'N/A'}, cell: {data_ref.source_cell_id or 'N/A'})")
            
            if not isinstance(direct_host_path, str):
                err_msg = f"Direct host path value is not a string: {type(direct_host_path)}"
                python_agent_logger.error(err_msg)
                raise ValueError(err_msg)
            if not os.path.isabs(direct_host_path):
                err_msg = f"Direct host path '{direct_host_path}' provided is not absolute."
                python_agent_logger.error(err_msg)
                raise ValueError(err_msg)
            # It's crucial that this path is accessible by the environment executing the Python code.
            # Checking for existence here is a good validation step.
            if not os.path.exists(direct_host_path):
                err_msg = f"Direct host path '{direct_host_path}' does not exist or is not accessible to the Python agent."
                python_agent_logger.error(err_msg)
                raise FileNotFoundError(err_msg)
            
            # Path is valid and directly usable.
            python_agent_logger.info(f"Validated direct host path for use: {direct_host_path}")
            return direct_host_path
        elif data_ref.type == "content_string":
            # Save the provided content to a new permanent file
            python_agent_logger.info(f"Received content_string. Staging data to permanent local file... (original: {data_ref.original_filename or 'N/A'}, cell: {data_ref.source_cell_id or 'N/A'})")
            base_filename = "dataset"
            if data_ref.original_filename:
                sanitized_name = re.sub(r'[^\w\.-]', '_', data_ref.original_filename)
                name_part, ext_part = os.path.splitext(sanitized_name)
                if not ext_part: sanitized_name += ".csv"
                elif ext_part.lower() != ".csv": sanitized_name = name_part + ".csv"
                base_filename = sanitized_name
            unique_id = str(uuid.uuid4().hex[:8])
            filename = f"{os.path.splitext(base_filename)[0]}_{unique_id}.csv"
            dir_path = os.path.join(IMPORTED_DATA_BASE_PATH, notebook_id, session_id)
            try: os.makedirs(dir_path, exist_ok=True)
            except OSError as e: raise
            local_permanent_path = os.path.join(dir_path, filename)
            try:
                with open(local_permanent_path, 'w', encoding='utf-8') as f: f.write(data_ref.value)
                python_agent_logger.info(f"Successfully wrote data to permanent local file: {local_permanent_path}")
                return local_permanent_path
            except IOError as e: raise
        else:
            err_msg = f"PythonAgent._prepare_local_file received unsupported data_ref type '{data_ref.type}'."
            python_agent_logger.error(err_msg)
            raise ValueError(err_msg)

    def _parse_python_mcp_output(self, raw_output: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Parses the output from the Python MCP server (mcp-server-data-exploration)
        into a structured dictionary. Expects JSON or a dict.
        """
        if isinstance(raw_output, dict):
            # If it's already a dict, assume it's in the desired format or close to it.
            # Ensure basic keys are present.
            parsed_result = {
                "status": raw_output.get("status", "success" if raw_output.get("stdout") is not None else "error"),
                "stdout": raw_output.get("stdout"),
                "stderr": raw_output.get("stderr"),
                "return_value": raw_output.get("return_value"), # Or other relevant fields
                "dependencies": raw_output.get("dependencies"), # If provided by new server
                "error_details": raw_output.get("error_details")
            }
            if parsed_result["status"] == "error" and not parsed_result["error_details"] and parsed_result["stderr"]:
                 parsed_result["error_details"] = {
                    "type": "PythonExecutionError",
                    "message": str(parsed_result["stderr"]).splitlines()[-1] if parsed_result["stderr"] else "Unknown Python error",
                    "traceback": str(parsed_result["stderr"])
                }
            python_agent_logger.info(f"MCP output was already a dict: {parsed_result}")
            return parsed_result
        elif isinstance(raw_output, str):
            try:
                # Attempt to parse as JSON if it's a string
                data = json.loads(raw_output)
                if isinstance(data, dict):
                    # Recursively call to handle if the JSON string contained a dict
                    return self._parse_python_mcp_output(data)
                else:
                    # JSON, but not a dict - treat as stdout
                    return {"status": "success", "stdout": raw_output, "stderr": None, "return_value": None, "dependencies": None, "error_details": None}
            except json.JSONDecodeError:
                # Not JSON, check for known error patterns before treating as plain stdout
                python_agent_logger.warning(f"MCP output is a string but not JSON. Raw: {raw_output[:500]}")
                # Regex to capture (-XXXXX, "Error message")
                mcp_error_match = re.match(r"\s*\(\s*(-\d+)\s*,\s*\"(.*)\"\s*\)\s*", raw_output)
                if mcp_error_match:
                    error_code = mcp_error_match.group(1)
                    error_message = mcp_error_match.group(2)
                    python_agent_logger.error(f"Identified MCP-style error in string output: Code {error_code}, Message: {error_message}")
                    return {
                        "status": "error", 
                        "stdout": None, 
                        "stderr": error_message, 
                        "return_value": None, 
                        "dependencies": None, 
                        "error_details": {"type": "MCPExecutionError", "code": error_code, "message": error_message, "traceback": raw_output}
                    }
                else:
                    # No known error pattern, treat as plain string output (likely stdout)
                    python_agent_logger.info(f"MCP output is a non-JSON string without known error patterns. Treating as direct stdout: {raw_output[:200]}")
                    return {"status": "success", "stdout": raw_output, "stderr": None, "return_value": None, "dependencies": None, "error_details": None}
        else:
            python_agent_logger.warning(f"Unexpected MCP output type: {type(raw_output)}. Returning error structure.")
            return {"status": "error", "stderr": f"Invalid output type: {type(raw_output)}", "stdout": None, "return_value": None, "dependencies": None, "error_details": {"type": "ParsingError", "message": "Invalid/unexpected output type from MCP server"}}

    def _get_stdio_server_params(self) -> StdioServerParameters:
        """Returns the StdioServerParameters for the mcp-server-data-exploration."""
        env = os.environ.copy()
        server_params = StdioServerParameters(
            command='/root/.local/bin/uv',
            args=[
                '--directory',
                '/opt/mcp-server-data-exploration', # Path where we cloned it in Dockerfile.backend
                'run',
                'mcp-server-ds' # Changed to 'mcp-server-ds' based on documentation
            ],
            env=env
        )
        python_agent_logger.info(f"Using StdioServerParameters for mcp-server-data-exploration. Command: {server_params.command} Args: {server_params.args}")
        return server_params

    async def _get_stdio_server(self) -> Optional[MCPServerStdio]:
        """Creates the MCPServerStdio instance using hardcoded parameters."""
        try:
            stdio_params = self._get_stdio_server_params()
            return MCPServerStdio(command=stdio_params.command, args=stdio_params.args, env=stdio_params.env)
        except Exception as e:
            python_agent_logger.error(f"Error creating MCPServerStdio instance: {e}", exc_info=True)
            return None

    def _read_system_prompt(self) -> str:
        """Reads the system prompt from the dedicated file."""
        prompt_file_path = os.path.join(os.path.dirname(__file__), "prompts", "python_agent_system_prompt.txt")
        try:
            with open(prompt_file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            python_agent_logger.error(f"System prompt file not found at: {prompt_file_path}")
            return "You are a helpful AI assistant interacting with a Python execution MCP server. Use the 'run_python_code' tool to execute Python code."
        except Exception as e:
            python_agent_logger.error(f"Error reading system prompt file {prompt_file_path}: {e}", exc_info=True)
            return "You are a helpful AI assistant interacting with a Python execution MCP server."

    def _initialize_agent(self, stdio_server: MCPServerStdio, extra_tools: Optional[list] = None) -> Agent:
        """Initializes the Pydantic AI Agent with Python specific configuration.

        The caller can supply *extra_tools* (e.g. `list_cells` / `get_cell`) which
        will be registered with the underlying Agent instance.
        """
        system_prompt = self._read_system_prompt()
        agent = Agent(
            self.model,
            mcp_servers=[stdio_server],
            system_prompt=system_prompt,
            tools=extra_tools or [],  # type: ignore[arg-type]
        )
        python_agent_logger.info("Agent instance created with MCPServerStdio and %d extra tools.", len(extra_tools or []))
        python_agent_logger.info(f"PythonAgent: Pydantic AI Agent initialized with {len(extra_tools or [])} notebook context tools.")
        return agent

    async def run_query(
        self,
        agent_input: PythonAgentInput,
        db: Optional[AsyncSession] = None
    ) -> AsyncGenerator[Any, None]:
        notebook_id = agent_input.notebook_id
        session_id = agent_input.session_id
        user_query = agent_input.user_query
        dependency_cell_ids = agent_input.dependency_cell_ids

        python_agent_logger.info(f"Running Python query for notebook {notebook_id}, session {session_id}. User query: '{user_query}'. Dependencies: {dependency_cell_ids}")
        
        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE, status=StatusType.STARTING, agent_type=AgentType.PYTHON,
            message="Initializing Python Agent...", notebook_id=notebook_id, session_id=session_id,
            attempt=None, max_attempts=None, reason=None, step_id=None, original_plan_step_id=None
        )

        stdio_server = await self._get_stdio_server()
        if not stdio_server:
            error_msg = "Failed to configure Python MCP stdio server."
            python_agent_logger.error(error_msg)
            yield FatalErrorEvent(type=EventType.FATAL_ERROR, status=StatusType.FATAL_ERROR, agent_type=AgentType.PYTHON, error=error_msg, notebook_id=notebook_id, session_id=session_id)
            return

        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE, status=StatusType.CONNECTION_READY, agent_type=AgentType.PYTHON,
            message="Python MCP server connection configured.", notebook_id=notebook_id, session_id=session_id,
            attempt=None, max_attempts=None, reason=None, step_id=None, original_plan_step_id=None
        )

        try:
            from backend.ai.notebook_context_tools import create_notebook_context_tools
            notebook_tools = create_notebook_context_tools(notebook_id, self.notebook_manager)
            self.agent = self._initialize_agent(stdio_server, extra_tools=notebook_tools)
            yield StatusUpdateEvent(
                type=EventType.STATUS_UPDATE, status=StatusType.AGENT_CREATED, agent_type=AgentType.PYTHON, 
                message="Pydantic AI agent instance created.", notebook_id=notebook_id, session_id=session_id,
                attempt=None, max_attempts=None, reason=None, step_id=None, original_plan_step_id=None
            )
        except Exception as init_err:
            error_msg = f"Failed to initialize Pydantic AI Agent: {init_err}"
            python_agent_logger.error(error_msg, exc_info=True)
            yield FatalErrorEvent(type=EventType.FATAL_ERROR, status=StatusType.FATAL_ERROR, agent_type=AgentType.PYTHON, error=error_msg, notebook_id=notebook_id, session_id=session_id)
            return

        current_time_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        prompt_instructions_for_llm = (
            f"Current time is {current_time_utc}.\n"
            f"User Query for this Python cell: {user_query}\n\n"
            f"You have also been provided with a mapping of relevant dependency step IDs to their created cell IDs: {dependency_cell_ids}.\n"
            f"If your task requires data or file paths from a previous step (e.g., from a filesystem operation like search_files, read_file, or get_file_info), "
            f"use the 'get_cell' tool with the appropriate cell ID from the 'dependency_cell_ids' mapping. "
            f"Inspect the 'tool_args' (for input paths/args of the dependency) or 'tool_result' (for output paths/data of the dependency) of the fetched cell content to find the necessary information (e.g., file paths). "
            f"Paths obtained this way are direct host paths and can be used with your Python tools (like 'load_csv').\n\n"
            f"Available Python execution tools (via mcp-server-data-exploration): load_csv, run_script. "
            f"Follow output formatting instructions (DataFrame, Plot, JSON - details will be in the main system prompt).\n"
        )
        current_description = prompt_instructions_for_llm 

        max_attempts = 5
        last_error = None
        attempt_completed = 0
        success_occurred = False
        accumulated_message_history: list[ModelMessage] = []

        yield StatusUpdateEvent(
            type=EventType.STATUS_UPDATE, status=StatusType.STARTING_ATTEMPTS,
            agent_type=AgentType.PYTHON, message=f"Attempting Python query (max {max_attempts} attempts)...",
            max_attempts=max_attempts, notebook_id=notebook_id, session_id=session_id,
            attempt=None, reason=None, step_id=None, original_plan_step_id=None
        )

        try:
            for attempt in range(max_attempts):
                attempt_completed = attempt + 1
                python_agent_logger.info(f"Python Query Attempt {attempt_completed}/{max_attempts}")
                yield StatusUpdateEvent(
                    type=EventType.STATUS_UPDATE, status=StatusType.ATTEMPT_START,
                    agent_type=AgentType.PYTHON, attempt=attempt_completed, max_attempts=max_attempts,
                    notebook_id=notebook_id, session_id=session_id,
                    message=None, reason=None, step_id=None, original_plan_step_id=None
                )
                attempt_failed = False
                last_error_for_attempt = None
                agent_produced_final_result = False

                try:
                    async with self.agent.run_mcp_servers():
                        python_agent_logger.info(f"Attempt {attempt_completed}: MCP Server context entered.")
                        async with self.agent.iter(current_description, message_history=accumulated_message_history) as agent_run:
                            yield StatusUpdateEvent(
                                type=EventType.STATUS_UPDATE, status=StatusType.MCP_CONNECTION_ACTIVE,
                                agent_type=AgentType.PYTHON, attempt=attempt_completed,
                                message="MCP server connection established and agent.iter active.",
                                notebook_id=notebook_id, session_id=session_id,
                                max_attempts=None, reason=None, step_id=None, original_plan_step_id=None
                            )
                            pending_tool_calls: Dict[str, Dict[str, Any]] = {}
                            yield StatusUpdateEvent(
                                type=EventType.STATUS_UPDATE, status=StatusType.AGENT_ITERATING,
                                agent_type=AgentType.PYTHON, attempt=attempt_completed,
                                message="Agent is processing Python request...",
                                notebook_id=notebook_id, session_id=session_id,
                                max_attempts=None, reason=None, step_id=None, original_plan_step_id=None
                            )
                            try:
                                async for node in agent_run: 
                                    if isinstance(node, CallToolsNode):
                                        python_agent_logger.info(f"Attempt {attempt_completed}: Processing CallToolsNode, streaming events...")
                                        try:
                                            async with node.stream(agent_run.ctx) as handle_stream: 
                                                async for event in handle_stream:
                                                    if isinstance(event, FunctionToolCallEvent):
                                                        tool_call_id = event.part.tool_call_id; tool_name = getattr(event.part, 'tool_name', "UnknownTool"); tool_args = getattr(event.part, 'args', {})
                                                        if isinstance(tool_args, str): tool_args = json.loads(tool_args) if tool_name != 'run-script' else {'script': tool_args}
                                                        pending_tool_calls[tool_call_id] = {"tool_name": tool_name, "tool_args": tool_args}
                                                        yield ToolCallRequestedEvent(type=EventType.TOOL_CALL_REQUESTED, status=StatusType.TOOL_CALL_REQUESTED,agent_type=AgentType.PYTHON, attempt=attempt_completed,tool_call_id=tool_call_id, tool_name=tool_name, tool_args=tool_args,notebook_id=notebook_id, session_id=session_id, original_plan_step_id=None)
                                                    elif isinstance(event, FunctionToolResultEvent):
                                                        tool_call_id = event.tool_call_id; raw_tool_result = event.result.content
                                                        if tool_call_id in pending_tool_calls:
                                                            call_info = pending_tool_calls.pop(tool_call_id)
                                                            parsed_tool_result = self._parse_python_mcp_output(str(raw_tool_result) if not isinstance(raw_tool_result, (str, dict)) else raw_tool_result)
                                                            yield ToolSuccessEvent(type=EventType.TOOL_SUCCESS, status=StatusType.TOOL_SUCCESS,agent_type=AgentType.PYTHON, attempt=attempt_completed,tool_call_id=tool_call_id, tool_name=call_info["tool_name"],tool_args=call_info["tool_args"], tool_result=parsed_tool_result,notebook_id=notebook_id, session_id=session_id, original_plan_step_id=None)
                                                            success_occurred = True
                                        except Exception as stream_err_inner: 
                                            python_agent_logger.error(f"Attempt {attempt_completed}: Error during CallToolsNode stream: {stream_err_inner}", exc_info=True)
                                            yield ToolErrorEvent(type=EventType.TOOL_ERROR, status=StatusType.ERROR, agent_type=AgentType.PYTHON,attempt=attempt_completed, error=f"Stream Processing Error: {stream_err_inner}",notebook_id=notebook_id, session_id=session_id, tool_call_id=None, tool_name=None, tool_args=None, message=None, original_plan_step_id=None)
                                            raise stream_err_inner 
                                run_result = agent_run.result 
                                python_agent_logger.info(f"Attempt {attempt_completed}: Agent iteration finished. Raw final result: {run_result}")
                                if not attempt_failed: agent_produced_final_result = True
                            except UnexpectedModelBehavior as e_model_behavior: 
                                python_agent_logger.error(f"Attempt {attempt_completed} caught UnexpectedModelBehavior: {e_model_behavior}", exc_info=True)
                                last_error_for_attempt = f"Agent run failed due to unexpected model behavior: {str(e_model_behavior)}"
                                attempt_failed = True
                                yield ToolErrorEvent(type=EventType.TOOL_ERROR, status=StatusType.MODEL_ERROR,agent_type=AgentType.PYTHON, attempt=attempt_completed,error=last_error_for_attempt,notebook_id=notebook_id, session_id=session_id, tool_call_id=None, tool_name=None, tool_args=None, message=None, original_plan_step_id=None)
                            except Exception as e_general_iter: 
                                error_msg_detail = str(e_general_iter)
                                is_timestamp_error = isinstance(e_general_iter, TypeError) and "'NoneType' object cannot be interpreted as an integer" in error_msg_detail
                                error_msg = "TypeError: OpenAI API response likely missing 'created' timestamp." if is_timestamp_error else f"Agent iteration failed unexpectedly: {error_msg_detail}"
                                error_status = StatusType.TIMESTAMP_ERROR if is_timestamp_error else StatusType.GENERAL_ERROR_RUN
                                python_agent_logger.error(f"Attempt {attempt_completed} caught general error during agent.iter: {error_msg}", exc_info=True)
                                last_error_for_attempt = error_msg
                                attempt_failed = True
                                yield ToolErrorEvent(type=EventType.TOOL_ERROR,status=error_status,agent_type=AgentType.PYTHON,attempt=attempt_completed,error=error_msg,notebook_id=notebook_id, session_id=session_id, tool_call_id=None, tool_name=None, tool_args=None, message=None, original_plan_step_id=None)
                            finally: 
                                if hasattr(agent_run, 'ctx') and hasattr(agent_run.ctx, 'state') and hasattr(agent_run.ctx.state, 'message_history'): 
                                    accumulated_message_history = agent_run.ctx.state.message_history[:]
                except Exception as mcp_context_err:
                    python_agent_logger.error(f"Error with MCP server context or agent.iter context for attempt {attempt_completed}: {mcp_context_err}", exc_info=True)
                    last_error_for_attempt = f"MCP/Agent Context Error: {str(mcp_context_err)}"
                    attempt_failed = True
                    yield FatalErrorEvent(type=EventType.FATAL_ERROR,status=StatusType.FATAL_MCP_ERROR, agent_type=AgentType.PYTHON,error=last_error_for_attempt, session_id=session_id,notebook_id=notebook_id)
                    break 

                if agent_produced_final_result and not attempt_failed:
                    python_agent_logger.info(f"Agent completed successfully on attempt {attempt_completed}. Exiting loop.")
                    break
                elif attempt_failed:
                    last_error = last_error_for_attempt
                    if last_error_for_attempt and "TypeError: OpenAI API response likely missing 'created' timestamp." in last_error_for_attempt:
                        break
                    if attempt < max_attempts - 1:
                        error_context = f"\\n\\nINFO: Attempt {attempt_completed} failed with error: {last_error_for_attempt}. Retrying..."
                        current_description += error_context
                        yield StatusUpdateEvent(type=EventType.STATUS_UPDATE, status=StatusType.RETRYING,agent_type=AgentType.PYTHON,attempt=attempt_completed,reason=f"error: {str(last_error_for_attempt)[:100]}...",notebook_id=notebook_id, session_id=session_id, max_attempts=max_attempts, message=None, step_id=None, original_plan_step_id=None)
                        continue
                    else:
                        break 
                elif attempt >= max_attempts - 1:
                    last_error = last_error or "Max attempts reached without successful agent completion."
                    break
                else:
                    last_error = last_error or "Unexpected loop state."
                    break
        except Exception as e:
            last_error = f"Fatal query processing error: {str(e)}"
            python_agent_logger.error(f"Fatal error during Python query processing (outside attempt loop): {e}", exc_info=True)
            yield FatalErrorEvent(type=EventType.FATAL_ERROR,status=StatusType.FATAL_ERROR,agent_type=AgentType.PYTHON,error=last_error,session_id=session_id,notebook_id=notebook_id)
        finally:
            python_agent_logger.info("Exiting PythonAgent.run_query method's main try/except/finally block.")

        if success_occurred and not last_error:
            yield FinalStatusEvent(type=EventType.FINAL_STATUS,status=StatusType.FINISHED_SUCCESS,agent_type=AgentType.PYTHON,attempts=attempt_completed,session_id=session_id,notebook_id=notebook_id, message=None)
        elif last_error:
            final_error_msg = f"Python query finished after {attempt_completed} attempts. Last error: {last_error}"
            python_agent_logger.error(final_error_msg)
            yield FinalStatusEvent(type=EventType.FINAL_STATUS,status=StatusType.FINISHED_ERROR, agent_type=AgentType.PYTHON,attempts=attempt_completed,message=final_error_msg,session_id=session_id,notebook_id=notebook_id)
        else:
            final_error_msg = f"Python query finished after {attempt_completed} attempts without reported success or error."
            python_agent_logger.warning(final_error_msg)
            yield FinalStatusEvent(type=EventType.FINAL_STATUS,status=StatusType.FINISHED_NO_RESULT,agent_type=AgentType.PYTHON,attempts=attempt_completed,message=final_error_msg,session_id=session_id,notebook_id=notebook_id)
