"""
Log AI Agent Service

Provides an asynchronous wrapper around the FastMCP Log-Analysis server so
Sherlog Canvas can execute log-analysis tools (e.g. log clustering, anomaly
finding, etc.) from the investigation workflow.

The implementation purposefully mirrors the public interface of
`PythonAgent.run_query(...)` so that the surrounding Step/Cell plumbing can be
kept identical.  Internally we keep the logic lightweight – we simply forward
LLM-generated tool calls to the MCP server and translate MCP events back to the
Sherlog event model.
"""

from __future__ import annotations

import asyncio
import logging
import os
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from pydantic_ai import Agent, CallToolsNode, UnexpectedModelBehavior
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    FinalResultEvent,
)
from pydantic_graph import GraphRunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStdio
from mcp import StdioServerParameters
from mcp.shared.exceptions import McpError

from backend.ai.events import (
    AgentType,
    StatusType,
    EventType,
    StatusUpdateEvent,
    ToolCallRequestedEvent,
    ToolSuccessEvent,
    ToolErrorEvent,
    FatalErrorEvent,
)
from backend.ai.models import SafeOpenAIModel
from backend.ai.notebook_context_tools import create_notebook_context_tools
from backend.services.notebook_manager import NotebookManager

logger = logging.getLogger("ai.log_ai_agent")


class LogAIAgent:
    """Light-weight wrapper around the *mcp-sherlog-log-analysis* FastMCP server."""

    _SYSTEM_PROMPT_PATH = os.path.join(
        os.path.dirname(__file__), "prompts", "logai_agent_system_prompt.txt"
    )

    def __init__(self, notebook_id: str, notebook_manager: Optional[NotebookManager] = None):
        self.notebook_id = notebook_id
        self.notebook_manager = notebook_manager
        settings = __import__("backend.config", fromlist=["get_settings"]).get_settings()
        self.model: OpenAIModel = SafeOpenAIModel(
            "openai/gpt-4.1",
            provider=OpenAIProvider(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
            ),
        )
        self._agent: Optional[Agent] = None  # lazily initialised per query

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def _get_stdio_server_params(self) -> StdioServerParameters:
        """Return Docker-based command/args for the Log-AI MCP server image."""
        # Use the published container image instead of building via uv/poetry each time
        env_copy = os.environ.copy()
        # TODO: Add any specific environment variables required by the Log-AI MCP if any

        docker_args = [
            "run",
            "--rm",
            "-i",  # keep STDIN open for MCP protocol
            "--volume=/var/run/docker.sock:/var/run/docker.sock",
        ]

        host_fs_root = os.environ.get("SHERLOG_HOST_FS_ROOT")
        if host_fs_root:
            docker_args.append("-v")
            docker_args.append(f"{host_fs_root}:{host_fs_root}:ro")

        docker_args.append("ghcr.io/navneet-mkr/logai-mcp:0.1.3")

        logger.info(f"Constructed docker_args for Log-AI MCP server: {docker_args}")
        return StdioServerParameters(
            command="docker",
            args=docker_args,
            env=env_copy,
        )

    async def _get_stdio_server(self) -> MCPServerStdio:
        params = self._get_stdio_server_params()
        return MCPServerStdio(
            command=params.command, args=params.args, env=params.env
        )

    def _read_system_prompt(self) -> str:
        try:
            with open(self._SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as fp:
                prompt_content = fp.read()
                logger.info(f"Successfully read system prompt from: {self._SYSTEM_PROMPT_PATH}")
                return prompt_content
        except FileNotFoundError:
            logger.warning(
                "Log-AI system-prompt file missing at %s – falling back to minimal prompt.",
                self._SYSTEM_PROMPT_PATH,
            )
            return (
                "You are an assistant specialised in analysing software logs.  "
                "When appropriate, call a tool exposed by the Log-AI MCP server to "
                "perform log parsing, clustering, anomaly detection, etc.  "
                "Strictly respect the provided JSON schema when supplying tool arguments."
            )

    def _init_agent(self, mcp_server: MCPServerStdio, extra_tools: Optional[list] = None) -> Agent:
        system_prompt = self._read_system_prompt()
        return Agent(
            self.model,
            mcp_servers=[mcp_server],
            system_prompt=system_prompt,
            tools=extra_tools or [],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_query(
        self,
        user_query: str,
        session_id: str,
    ) -> AsyncGenerator[Any, None]:
        """Stream Sherlog events while letting the LLM orchestrate Log-AI tools."""
        notebook_id = self.notebook_id
        logger.info(
            "LogAIAgent.run_query invoked (notebook=%s, session=%s, query=%s)",
            notebook_id,
            session_id,
            user_query[:200],
        )

        # --- Event helpers ------------------------------------------------

        def _status(status: StatusType, msg: str) -> StatusUpdateEvent:
            return StatusUpdateEvent(
                type=EventType.STATUS_UPDATE,
                status=status,
                agent_type=AgentType.LOG_AI,
                message=msg,
                attempt=None,
                max_attempts=None,
                reason=None,
                step_id=None,
                original_plan_step_id=None,
                notebook_id=notebook_id,
                session_id=session_id,
            )

        yield _status(StatusType.STARTING, "Initialising Log-AI agent …")

        # Set-up MCP server
        try:
            stdio_server = await self._get_stdio_server()
        except Exception as e:
            err = f"Failed to create Log-AI MCP server parameters: {e}"
            logger.error(err, exc_info=True)
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_ERROR,
                agent_type=AgentType.LOG_AI,
                error=err,
                notebook_id=notebook_id,
                session_id=session_id,
            )
            return

        yield _status(StatusType.CONNECTION_READY, "Log-AI MCP server parameters prepared.")

        # Notebook context tools (list_cells / get_cell) – optional
        try:
            extra_tools = create_notebook_context_tools(
                notebook_id, self.notebook_manager
            )
            logger.info(f"Successfully created {len(extra_tools)} notebook context tools for Log-AI agent.")
        except Exception as tools_err:
            logger.warning(
                "Failed creating notebook context tools for Log-AI agent: %s", tools_err
            )
            extra_tools = []

        self._agent = self._init_agent(stdio_server, extra_tools=extra_tools)
        yield _status(StatusType.AGENT_CREATED, "LLM agent initialised.")

        # Build prompt
        current_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
        prompt = (
            f"Current time: {current_time_utc}.\\n"
            f"Current Notebook ID: {self.notebook_id}.\\n"
            f"User request: {user_query}\\n"  # user_query is expected to be context-rich
        )

        # --- Run LLM agent -------------------------------------------------
        try:
            logger.info("Attempting to start Log-AI MCP servers...")
            async with self._agent.run_mcp_servers():
                logger.info("Log-AI MCP servers started successfully.")
                async with self._agent.iter(prompt) as run_ctx:
                    yield _status(StatusType.AGENT_ITERATING, "Running analysis …")
                    logger.info(f"Log-AI agent iteration started with prompt: {prompt[:200]}...")

                    pending_calls: Dict[str, Dict[str, Any]] = {}
                    agent_iteration_has_error = False

                    try:
                        async for node in run_ctx:
                            if Agent.is_call_tools_node(node):
                                logger.info("LogAIAgent: Processing CallToolsNode, streaming events...")
                                try:
                                    async with node.stream(run_ctx.ctx) as stream:
                                        async for event in stream:
                                            if isinstance(event, FunctionToolCallEvent):
                                                tool_call_id = event.part.tool_call_id
                                                tool_name = getattr(event.part, 'tool_name', None)
                                                tool_args = getattr(event.part, 'args', {})
                                                if not tool_name:
                                                    logger.warning(f"LogAIAgent: ToolCallPart missing 'tool_name'. Part: {event.part!r}")
                                                    tool_name = "UnknownTool"
                                                
                                                if isinstance(tool_args, str):
                                                    try:
                                                        tool_args = json.loads(tool_args)
                                                    except json.JSONDecodeError as json_err:
                                                        logger.error(f"Failed to parse tool_args JSON string: {tool_args}. Error: {json_err}")
                                                        tool_args = {} 
                                                elif not isinstance(tool_args, dict):
                                                    logger.warning(f"tool_args is not a dict or valid JSON string: {type(tool_args)}. Defaulting to empty dict.")
                                                    tool_args = {}

                                                pending_calls[tool_call_id] = {
                                                    "tool_name": tool_name, 
                                                    "tool_args": tool_args
                                                }
                                                logger.info(f"LogAIAgent: Tool call requested: {tool_name} (ID: {tool_call_id}) with args: {tool_args}")
                                                yield ToolCallRequestedEvent(
                                                    type=EventType.TOOL_CALL_REQUESTED,
                                                    status=StatusType.TOOL_CALL_REQUESTED,
                                                    agent_type=AgentType.LOG_AI,
                                                    attempt=None,
                                                    tool_call_id=tool_call_id,
                                                    tool_name=tool_name,
                                                    tool_args=tool_args,
                                                    original_plan_step_id=None,
                                                    notebook_id=notebook_id,
                                                    session_id=session_id,
                                                )
                                            elif isinstance(event, FunctionToolResultEvent):
                                                tool_call_id = event.tool_call_id
                                                raw_res = event.result.content
                                                
                                                popped_tool_metadata = pending_calls.pop(tool_call_id, {})
                                                tool_name_from_meta = popped_tool_metadata.get('tool_name', 'UnknownTool')
                                                tool_args_from_meta = popped_tool_metadata.get('tool_args', {})

                                                logger.info(f"LogAIAgent: Tool call {tool_call_id} ({tool_name_from_meta}) result content (raw_res): {raw_res!r}")
                                                
                                                yield ToolSuccessEvent(
                                                    type=EventType.TOOL_SUCCESS,
                                                    status=StatusType.TOOL_SUCCESS,
                                                    agent_type=AgentType.LOG_AI,
                                                    attempt=None,
                                                    tool_call_id=tool_call_id,
                                                    tool_name=tool_name_from_meta,
                                                    tool_args=tool_args_from_meta,
                                                    tool_result=raw_res,
                                                    original_plan_step_id=None,
                                                    notebook_id=notebook_id,
                                                    session_id=session_id,
                                                )
                                except McpError as mcp_stream_err:
                                    agent_iteration_has_error = True
                                    err_msg = f"MCPError during Log-AI tool stream: {mcp_stream_err}"
                                    logger.error(err_msg, exc_info=True)
                                    
                                    mcp_tool_call_id = getattr(mcp_stream_err, 'tool_call_id', None)
                                    failed_tool_info = pending_calls.get(mcp_tool_call_id, {}) if mcp_tool_call_id else {}

                                    yield ToolErrorEvent(
                                        type=EventType.TOOL_ERROR,
                                        status=StatusType.MCP_ERROR,
                                        agent_type=AgentType.LOG_AI,
                                        attempt=None,
                                        tool_call_id=mcp_tool_call_id,
                                        tool_name=failed_tool_info.get("tool_name"),
                                        tool_args=failed_tool_info.get("tool_args"),
                                        error=err_msg,
                                        message=None, original_plan_step_id=None,
                                        notebook_id=notebook_id, session_id=session_id,
                                    )
                                    raise
                                except Exception as stream_err:
                                    agent_iteration_has_error = True
                                    err_msg = f"Error during Log-AI tool stream processing: {stream_err}"
                                    logger.error(err_msg, exc_info=True)
                                    yield ToolErrorEvent(
                                        type=EventType.TOOL_ERROR,
                                        status=StatusType.ERROR,
                                        agent_type=AgentType.LOG_AI,
                                        attempt=None,
                                        tool_call_id=None, tool_name=None, tool_args=None,
                                        error=err_msg,
                                        message=None, original_plan_step_id=None,
                                        notebook_id=notebook_id, session_id=session_id,
                                    )
                                    raise
                            elif Agent.is_end_node(node):
                                output = node.data.output
                                if output:
                                    logger.info(f"LogAIAgent: Final result: {output}")
                                    yield _status(StatusType.AGENT_RUN_COMPLETE, "Log-AI analysis finished.")
                            elif Agent.is_model_request_node(node):
                                logger.info(f"LogAIAgent: Model request node: {node}")
                                async with node.stream(run_ctx.ctx) as request_stream:
                                    async for event in request_stream:
                                        if isinstance(event, FinalResultEvent):
                                            logger.info(
                                                f'[Result] The model produced a final output (tool_name={event.tool_name})'
                                            )
                        
                    
                    except Exception as iteration_exc:
                        err_msg = f"Error during Log-AI agent iteration: {iteration_exc}"
                        logger.error(err_msg, exc_info=True)
                        raise

                logger.info("Log-AI MCP servers stopping.")
            
            if not agent_iteration_has_error:
                 yield _status(StatusType.AGENT_RUN_COMPLETE, "Log-AI analysis finished.")

        except UnexpectedModelBehavior as umb:
            err_msg = f"Unexpected model behaviour for Log-AI agent: {umb}"
            logger.error(err_msg, exc_info=True)
            yield ToolErrorEvent(
                type=EventType.TOOL_ERROR,
                status=StatusType.MODEL_ERROR,
                agent_type=AgentType.LOG_AI,
                attempt=None,
                tool_call_id=None, tool_name=None, tool_args=None,
                error=err_msg,
                message=None, original_plan_step_id=None,
                notebook_id=notebook_id, session_id=session_id,
            )
        except McpError as mcp_main_err:
            err_msg = f"Fatal Log-AI agent error due to MCP issue: {mcp_main_err}"
            logger.error(err_msg, exc_info=True)
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_MCP_ERROR, 
                agent_type=AgentType.LOG_AI,
                error=err_msg,
                notebook_id=notebook_id, session_id=session_id,
            )
        except Exception as exc:
            err_msg = f"Fatal Log-AI agent error: {exc}"
            logger.error(err_msg, exc_info=True)
            yield FatalErrorEvent(
                type=EventType.FATAL_ERROR,
                status=StatusType.FATAL_ERROR,
                agent_type=AgentType.LOG_AI,
                error=err_msg,
                notebook_id=notebook_id,
                session_id=session_id,
            )
