"""
Agent implementations for different step types.
"""

import logging
from typing import Any, Dict, AsyncGenerator, Union, Optional, List, TYPE_CHECKING # Added List and TYPE_CHECKING
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

from backend.ai.models import InvestigationStepModel
from backend.ai.events import (
    BaseEvent, AgentType, StatusType, StatusUpdateEvent,
    ToolSuccessEvent, ToolErrorEvent, FinalStatusEvent, FatalErrorEvent, # Added FatalErrorEvent
    GitHubStepProcessingCompleteEvent, FileSystemStepProcessingCompleteEvent,
    PythonStepProcessingCompleteEvent # Added
)
from backend.core.query_result import MarkdownQueryResult, InvestigationReport, Finding
from backend.ai.github_query_agent import GitHubQueryAgent
from backend.ai.investigation_report_agent import InvestigationReportAgent
from backend.ai.filesystem_agent import FileSystemAgent
from backend.ai.python_agent import PythonAgent
from backend.ai.models import PythonAgentInput, FileDataRef # Added for PythonStepAgent
from backend.ai.prompts.investigation_prompts import MARKDOWN_GENERATOR_SYSTEM_PROMPT
from backend.config import get_settings
from backend.services.notebook_manager import NotebookManager # Added import
from backend.ai.notebook_context_tools import create_notebook_context_tools # Added import

# Type-only import to satisfy static checkers for forward reference
if TYPE_CHECKING:
    from backend.ai.logai_agent import LogAIAgent
    from backend.ai.media_agent import MediaTimelineAgent

ai_logger = logging.getLogger("ai")

def _create_contextual_xml_prompt(description: str, context: Dict[str, Any]) -> str:
    """Helper function to create an XML-formatted prompt with context and timestamp."""
    current_time_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
    
    # Escape CDATA closing sequence in description
    safe_description = description.replace("]]>'", "]] ]]> <![CDATA[")

    context_items_xml_parts = []
    if context:
        for key, value in context.items():
            # Escape CDATA closing sequence in context values
            safe_value = str(value).replace("]]>'", "]] ]]> <![CDATA[")
            context_items_xml_parts.append(f'        <item key="{key}"><![CDATA[{safe_value}]]></item>')
    context_items_xml = "\n".join(context_items_xml_parts)
    
    prompt_with_context = f"""<task_with_context>
    <user_query><![CDATA[{safe_description}]]></user_query>
    <current_time_utc>{current_time_utc_str}</current_time_utc>"""
    
    if context_items_xml:
        prompt_with_context += f"""
    <shared_context>
{context_items_xml}
    </shared_context>"""
    prompt_with_context += """
</task_with_context>"""
    return prompt_with_context


class StepAgent(ABC):
    """Base class for step-specific agent implementations"""
    def __init__(self, notebook_id: str):
        self.notebook_id = notebook_id
        self.settings = get_settings()
    
    @abstractmethod
    async def execute(self, 
                      step: InvestigationStepModel, 
                      agent_input_data: Union[str, PythonAgentInput], # Changed from prompt: str
                      session_id: str, 
                      context: Dict[str, Any],
                      db: Optional[AsyncSession] = None  # Added db parameter, make it optional for non-Python agents
                      ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Execute the step and yield events/results."""
        pass
    
    @abstractmethod
    def get_agent_type(self) -> AgentType:
        """Return the agent type for this step agent."""
        pass


class MarkdownStepAgent(StepAgent):
    """Agent for executing markdown steps"""
    def __init__(
        self,
        notebook_id: str,
        model: OpenAIModel,
        notebook_manager: Optional[NotebookManager],
        mcp_servers: Optional[List[Any]] = None,
    ) -> None:
        """Create a MarkdownStepAgent.

        Parameters
        ----------
        notebook_id : str
            The notebook UUID this agent operates in.
        model : OpenAIModel
            LLM wrapper to use for markdown generation.
        notebook_manager : Optional[NotebookManager]
            Gives the agent access to notebook-level helpers/tools.
        mcp_servers : Optional[List[Any]]
            A list of already-initialised MCP servers (e.g. for qdrant) that
            should be forwarded to the internal pydantic-ai Agent so that
            markdown generation can call tools such as `qdrant.qdrant-find`.
        """

        super().__init__(notebook_id)
        self.model = model
        self.notebook_manager = notebook_manager  # Store notebook_manager
        # Keep only Qdrant MCP servers – Markdown generation only needs semantic code search,
        # not GitHub or Filesystem toolsets.
        self.mcp_servers = [
            s for s in (mcp_servers or [])
            if str(getattr(s, "command", "")).endswith("mcp-server-qdrant")
        ]

        # Create notebook context tools
        notebook_tools = create_notebook_context_tools(self.notebook_id, self.notebook_manager)

        # pydantic-ai Agent with tool + MCP support
        self.markdown_generator = Agent(
            self.model,
            output_type=MarkdownQueryResult,
            system_prompt=MARKDOWN_GENERATOR_SYSTEM_PROMPT,
            tools=notebook_tools,
        )
    
    def get_agent_type(self) -> AgentType:
        return AgentType.MARKDOWN
    
    async def execute(self, 
                     step: InvestigationStepModel, 
                     agent_input_data: Union[str, PythonAgentInput], # Changed from prompt
                     session_id: str, 
                     context: Dict[str, Any],
                     db: Optional[AsyncSession] = None # Added db parameter
                     ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Generate markdown content for the step"""
        if not isinstance(agent_input_data, str):
            # This case should ideally not happen for MarkdownStepAgent
            # Or handle it by converting/logging if necessary
            raise TypeError(f"MarkdownStepAgent expects a string prompt, got {type(agent_input_data)}")
        original_description = agent_input_data

        # Construct XML prompt with context using the helper function
        prompt_with_context = _create_contextual_xml_prompt(original_description, context)

        yield StatusUpdateEvent(
            status=StatusType.AGENT_ITERATING, 
            agent_type=self.get_agent_type(), 
            message="Generating Markdown...", 
            attempt=None, 
            max_attempts=None, 
            reason=None, 
            step_id=step.step_id, 
            original_plan_step_id=None, 
            session_id=session_id, 
            notebook_id=self.notebook_id
        )
        
        result = await self.markdown_generator.run(prompt_with_context)
        if isinstance(result.output, MarkdownQueryResult):
            final_result = result.output
        else:
            ai_logger.warning(f"Markdown generator did not return MarkdownQueryResult. Got: {type(result.output)}. Falling back.")
            fallback_content = str(result.output) if result.output else ''
            final_result = MarkdownQueryResult(query=step.description, data=fallback_content)
            
        yield {"type": "final_step_result", "result": final_result}


class GitHubStepAgent(StepAgent):
    """Agent for executing GitHub steps"""
    def __init__(self, notebook_id: str):
        super().__init__(notebook_id)
        self.github_generator = None  # Lazily initialized
    
    def get_agent_type(self) -> AgentType:
        return AgentType.GITHUB
    
    async def execute(self, 
                     step: InvestigationStepModel, 
                     agent_input_data: Union[str, PythonAgentInput], # Changed from prompt
                     session_id: str, 
                     context: Dict[str, Any],
                     db: Optional[AsyncSession] = None # Added db parameter
                     ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Execute a GitHub query step"""
        if not isinstance(agent_input_data, str):
            raise TypeError(f"GitHubStepAgent expects a string prompt, got {type(agent_input_data)}")
        original_description = agent_input_data

        # Construct XML prompt with context using the helper function
        prompt_with_context = _create_contextual_xml_prompt(original_description, context)

        # Lazy initialization
        if self.github_generator is None:
            ai_logger.info("Lazily initializing GitHubQueryAgent.")
            self.github_generator = GitHubQueryAgent(notebook_id=self.notebook_id)
        
        ai_logger.info(f"Processing GitHub step {step.step_id} using run_query generator with XML prompt...")
        
        # Forward events from the GitHub agent
        async for event in self.github_generator.run_query(
            prompt_with_context, # Use the new XML prompt
            session_id=session_id,
            notebook_id=self.notebook_id
        ):
            # Forward specific event types
            if isinstance(event, (StatusUpdateEvent, ToolSuccessEvent, ToolErrorEvent)):
                yield event
            elif isinstance(event, FinalStatusEvent):
                ai_logger.info(f"GitHub query finished for step {step.step_id} with status: {event.status}")
            elif isinstance(event, BaseEvent):
                ai_logger.warning(f"Unexpected BaseEvent type {type(event)} from GitHub agent: {event!r}")
            else:
                ai_logger.warning(f"Unexpected non-BaseEvent type {type(event)} from GitHub agent: {event!r}")
        
        # Signal completion of this step
        yield GitHubStepProcessingCompleteEvent(
            original_plan_step_id=step.step_id,
            session_id=session_id,
            notebook_id=self.notebook_id
        )


class FileSystemStepAgent(StepAgent):
    """Agent for executing filesystem steps"""
    def __init__(self, notebook_id: str):
        super().__init__(notebook_id)
        self.filesystem_generator = None  # Lazily initialized
    
    def get_agent_type(self) -> AgentType:
        return AgentType.FILESYSTEM
    
    async def execute(self, 
                     step: InvestigationStepModel, 
                     agent_input_data: Union[str, PythonAgentInput], # Changed from prompt
                     session_id: str, 
                     context: Dict[str, Any],
                     db: Optional[AsyncSession] = None # Added db parameter
                     ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Execute a filesystem query step"""
        if not isinstance(agent_input_data, str):
            raise TypeError(f"FileSystemStepAgent expects a string prompt, got {type(agent_input_data)}")
        original_description = agent_input_data

        # Construct XML prompt with context using the helper function
        prompt_with_context = _create_contextual_xml_prompt(original_description, context)
        
        # Lazy initialization
        if self.filesystem_generator is None:
            ai_logger.info("Lazily initializing FileSystemAgent.")
            self.filesystem_generator = FileSystemAgent(notebook_id=self.notebook_id)
        
        ai_logger.info(f"Processing Filesystem step {step.step_id} using run_query generator with XML prompt...")
        
        # Forward events from the filesystem agent
        async for event in self.filesystem_generator.run_query(
            prompt_with_context, # Use the new XML prompt
            session_id=session_id,
            notebook_id=self.notebook_id
        ):
            # Forward relevant events
            if isinstance(event, (ToolSuccessEvent, ToolErrorEvent, StatusUpdateEvent)):
                yield event
            elif isinstance(event, FinalStatusEvent):
                ai_logger.info(f"FileSystem query finished for step {step.step_id} with status: {event.status}")
            elif isinstance(event, BaseEvent):
                ai_logger.warning(f"Unexpected BaseEvent type {type(event)} from Filesystem agent: {event!r}")
            else:
                ai_logger.warning(f"Unexpected non-BaseEvent type {type(event)} from Filesystem agent: {event!r}")
        
        # Signal completion of this step
        yield FileSystemStepProcessingCompleteEvent(
            original_plan_step_id=step.step_id,
            session_id=session_id,
            notebook_id=self.notebook_id
        )


class PythonStepAgent(StepAgent):
    """Agent for executing Python steps"""
    def __init__(self, notebook_id: str, notebook_manager: Optional[NotebookManager] = None):
        super().__init__(notebook_id)
        self.python_generator: Optional[PythonAgent] = None  # Lazily initialized
        self.notebook_manager = notebook_manager # Store notebook_manager
    
    def get_agent_type(self) -> AgentType:
        return AgentType.PYTHON
    
    async def execute(self, 
                     step: InvestigationStepModel, 
                     agent_input_data: Union[str, PythonAgentInput], # Changed parameter name
                     session_id: str, # session_id is available here but PythonAgent.run_query might not need it if it's in agent_input_data
                     context: Dict[str, Any],
                     db: Optional[AsyncSession] = None # Added db parameter, used by PythonAgent
                     ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Execute a Python query step"""
        if not isinstance(agent_input_data, PythonAgentInput):
            # This case should ideally not happen if step_processor correctly sets agent_input_data
            raise TypeError(f"PythonStepAgent expects PythonAgentInput, got {type(agent_input_data)}")
        
        # Lazy initialization
        if self.python_generator is None:
            ai_logger.info("Lazily initializing PythonAgent for Python steps.")
            self.python_generator = PythonAgent(notebook_id=self.notebook_id, notebook_manager=self.notebook_manager)
        
        ai_logger.info(f"Processing Python step {step.step_id} using run_query generator...")
        
        # Forward events from the Python agent
        # PythonAgent.run_query should expect PythonAgentInput which contains notebook_id and session_id
        # Also pass db session to PythonAgent.run_query
        async for event in self.python_generator.run_query(agent_input=agent_input_data, db=db):
            # Forward relevant events
            if isinstance(event, (ToolSuccessEvent, ToolErrorEvent, StatusUpdateEvent, FatalErrorEvent)):
                yield event
            elif isinstance(event, FinalStatusEvent):
                ai_logger.info(f"Python query finished for step {step.step_id} with status: {event.status}")
            elif isinstance(event, BaseEvent):
                ai_logger.warning(f"Unexpected BaseEvent type {type(event)} from Python agent: {event!r}")
            else:
                ai_logger.warning(f"Unexpected non-BaseEvent type {type(event)} from Python agent: {event!r}")
        
        # Signal completion of this step
        yield PythonStepProcessingCompleteEvent( # Corrected event
            original_plan_step_id=step.step_id,
            session_id=session_id,
            notebook_id=self.notebook_id
        )


class MediaTimelineStepAgent(StepAgent):
    """Agent for executing media timeline steps"""
    def __init__(self, notebook_id: str, connection_manager: Any, notebook_manager: Optional[NotebookManager] = None, mcp_servers: Optional[List[Any]] = None): # Added mcp_servers
        super().__init__(notebook_id)
        self.connection_manager = connection_manager
        self.notebook_manager = notebook_manager
        self.mcp_servers = mcp_servers or [] # Store mcp_servers
        # Will be instantiated per execute call since it requires session_id
        self.timeline_agent: Optional[MediaTimelineAgent] = None

    def get_agent_type(self) -> AgentType:
        return AgentType.MEDIA_TIMELINE

    async def execute(
        self,
        step: InvestigationStepModel,
        agent_input_data: Union[str, PythonAgentInput],  # Should be description string
        session_id: str,
        context: Dict[str, Any],
        db: Optional[AsyncSession] = None  # Unused but kept for compatibility
    ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Run the MediaTimelineAgent and forward its events"""
        if not isinstance(agent_input_data, str):
            raise TypeError(f"MediaTimelineStepAgent expects a string description, got {type(agent_input_data)}")

        description = agent_input_data

        # Local import to handle potential NameError if module-level import isn't effective.
        from backend.ai.media_agent import MediaTimelineAgent

        # (Re)instantiate the MediaTimelineAgent for this execution so it has correct session_id
        self.timeline_agent = MediaTimelineAgent(
            notebook_id=self.notebook_id,
            session_id=session_id,
            connection_manager=self.connection_manager,
            notebook_manager=self.notebook_manager,
            mcp_servers=self.mcp_servers # Pass mcp_servers
        )

        ai_logger.info(f"Processing MediaTimeline step {step.step_id} using timeline agent...")

        # Forward events from timeline agent
        async for event in self.timeline_agent.run_query(description, context=context):
            if isinstance(event, BaseEvent):
                # Ensure session and notebook IDs are set if missing
                if not event.session_id:
                    event.session_id = session_id
                if not event.notebook_id:
                    event.notebook_id = self.notebook_id
                yield event
            elif isinstance(event, dict):
                # Not expected for timeline agent currently. Log and ignore
                ai_logger.warning(f"Unexpected dict event from MediaTimelineAgent: {event}")
            else:
                # Assume it's the final MediaTimelinePayload object
                yield {"type": "final_step_result", "result": event}


class ReportStepAgent(StepAgent):
    """Agent for generating investigation reports"""
    def __init__(self, notebook_id: str, mcp_servers: Optional[List[Any]] = None): # Added mcp_servers
        super().__init__(notebook_id)
        self.mcp_servers = mcp_servers or [] # Store mcp_servers
        self.report_generator = None  # Lazily initialized
    
    def get_agent_type(self) -> AgentType:
        return AgentType.INVESTIGATION_REPORT_GENERATOR
    
    async def execute(self, 
                     step: InvestigationStepModel, 
                     agent_input_data: Union[str, PythonAgentInput], # Changed from prompt
                     session_id: str, 
                     context: Dict[str, Any],
                     db: Optional[AsyncSession] = None # Added db parameter
                     ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Generate an investigation report"""
        if not isinstance(agent_input_data, str):
            raise TypeError(f"ReportStepAgent expects a string prompt, got {type(agent_input_data)}")
        # prompt = agent_input_data # Not directly used by report_generator.run_report_generation

        # Extract required context
        findings_text = context.get("findings_text", "")
        original_query = context.get("original_query", "") # This seems to be the main "prompt" for the report
        
        # Lazy initialization
        if self.report_generator is None:
            ai_logger.info("Lazily initializing InvestigationReportAgent.")
            self.report_generator = InvestigationReportAgent(notebook_id=self.notebook_id, mcp_servers=self.mcp_servers) # Pass mcp_servers
        
        ai_logger.info(f"Processing Report step {step.step_id}...")
        final_report_object = None
        report_error = None
        
        try:
            async for result_part in self.report_generator.run_report_generation(
                original_query=original_query,
                findings_summary=findings_text,
                session_id=session_id,
                notebook_id=self.notebook_id
            ):
                if isinstance(result_part, InvestigationReport):
                    final_report_object = result_part
                    report_error = final_report_object.error
                    yield StatusUpdateEvent(
                        status=StatusType.SUCCESS,
                        message="Report object generated",
                        agent_type=self.get_agent_type(),
                        attempt=None,
                        max_attempts=None,
                        reason=None,
                        step_id=step.step_id,
                        original_plan_step_id=None,
                        session_id=session_id,
                        notebook_id=self.notebook_id
                    )
                    break
                elif isinstance(result_part, StatusUpdateEvent):
                    # Forward status updates
                    if result_part.session_id is None:
                        result_part.session_id = session_id
                    if result_part.notebook_id is None:
                        result_part.notebook_id = self.notebook_id
                    yield result_part
                else:
                    ai_logger.warning(f"Unexpected item from report generator: {type(result_part)}")
            
            if final_report_object is None:
                report_error = "Report agent did not return a final report object."
                ai_logger.error(report_error)
                # Create a placeholder error report
                final_report_object = self._create_error_report(original_query, report_error)
                
        except Exception as e:
            report_error = f"Error during report generation: {e}"
            ai_logger.error(report_error, exc_info=True)
            # Create a placeholder error report
            final_report_object = self._create_error_report(original_query, report_error)
        
        yield {"type": "final_step_result", "result": final_report_object, "error": report_error}
    
    def _create_error_report(self, query: str, error_message: str) -> InvestigationReport:
        """Create a placeholder error report when generation fails"""
        return InvestigationReport(
            query=query,
            title="Report Generation Failed",
            issue_summary=Finding(summary="Generation Error", details=None, code_reference=None, supporting_quotes=None),
            root_cause=Finding(summary="Generation Error", details=None, code_reference=None, supporting_quotes=None),
            error=error_message,
            status=None,
            status_reason="Generation Error",
            estimated_severity=None,
            root_cause_confidence=None,
            proposed_fix=None,
            proposed_fix_confidence=None,
            affected_context=None,
            key_components=[],
            related_items=[],
            suggested_next_steps=[],
            tags=[]
        )


class LogAIStepAgent(StepAgent):
    """Agent for executing Log-AI (log analysis) steps via FastMCP server."""

    def __init__(self, notebook_id: str, notebook_manager: Optional[NotebookManager] = None):
        super().__init__(notebook_id)
        self.log_ai_generator: Optional["LogAIAgent"] = None  # lazy
        self.notebook_manager = notebook_manager

    def get_agent_type(self) -> AgentType:
        return AgentType.LOG_AI

    async def execute(
        self,
        step: InvestigationStepModel,
        agent_input_data: Union[str, PythonAgentInput],  # Expecting plain description string
        session_id: str,
        context: Dict[str, Any],
        db: Optional[AsyncSession] = None,  # Unused for Log-AI
    ) -> AsyncGenerator[Union[BaseEvent, Dict[str, Any]], None]:
        """Stream events from the underlying LogAIAgent."""
        from backend.ai.logai_agent import LogAIAgent  # Local import

        if not isinstance(agent_input_data, str):
            raise TypeError(
                f"LogAIStepAgent expects description string, got {type(agent_input_data)}"
            )

        # Lazy init underlying agent
        if self.log_ai_generator is None:
            ai_logger.info("Lazily initialising LogAIAgent for log-ai steps.")
            self.log_ai_generator = LogAIAgent(
                notebook_id=self.notebook_id, notebook_manager=self.notebook_manager
            )

        user_description: str = agent_input_data
        ai_logger.info(
            f"Processing Log-AI step {step.step_id} (session {session_id}) …"
        )

        async for event in self.log_ai_generator.run_query(
            user_query=user_description, session_id=session_id
        ):
            # Forward only recognised BaseEvent subclasses – Tool/Status/Fatal etc.
            # Unknown objects (e.g. raw results) are passed as final_step_result dict.
            from backend.ai.events import BaseEvent, FinalStatusEvent

            if isinstance(event, (ToolSuccessEvent, ToolErrorEvent, StatusUpdateEvent, FatalErrorEvent)):
                ai_logger.info(f"Log-AI event: {event}")
                yield event
            elif isinstance(event, FinalStatusEvent):
                ai_logger.info(
                    f"Log-AI query finished for step {step.step_id} with status: {event.status}"
                )
            elif isinstance(event, BaseEvent):
                ai_logger.warning(
                    f"Unexpected BaseEvent type {type(event)} from LogAIAgent: {event!r}"
                )
            else:
                yield {"type": "final_step_result", "result": event}

        from backend.ai.events import LogAIToolCellCreatedEvent
