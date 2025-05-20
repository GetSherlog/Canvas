"""
Step processor for executing and processing individual investigation steps.
"""

import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union, Type, AsyncGenerator
from uuid import UUID

from backend.ai.models import StepType, InvestigationStepModel, PythonAgentInput
from backend.ai.step_result import StepResult
from backend.ai.step_agents import StepAgent, MarkdownStepAgent, GitHubStepAgent, FileSystemStepAgent, PythonStepAgent, ReportStepAgent
from backend.ai.code_index_query_agent import CodeIndexQueryAgent
from backend.ai.cell_creator import CellCreator
from pydantic_ai.models.openai import OpenAIModel
from backend.core.cell import CellType
from backend.core.query_result import QueryResult
from backend.services.notebook_manager import NotebookManager
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.chat_tools import NotebookCellTools
from backend.services.connection_manager import ConnectionManager

from backend.ai.events import (
    AgentType, BaseEvent, StatusUpdateEvent,
    ToolSuccessEvent, ToolErrorEvent,
    GitHubToolCellCreatedEvent, GitHubToolErrorEvent, 
    FileSystemToolCellCreatedEvent, FileSystemToolErrorEvent, 
    PythonToolCellCreatedEvent, PythonToolErrorEvent,
    CodeIndexQueryToolCellCreatedEvent, CodeIndexQueryToolErrorEvent,
    StepCompletedEvent, StepErrorEvent, StepExecutionCompleteEvent,
    SummaryCellCreatedEvent, SummaryCellErrorEvent,
    MediaTimelineCellCreatedEvent,
    LogAIToolCellCreatedEvent, LogAIToolErrorEvent,
)

import json

ai_logger = logging.getLogger("ai")

STEP_CONTEXT_SNIPPET_LIMIT = 40000
REPORT_CONTEXT_SNIPPET_LIMIT = 40000

class StepProcessor:
    """Handles the execution and processing of individual investigation steps"""
    INTERNAL_NOTEBOOK_CONTEXT_TOOLS = ["list_cells", "get_cell"]

    def __init__(
        self,
        notebook_id: str, 
        model: OpenAIModel,
        connection_manager: ConnectionManager,
        notebook_manager: Optional[NotebookManager] = None,
        mcp_servers: Optional[List[Any]] = None
    ):
        self.notebook_id = notebook_id
        self.model = model
        self.connection_manager = connection_manager
        self.notebook_manager = notebook_manager
        self.mcp_servers = mcp_servers or []
        self.cell_creator = CellCreator(notebook_id, connection_manager)
        
        self._step_agents: Dict[StepType, StepAgent] = {}
    
    def _get_agent_for_step_type(self, step_type: StepType) -> StepAgent:
        """Get or create the appropriate agent for a step type"""
        if step_type not in self._step_agents:
            if step_type == StepType.MARKDOWN:
                self._step_agents[step_type] = MarkdownStepAgent(
                    notebook_id=self.notebook_id,
                    model=self.model,
                    notebook_manager=self.notebook_manager,
                    mcp_servers=self.mcp_servers,
                )
            elif step_type == StepType.GITHUB:
                self._step_agents[step_type] = GitHubStepAgent(self.notebook_id)
            elif step_type == StepType.FILESYSTEM:
                self._step_agents[step_type] = FileSystemStepAgent(self.notebook_id)
            elif step_type == StepType.PYTHON:
                self._step_agents[step_type] = PythonStepAgent(self.notebook_id, notebook_manager=self.notebook_manager)
            elif step_type == StepType.INVESTIGATION_REPORT:
                self._step_agents[step_type] = ReportStepAgent(self.notebook_id, mcp_servers=self.mcp_servers)
            elif step_type == StepType.MEDIA_TIMELINE:
                from backend.ai.step_agents import MediaTimelineStepAgent
                self._step_agents[step_type] = MediaTimelineStepAgent(notebook_id=self.notebook_id, connection_manager=self.connection_manager, notebook_manager=self.notebook_manager, mcp_servers=self.mcp_servers)
            elif step_type == StepType.CODE_INDEX_QUERY:
                self._step_agents[step_type] = CodeIndexQueryAgent(
                    notebook_id=self.notebook_id,
                    connection_manager=self.connection_manager,
                    mcp_servers=self.mcp_servers
                )
            elif step_type == StepType.LOG_AI:
                from backend.ai.step_agents import LogAIStepAgent
                self._step_agents[step_type] = LogAIStepAgent(self.notebook_id, notebook_manager=self.notebook_manager)
            else:
                raise ValueError(f"Unsupported step type: {step_type}")
                
        return self._step_agents[step_type]

    async def process_step(
        self,
        step: InvestigationStepModel,
        executed_steps: Dict[str, Any],
        step_results: Dict[str, StepResult], 
        plan_step_id_to_cell_ids: Dict[str, List[UUID]],
        cell_tools: NotebookCellTools,
        session_id: str,
        db: AsyncSession,
        original_query: str = ""
    ) -> AsyncGenerator[Union[BaseEvent, StepExecutionCompleteEvent], None]:
        """Process a single investigation step and yield event updates"""
        step_type_value = step.step_type.value if step.step_type else "Unknown"
        ai_logger.info(f"<<<<< Processing step {step.step_id} ({step_type_value}) for session {session_id} >>>>>")
        ai_logger.info(f"Step details: {step.model_dump_json(indent=2)}")

        if not step.step_type:
            error_msg = f"Step {step.step_id} is missing step_type"
            ai_logger.error(error_msg)
            yield StepErrorEvent(
                step_id=step.step_id,
                error=error_msg,
                agent_type=AgentType.UNKNOWN,
                step_type=None,
                cell_id=None,
                cell_params=None,
                result=None,
                session_id=session_id,
                notebook_id=self.notebook_id
            )
            return
        
        step_result = StepResult(step.step_id, step.step_type)
        
        context = self._build_step_context(
            step,
            executed_steps,
            step_results,
            plan_step_id_to_cell_ids
        )
        ai_logger.info(f"Step {step.step_id} context: {context}")
        
        if original_query:
            context["original_query"] = original_query
            context["prompt"] = f"Original user query: {original_query}\n\n" + context["prompt"]
        
        # Get the appropriate agent for this step type
        try:
            step_agent = self._get_agent_for_step_type(step.step_type)
        except ValueError as e:
            error_msg = f"Could not get agent for step {step.step_id}: {e}"
            ai_logger.error(error_msg)
            yield StepErrorEvent(
                step_id=step.step_id,
                error=error_msg,
                agent_type=AgentType.UNKNOWN,
                step_type=str(step.step_type),
                cell_id=None,
                cell_params=None,
                result=None,
                session_id=session_id,
                notebook_id=self.notebook_id
            )
            return
        
        # Track execution results
        final_result_data = None
        github_step_has_tool_errors = False
        filesystem_step_has_tool_errors = False
        python_step_has_tool_errors = False
        code_index_query_step_has_tool_errors = False # Added for code index query
        
        # Special handling for report steps
        if step.step_type == StepType.INVESTIGATION_REPORT:
            context["findings_text"] = self._format_findings_for_report(step, executed_steps, step_results)
            for exec_step in executed_steps.values():
                if 'original_query' in exec_step:
                    context["original_query"] = exec_step["original_query"]
                    break
            
            report_error = None
            report_result = None
            
            generator = step_agent.execute(step, context.get("prompt", ""), session_id, context, db=db)
            async for event in generator:
                if isinstance(event, BaseEvent):
                    yield event
                elif isinstance(event, dict) and event.get("type") == "final_step_result":
                    report_result = event.get("result")
                    report_error = event.get("error")
                
            if report_result:
                dependency_cell_ids = [cid for dep_id in step.dependencies for cid in plan_step_id_to_cell_ids.get(dep_id, [])]
                created_cell_id, cell_params, cell_error = await self.cell_creator.create_report_cell(
                    cell_tools=cell_tools, step=step, report=report_result,
                    dependency_cell_ids=dependency_cell_ids, session_id=session_id
                )
                if cell_error:
                    yield SummaryCellErrorEvent(
                        error=cell_error, cell_params=cell_params.model_dump() if cell_params else None,
                        session_id=session_id, notebook_id=self.notebook_id
                    )
                    step_result.add_error(cell_error)
                else:
                    yield SummaryCellCreatedEvent(
                        cell_params=cell_params.model_dump() if cell_params else {},
                        cell_id=str(created_cell_id) if created_cell_id else None,
                        error=report_error, session_id=session_id, notebook_id=self.notebook_id
                    )
                if created_cell_id:
                    plan_step_id_to_cell_ids.setdefault(step.step_id, []).append(created_cell_id)
                    step_result.add_cell_id(created_cell_id)
                final_result_data = report_result
                step_result.add_output(report_result)
                if report_error:
                    step_result.add_error(report_error)
            else:
                error_msg = "Report generation failed to produce a report"
                step_result.add_error(error_msg)
            
            step_results[step.step_id] = step_result
            yield StepExecutionCompleteEvent(
                step_id=step.step_id, final_result_data=final_result_data,
                step_outputs=step_result.outputs, step_error=step_result.get_combined_error(),
                github_step_has_tool_errors=False, filesystem_step_has_tool_errors=False,
                python_step_has_tool_errors=False, code_index_query_step_has_tool_errors=code_index_query_step_has_tool_errors, # Use the variable
                session_id=session_id, notebook_id=self.notebook_id
            )
            return
        
        agent_type = step_agent.get_agent_type()
        agent_input_data: Union[str, PythonAgentInput] = context.get("prompt", "")
        if isinstance(agent_input_data, str):
            ai_logger.info(f"Step {step.step_id} agent type: {agent_type}, initial agent_input_data (prompt): {agent_input_data[:500]}...")
        else: # It's PythonAgentInput
            ai_logger.info(f"Step {step.step_id} agent type: {agent_type}, initial agent_input_data type: PythonAgentInput (details logged separately if Python step)")

        if step.step_type == StepType.PYTHON:
            
            dependency_cell_ids_for_agent: Dict[str, List[str]] = {}
            if step.dependencies:
                for dep_id in step.dependencies:
                    if dep_id in plan_step_id_to_cell_ids and plan_step_id_to_cell_ids[dep_id]:
                        dependency_cell_ids_for_agent[dep_id] = [str(uuid_val) for uuid_val in plan_step_id_to_cell_ids[dep_id]]
            
            query_for_python_agent = step.description
            if not query_for_python_agent:
                query_for_python_agent = "# No specific description provided for Python step."
            
            try:
                python_agent_input_obj = PythonAgentInput(
                    user_query=query_for_python_agent,
                    notebook_id=self.notebook_id, 
                    session_id=session_id,
                    dependency_cell_ids=dependency_cell_ids_for_agent 
                )
                agent_input_data = python_agent_input_obj
                ai_logger.info(f"PythonAgentInput created for step {step.step_id} with {len(dependency_cell_ids_for_agent)} dependency_cell_id mappings.")
                ai_logger.debug(f"PythonAgentInput: {python_agent_input_obj.model_dump_json(indent=2)}")
            except Exception as e: # Catch potential Pydantic validation errors if model mismatch
                error_msg = f"Error creating PythonAgentInput for step {step.step_id}: {e}\\n{traceback.format_exc()}"
                ai_logger.error(error_msg, exc_info=True)
                yield StepErrorEvent(
                    step_id=step.step_id, 
                    error=error_msg, 
                    agent_type=AgentType.PYTHON, 
                    step_type=StepType.PYTHON, 
                    session_id=session_id, 
                    notebook_id=self.notebook_id,
                    cell_id=None,      # Explicitly pass None
                    cell_params=None,  # Explicitly pass None
                    result=None        # Explicitly pass None
                )
                step_result.add_error(error_msg)
                step_results[step.step_id] = step_result
                yield StepExecutionCompleteEvent(step_id=step.step_id, final_result_data=None, step_outputs=step_result.outputs, step_error=step_result.get_combined_error(), github_step_has_tool_errors=False, filesystem_step_has_tool_errors=False, python_step_has_tool_errors=True, code_index_query_step_has_tool_errors=code_index_query_step_has_tool_errors, session_id=session_id, notebook_id=self.notebook_id) # Use the variable
                return
        
        # This was the part with agent_input_data for PythonAgent, MediaTimelineAgent also takes similar care
        # The execute method of MediaTimelineAgent expects agent_input_data to be the query string.
        if step.step_type == StepType.MEDIA_TIMELINE:
            # For MediaTimelineAgent, agent_input_data is typically the media query (URL or reference).
            # This usually comes from step.description or a specific parameter.
            # The context["prompt"] is step.description by default in _build_step_context.
            # We also need to ensure cell_tools is passed to the execute method.
            # The StepAgent.execute signature is: step, agent_input_data, session_id, context, db
            # MediaTimelineAgent.execute expects: step, agent_input_data, session_id, context, db
            # And it extracts cell_tools from context.
            # So, we need to ensure cell_tools is IN the context.
            context['cell_tools'] = cell_tools # Ensure cell_tools is in the context
            agent_input_data = context.get("prompt", step.description) # Default to step.description
            ai_logger.info(f"Preparing to call MediaTimelineAgent.execute with input: {str(agent_input_data)[:200]}")

        generator = step_agent.execute(step, agent_input_data, session_id, context, db=db)
        async for event in generator:
            if isinstance(event, StatusUpdateEvent):
                ai_logger.info(f"Step {step.step_id} yielding StatusUpdateEvent: {event.status} - {event.message}")
                if not event.step_id:
                    yield StatusUpdateEvent(
                        status=event.status, agent_type=event.agent_type, message=event.message,
                        attempt=event.attempt, max_attempts=event.max_attempts, reason=event.reason,
                        step_id=step.step_id, original_plan_step_id=event.original_plan_step_id,
                        session_id=session_id, notebook_id=self.notebook_id
                    )
                else:
                    yield event
            elif isinstance(event, dict) and event.get("type") == "final_step_result" and step.step_type not in [StepType.GITHUB, StepType.FILESYSTEM, StepType.PYTHON]:
                final_result_data = event.get("result")
                ai_logger.info(f"Step {step.step_id} received final_step_result (non-tool based): {type(final_result_data)}")
                if step.step_type == StepType.MEDIA_TIMELINE:
                    # Media timeline returns a specialized payload, not QueryResult
                    step_result.add_output(final_result_data)
                else:
                    if not isinstance(final_result_data, QueryResult):
                        ai_logger.error(f"final_step_result did not contain QueryResult for step {step.step_id}")
                        final_result_data = None
                        step_result.add_error("Internal error: Invalid final result format")
                    else:
                        step_result.add_output(final_result_data)
                        if final_result_data.error:
                            step_result.add_error(final_result_data.error)
                break
            elif isinstance(event, ToolSuccessEvent):
                ai_logger.info(f"Step {step.step_id} received ToolSuccessEvent: {event.tool_name}")
                created_event_map = {
                    StepType.GITHUB: GitHubToolCellCreatedEvent,
                    StepType.FILESYSTEM: FileSystemToolCellCreatedEvent,
                    StepType.PYTHON: PythonToolCellCreatedEvent,
                    StepType.CODE_INDEX_QUERY: CodeIndexQueryToolCellCreatedEvent,
                    StepType.LOG_AI: LogAIToolCellCreatedEvent,
                }
                created_event_class = created_event_map.get(step.step_type)
                if created_event_class:
                    # For CodeIndexQuery steps, create a dedicated cell regardless of the exact MCP tool name.
                    if step.step_type == StepType.CODE_INDEX_QUERY and isinstance(event, ToolSuccessEvent):
                        # Accept tool names like "qdrant-find" or "qdrant.qdrant-find" etc.
                        tool_name_for_display = event.tool_name or "qdrant-find"
                        created_cell_id, cell_params_model, cell_creation_error_msg = await self.cell_creator.create_code_index_query_cell(
                            cell_tools=cell_tools, step=step, tool_event=event,
                            dependency_cell_ids=[cid for dep_id in step.dependencies for cid in plan_step_id_to_cell_ids.get(dep_id, [])],
                            session_id=session_id
                        )
                        if cell_creation_error_msg:
                            step_result.add_error(cell_creation_error_msg)
                            # Yield a ToolErrorEvent if cell creation fails for this specific case
                            yield CodeIndexQueryToolErrorEvent(
                                original_plan_step_id=step.step_id,
                                tool_name=tool_name_for_display,
                                tool_args=event.tool_args,
                                error=cell_creation_error_msg,
                                agent_type=agent_type,
                                session_id=session_id,
                                notebook_id=self.notebook_id,
                                tool_call_id=event.tool_call_id
                            )
                            code_index_query_step_has_tool_errors = True
                        elif created_cell_id and cell_params_model:
                            step_result.add_cell_id(created_cell_id)
                            plan_step_id_to_cell_ids.setdefault(step.step_id, []).append(created_cell_id)
                            yield CodeIndexQueryToolCellCreatedEvent(
                                original_plan_step_id=step.step_id,
                                cell_id=str(created_cell_id),
                                tool_name=tool_name_for_display,
                                tool_args=event.tool_args,
                                result=event.tool_result,
                                cell_params=cell_params_model.model_dump(),
                                session_id=session_id,
                                notebook_id=self.notebook_id
                            )
                        step_result.add_output(self.cell_creator._serialize_tool_result(event.tool_result, tool_name_for_display))

                    elif created_event_class != ToolSuccessEvent: # For other specific tool cell created events
                        _, tool_event = await self._process_tool_success_event(
                            event=event, step=step, step_type=step.step_type, agent_type=agent_type,
                            plan_step_id_to_cell_ids=plan_step_id_to_cell_ids, cell_tools=cell_tools,
                            session_id=session_id, created_event_class=created_event_class,
                            step_result=step_result
                        )
                        yield tool_event
                    # If created_event_class is ToolSuccessEvent but not handled above (e.g. internal tools), it's processed by _process_tool_success_event
                    # but the resulting event might not be yielded if it's for an internal tool.
                    # The CodeIndexQueryAgent itself yields a ToolSuccessEvent, which is caught here.
                    # We only want to create a cell and yield CodeIndexQueryToolCellCreatedEvent.
                    # Other ToolSuccessEvents are handled by _process_tool_success_event.

            elif isinstance(event, ToolErrorEvent):
                error_event_map = {
                    StepType.GITHUB: GitHubToolErrorEvent,
                    StepType.FILESYSTEM: FileSystemToolErrorEvent,
                    StepType.PYTHON: PythonToolErrorEvent,
                    StepType.CODE_INDEX_QUERY: CodeIndexQueryToolErrorEvent,
                    StepType.LOG_AI: LogAIToolErrorEvent,
                }
                error_event_class = error_event_map.get(step.step_type)
                if error_event_class:
                    # For generic ToolErrorEvent, we might need to pass more fields if its constructor expects them
                    # For now, assuming it matches the specific error events' signature or handles missing fields.
                    ai_logger.info(f"Step {step.step_id} yielding {error_event_class.__name__} for tool {event.tool_name} error: {event.error}")
                    
                    # Construct the event based on whether it's a generic ToolErrorEvent or a specific one
                    # For generic ToolErrorEvent, we might need to pass more fields if its constructor expects them
                    # For now, assuming it matches the specific error events' signature or handles missing fields.
                    # This block will now primarily handle specific error events.
                    # The CodeIndexQueryAgent yields a ToolErrorEvent directly with all necessary fields.
                    if error_event_class and error_event_class != ToolErrorEvent: # Only yield specific, non-generic error events here
                        yield error_event_class(
                            original_plan_step_id=step.step_id, tool_call_id=event.tool_call_id,
                            tool_name=event.tool_name, tool_args=event.tool_args, error=event.error,
                            session_id=session_id, notebook_id=self.notebook_id
                        )
                    elif error_event_class == ToolErrorEvent: # If it's a generic ToolErrorEvent (e.g. from CodeIndexQueryAgent)
                        yield event # Forward the already constructed ToolErrorEvent
                    else:
                        ai_logger.warning(f"No specific error event class found for step type {step.step_type} and tool {event.tool_name}")


                if step.step_type == StepType.FILESYSTEM: filesystem_step_has_tool_errors = True
                if step.step_type == StepType.PYTHON: python_step_has_tool_errors = True
                if step.step_type == StepType.CODE_INDEX_QUERY: code_index_query_step_has_tool_errors = True # Added
                step_result.add_error(f"Error in tool {event.tool_name}: {event.error}")
            elif isinstance(event, BaseEvent): # Catch other BaseEvents that might be ToolErrorEvent from CodeIndexQueryAgent
                if isinstance(event, ToolErrorEvent) and event.tool_name and event.tool_name.endswith("qdrant-find"):
                    code_index_query_step_has_tool_errors = True
                    step_result.add_error(f"Error in tool {event.tool_name}: {event.error}")
                ai_logger.info(f"Step {step.step_id} yielding generic BaseEvent: {type(event)}")
                yield event
        
        if step.step_type == StepType.MARKDOWN and final_result_data:
            dependency_cell_ids = [cid for dep_id in step.dependencies for cid in plan_step_id_to_cell_ids.get(dep_id, [])]
            created_cell_id, cell_params, cell_error = await self.cell_creator.create_markdown_cell(
                cell_tools=cell_tools, step=step, result=final_result_data,
                dependency_cell_ids=dependency_cell_ids, session_id=session_id
            )
            if cell_error:
                step_result.add_error(cell_error)
            if created_cell_id:
                plan_step_id_to_cell_ids.setdefault(step.step_id, []).append(created_cell_id)
                step_result.add_cell_id(created_cell_id)
            
            if step_result.has_error():
                yield StepErrorEvent(
                    step_id=step.step_id,
                    step_type=step.step_type.value,
                    cell_id=str(created_cell_id) if created_cell_id else None,
                    cell_params=cell_params.model_dump() if cell_params else None,
                    result=None, # Or a minimal representation if appropriate for errors
                    error=step_result.get_combined_error(),
                    agent_type=agent_type,
                    session_id=session_id,
                    notebook_id=self.notebook_id
                )
            else:
                ai_logger.info(f"Step {step.step_id} (Markdown) yielding StepCompletedEvent. Cell ID: {created_cell_id}")
                yield StepCompletedEvent(
                    step_id=step.step_id,
                    step_type=step.step_type.value,
                    cell_id=str(created_cell_id) if created_cell_id else None,
                    cell_params=cell_params.model_dump() if cell_params else None,
                    result=final_result_data.model_dump() if final_result_data else None,
                    # No 'error' field for StepCompletedEvent
                    agent_type=agent_type,
                    session_id=session_id,
                    notebook_id=self.notebook_id
                )
        
        elif step.step_type == StepType.MEDIA_TIMELINE and final_result_data:
            dependency_cell_ids = [cid for dep_id in step.dependencies for cid in plan_step_id_to_cell_ids.get(dep_id, [])]
            created_cell_id, cell_params, cell_error = await self.cell_creator.create_media_timeline_cell(
                cell_tools=cell_tools,
                step=step,
                payload=final_result_data,
                dependency_cell_ids=dependency_cell_ids,
                session_id=session_id
            )

            if cell_error:
                step_result.add_error(cell_error)

            if created_cell_id:
                plan_step_id_to_cell_ids.setdefault(step.step_id, []).append(created_cell_id)
                step_result.add_cell_id(created_cell_id)

            yield MediaTimelineCellCreatedEvent(
                cell_id=str(created_cell_id) if created_cell_id else "",
                cell_params=cell_params.model_dump() if cell_params else {},
                session_id=session_id,
                notebook_id=self.notebook_id
            )
            # For frontend compatibility also yield StepCompletedEvent
            if step_result.has_error():
                yield StepErrorEvent(
                    step_id=step.step_id,
                    step_type=step.step_type.value,
                    cell_id=str(created_cell_id) if created_cell_id else None,
                    cell_params=cell_params.model_dump() if cell_params else None,
                    result=None,
                    error=step_result.get_combined_error(),
                    agent_type=agent_type,
                    session_id=session_id,
                    notebook_id=self.notebook_id
                )
            else:
                yield StepCompletedEvent(
                    step_id=step.step_id,
                    step_type=step.step_type.value,
                    cell_id=str(created_cell_id) if created_cell_id else None,
                    cell_params=cell_params.model_dump() if cell_params else None,
                    result=final_result_data.model_dump() if hasattr(final_result_data, 'model_dump') else None,
                    agent_type=agent_type,
                    session_id=session_id,
                    notebook_id=self.notebook_id,
                )
        
        step_results[step.step_id] = step_result
        ai_logger.info(f"Step {step.step_id} execution complete. Final result data type: {type(final_result_data)}, Has error: {step_result.has_error()}")
        ai_logger.info(f"Step {step.step_id} final outputs: {step_result.outputs}")
        ai_logger.info(f"Step {step.step_id} combined error: {step_result.get_combined_error()}")
        yield StepExecutionCompleteEvent(
            step_id=step.step_id, final_result_data=final_result_data,
            step_outputs=step_result.outputs, step_error=step_result.get_combined_error(),
            github_step_has_tool_errors=github_step_has_tool_errors,
            filesystem_step_has_tool_errors=filesystem_step_has_tool_errors,
            python_step_has_tool_errors=python_step_has_tool_errors,
            code_index_query_step_has_tool_errors=code_index_query_step_has_tool_errors, # Added
            session_id=session_id, notebook_id=self.notebook_id
        )
    
    async def _process_tool_success_event(
        self, 
        event: ToolSuccessEvent,
        step: InvestigationStepModel,
        step_type: StepType,
        agent_type: AgentType,
        plan_step_id_to_cell_ids: Dict[str, List[UUID]],
        cell_tools: NotebookCellTools,
        session_id: str,
        created_event_class: Type, # This should be Type[BaseEvent] or similar
        step_result: StepResult
    ) -> Tuple[Any, BaseEvent]:
        """Process a tool success event and conditionally create a cell for it"""
        dependency_cell_ids = [cid for dep_id in step.dependencies for cid in plan_step_id_to_cell_ids.get(dep_id, [])]
        
        # Determine cell_type (needed if cell is created)
        agent_to_cell_type_map = {
            AgentType.GITHUB: CellType.GITHUB,
            AgentType.FILESYSTEM: CellType.FILESYSTEM,
            AgentType.PYTHON: CellType.PYTHON,
            AgentType.SQL: CellType.SQL,
            AgentType.S3: CellType.S3,
            AgentType.METRIC: CellType.METRIC,
            AgentType.CODE_INDEX_QUERY: CellType.CODE_INDEX_QUERY,
            AgentType.LOG_AI: CellType.LOG_AI,
        }
        current_event_agent_type = event.agent_type if event.agent_type is not None else AgentType.UNKNOWN
        cell_type = agent_to_cell_type_map.get(current_event_agent_type, CellType.AI_QUERY)
        if cell_type == CellType.AI_QUERY and current_event_agent_type != AgentType.UNKNOWN:
             ai_logger.warning(
                f"No specific CellType mapping for AgentType '{current_event_agent_type.value}' "
                f"that executed tool '{event.tool_name}'. Defaulting cell to AI_QUERY."
            )

        tool_name_str = event.tool_name or "unknown_tool"
        serialized_result = self.cell_creator._serialize_tool_result(event.tool_result, tool_name_str)
        step_result.add_output(serialized_result) # Add output to step_result regardless of cell creation

        created_cell_id: Optional[UUID] = None
        cell_params_model: Optional[Any] = None # To store the Pydantic model for cell_params
        cell_creation_error_msg: Optional[str] = None

        # Conditionally create a cell
        if tool_name_str not in self.INTERNAL_NOTEBOOK_CONTEXT_TOOLS:
            ai_logger.info(f"Tool {tool_name_str} is not internal. Attempting to create cell.")
            created_cell_id, cell_params_model, cell_creation_error_msg = await self.cell_creator.create_tool_cell(
                cell_tools=cell_tools, step=step, cell_type=cell_type,
                agent_type=agent_type, tool_event=event, # Pass the original event for context
                dependency_cell_ids=dependency_cell_ids, session_id=session_id
            )

            if cell_creation_error_msg:
                ai_logger.warning(f"Error creating cell for {step_type.value} tool {event.tool_name}: {cell_creation_error_msg}")
                step_result.add_error(cell_creation_error_msg)
                # created_cell_id remains None if error, cell_params_model might be partially filled by create_tool_cell or None
            elif created_cell_id: # Cell creation was successful
                ai_logger.info(f"Successfully created cell {created_cell_id} for tool {tool_name_str}.")
                step_result.add_cell_id(created_cell_id)
                plan_step_id_to_cell_ids.setdefault(step.step_id, []).append(created_cell_id)
            else:
                # This case (no error, no cell_id) might indicate an issue in create_tool_cell logic
                ai_logger.warning(f"Cell creation for tool {tool_name_str} did not return an ID nor an error.")
        else:
            ai_logger.info(f"Skipping cell creation for internal notebook tool: {tool_name_str}")
            # No cell is created, created_cell_id and cell_params_model remain None.

        # Create the tool event, ensuring cell_id and cell_params are handled correctly
        final_cell_params_dict: Optional[Dict[str, Any]] = None
        if cell_params_model:
            try:
                final_cell_params_dict = cell_params_model.model_dump()
            except Exception as e:
                ai_logger.error(f"Failed to dump cell_params model for tool {tool_name_str}: {e}")
                # Keep final_cell_params_dict as None
        
        tool_event = created_event_class(
            original_plan_step_id=step.step_id,
            cell_id=str(created_cell_id) if created_cell_id else None,
            tool_name=event.tool_name, # Use original tool_name from event
            tool_args=event.tool_args or {},
            result=event.tool_result, # Pass the raw tool_result as per current logic
            cell_params=final_cell_params_dict, # Use the dumped dict or None
            session_id=session_id,
            notebook_id=self.notebook_id
        )

        return serialized_result, tool_event
    
    def _build_step_context(
        self,
        step: InvestigationStepModel,
        executed_steps: Dict[str, Any],
        step_results: Dict[str, StepResult],
        plan_step_id_to_cell_ids: Dict[str, List[UUID]]
    ) -> Dict[str, Any]:
        """Build context from dependencies for a step"""
        context = {"prompt": step.description}
        
        ai_logger.info(f"Building context for step {step.step_id}. Initial prompt: {context['prompt'][:1000]}...")
        if step.parameters:
            params_str = "\n".join([f"- {k}: {v}" for k, v in step.parameters.items()])
            context["prompt"] += f"\n\nParameters for this step:\n{params_str}"
            ai_logger.info(f"Step {step.step_id} parameters added to prompt: {params_str}")
        
        dependency_context = []
        for dep_id in step.dependencies:
            if dep_id in executed_steps:
                dep_step_info = executed_steps[dep_id]

                if not isinstance(dep_step_info, dict):
                    ai_logger.warning(f"Dependency info for {dep_id} is not a dictionary: {type(dep_step_info)}. Skipping context for this dependency.")
                    dependency_context.append(f"- Dependency '{dep_id}': Information malformed or unavailable.")
                    continue

                raw_dep_step_model_data = dep_step_info.get('step')
                dep_overall_error = dep_step_info.get('error')
                dep_result_obj = step_results.get(dep_id)

                if not raw_dep_step_model_data: # This check handles if 'step' key is missing or its value is None
                    ai_logger.warning(f"Could not find step model data for dependency ID {dep_id} in executed_steps.")
                    dependency_context.append(f"- Dependency '{dep_id}': Step model data unavailable.")
                    continue
                
                # Ensure raw_dep_step_model_data is a dict before attempting to create InvestigationStepModel from it
                if not isinstance(raw_dep_step_model_data, dict):
                    ai_logger.error(f"Step model data for dependency {dep_id} is not a dictionary: {type(raw_dep_step_model_data)}. Skipping.")
                    dependency_context.append(f"- Dependency '{dep_id}': Invalid step model data format.")
                    continue

                try:
                    dep_step_model = InvestigationStepModel(**raw_dep_step_model_data)
                except Exception as e:
                    ai_logger.error(f"Failed to parse InvestigationStepModel for dependency {dep_id} from data {raw_dep_step_model_data}: {e}")
                    dependency_context.append(f"- Dependency '{dep_id}': Error parsing step model data.")
                    continue
                    
                context_limit = STEP_CONTEXT_SNIPPET_LIMIT # Use updated limit
                context_line = f"- Dependency '{dep_id}' ({dep_step_model.step_type.value}): {dep_step_model.description[:context_limit]}..."
                
                if isinstance(dep_result_obj, StepResult) and dep_result_obj.outputs:
                    context_line += " (Outputs Available)"
                    outputs_summary_lines = []
                    for i, out_data in enumerate(dep_result_obj.outputs): # Limit number of outputs summarized
                        summary_prefix = f"  - Output {i+1}:"
                        if isinstance(out_data, dict):
                            if out_data.get("status") == "success" and "stdout" in out_data and out_data.get("stdout") is not None:
                                outputs_summary_lines.append(f"{summary_prefix} (stdout): {str(out_data['stdout'])[:context_limit].strip()}...")
                            elif "path" in out_data and "content" in out_data:
                                outputs_summary_lines.append(f"{summary_prefix} (file: {out_data['path']}): {str(out_data['content'])[:context_limit].strip()}...")
                            elif "search_results" in out_data:
                                search_results_data = out_data.get("search_results")
                                count = len(search_results_data) if isinstance(search_results_data, list) else 0
                                first_item_str = str(search_results_data[0])[:context_limit] if search_results_data and count > 0 else ""
                                outputs_summary_lines.append(f"{summary_prefix} ({count} search results found).{' First: ' + first_item_str + '...' if count > 0 else ''}")
                            else:
                                outputs_summary_lines.append(f"{summary_prefix} {str(out_data)[:context_limit].strip()}...")
                        elif isinstance(out_data, list):
                             outputs_summary_lines.append(f"{summary_prefix} (list with {len(out_data)} items). First: {str(out_data[0])[:context_limit]}..." if out_data else f"{summary_prefix} (empty list).")
                        elif isinstance(out_data, QueryResult):
                             outputs_summary_lines.append(f"{summary_prefix} {str(out_data.data)[:context_limit].strip()}...")
                        else:
                            outputs_summary_lines.append(f"{summary_prefix} {str(out_data)[:context_limit].strip()}...")
                    
                    if outputs_summary_lines: context_line += "\n" + "\n".join(outputs_summary_lines)
                    else: context_line += " (Step had outputs, but they could not be summarized for context.)"
                elif dep_overall_error:
                    context_line += f" (Failed: {str(dep_overall_error)[:context_limit]}... No usable output data for context.)"
                elif isinstance(dep_result_obj, StepResult) and dep_result_obj.has_error():
                     combined_error = dep_result_obj.get_combined_error()
                     error_snippet = str(combined_error)[:context_limit] if combined_error else "Unknown error"
                     context_line += f" (Failed: {error_snippet}... No usable output data for context.)"
                else:
                    context_line += " (Completed with no specific output data for context.)"
                dependency_context.append(context_line)
        
        if dependency_context:
            context["prompt"] += f"\n\nContext from Dependencies:\n" + "\n".join(dependency_context)
            ai_logger.info(f"Step {step.step_id} full dependency context: {' '.join(dependency_context)}")

        dep_cell_ids_for_prompt = {}
        for dep_id in step.dependencies:
            if dep_id in plan_step_id_to_cell_ids and plan_step_id_to_cell_ids[dep_id]:
                dep_cell_ids_for_prompt[dep_id] = [str(uuid_val) for uuid_val in plan_step_id_to_cell_ids[dep_id]]

        if dep_cell_ids_for_prompt:
            dep_cell_ids_str = json.dumps(dep_cell_ids_for_prompt, indent=2)
            context["prompt"] += f"\n\nDependency Cell IDs (from orchestrator):\n{dep_cell_ids_str}"
        
        return context
    
    def _format_findings_for_report(
        self,
        step: InvestigationStepModel,
        executed_steps: Dict[str, Any],
        step_results: Dict[str, StepResult] 
    ) -> str:
        """Format findings from previous steps for the report"""
        findings_text_lines = []
        ai_logger.info(f"Formatting findings for report step {step.step_id}. Dependencies: {step.dependencies}")

        if not step.dependencies:
            return "No dependencies specified for this report step. Unable to gather findings."

        for dep_id in step.dependencies:
            if dep_id not in executed_steps:
                ai_logger.warning(f"Dependency step_id '{dep_id}' for report step '{step.step_id}' not found in executed_steps. Skipping.")
                findings_text_lines.append(f"Step {dep_id}: Data unavailable (step not found in execution history).")
                continue
            
            step_info = executed_steps[dep_id]
            step_obj_data_any = step_info.get("step")
            step_res_obj = step_results.get(dep_id)
            step_error_msg = step_info.get("error")

            desc = "N/A (description unavailable)"
            type_val = "unknown (type unavailable)"
            dep_step_model: Optional[InvestigationStepModel] = None

            if isinstance(step_obj_data_any, dict):
                try:
                    dep_step_model = InvestigationStepModel(**step_obj_data_any)
                except Exception as e:
                    ai_logger.error(f"Failed to parse InvestigationStepModel for dep_id '{dep_id}' in _format_findings_for_report from dict: {e}")
            elif isinstance(step_obj_data_any, InvestigationStepModel):
                dep_step_model = step_obj_data_any
            elif step_obj_data_any is None:
                ai_logger.warning(f"Step data for dep_id '{dep_id}' is None in _format_findings_for_report.")
            else:
                ai_logger.warning(f"Unexpected type for step_obj_data for dep_id '{dep_id}': {type(step_obj_data_any)} in _format_findings_for_report.")

            if dep_step_model:
                desc = dep_step_model.description
                if isinstance(dep_step_model.step_type, StepType):
                    type_val = dep_step_model.step_type.value
                elif dep_step_model.step_type:
                    type_val = str(dep_step_model.step_type)
                else:
                    type_val = "unknown (step_type missing)"
            
            result_str = ""
            if step_error_msg:
                result_str = f"Error: {step_error_msg}"
            elif isinstance(step_res_obj, StepResult):
                if step_res_obj.has_error():
                    result_str = f"Error: {step_res_obj.get_combined_error()}"
                elif step_res_obj.outputs:
                    if step_res_obj.step_type == StepType.MARKDOWN and step_res_obj.outputs:
                        output = step_res_obj.outputs[0]
                        data_to_show = output.data if isinstance(output, QueryResult) else output
                        result_str = f"Data: {str(data_to_show)[:REPORT_CONTEXT_SNIPPET_LIMIT]}..."
                    else:
                        formatted_outputs = []
                        for i, output_data in enumerate(step_res_obj.outputs[:5]):
                            output_summary = str(output_data)[:REPORT_CONTEXT_SNIPPET_LIMIT // 2]
                            formatted_outputs.append(f"  - Output {i+1}: {output_summary}...")
                        if len(step_res_obj.outputs) > 5:
                            formatted_outputs.append(f"  ... and {len(step_res_obj.outputs) - 5} more outputs.")
                        result_str = "Data (multiple outputs):\\n" + "\\n".join(formatted_outputs) if formatted_outputs else "Step completed, but no specific outputs captured."
                else:
                    result_str = "Step completed, but no outputs available in StepResult."
            else:
                result_str = "Step completed without explicit data/error capture in StepResult."
            
            findings_text_lines.append(f"Step {dep_id} ({type_val}): {desc}\\nResult:\\n{result_str}")
        
        return "\\n---\\n".join(findings_text_lines) if findings_text_lines else "No findings could be gathered from the dependent steps."
