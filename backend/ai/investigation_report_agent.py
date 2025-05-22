"""
Investigation Report Agent Service

Agent for synthesizing investigation findings into a structured InvestigationReport.
"""

import logging
import os
from typing import Optional, AsyncGenerator, Union, Any, TYPE_CHECKING, List

from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.providers.openai import OpenAIProvider

from backend.ai.models import InvestigationStepModel, SafeOpenAIModel
from backend.config import get_settings
from backend.core.query_result import InvestigationReport
from backend.ai.events import (
    AgentType,
    StatusType,
    StatusUpdateEvent,
)
if TYPE_CHECKING:
    from backend.services.notebook_manager import NotebookManager
from backend.ai.notebook_context_tools import create_notebook_context_tools

investigation_report_agent_logger = logging.getLogger("ai.investigation_report_agent")

class InvestigationReportAgent:
    """Agent for generating structured investigation reports."""
    def __init__(self, notebook_id: str, notebook_manager: Optional['NotebookManager'] = None, mcp_servers: Optional[List[Any]] = None):
        investigation_report_agent_logger.info(f"Initializing InvestigationReportAgent for notebook_id: {notebook_id}")
        self.settings = get_settings()
        self.notebook_id = notebook_id
        self.notebook_manager = notebook_manager
        self.mcp_servers = mcp_servers or []
        self.agent: Optional[Agent] = None
        investigation_report_agent_logger.info(f"InvestigationReportAgent initialized successfully with {len(self.mcp_servers)} MCP servers.")

    def _read_system_prompt(self) -> str:
        """Reads the system prompt from the dedicated file."""
        prompt_file_path = os.path.join(os.path.dirname(__file__), "prompts", "investigation_report_agent_system_prompt.txt")
        try:
            with open(prompt_file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            investigation_report_agent_logger.error(f"System prompt file not found at: {prompt_file_path}")
            return "You are an AI assistant. Analyze the provided findings and generate a structured JSON report matching the InvestigationReport schema."
        except Exception as e:
            investigation_report_agent_logger.error(f"Error reading system prompt file {prompt_file_path}: {e}", exc_info=True)
            return "You are an AI assistant. Analyze the provided findings and generate a structured JSON report matching the InvestigationReport schema."

    def _initialize_agent(self) -> Agent:
        """Initializes the Pydantic AI Agent for report generation."""
        system_prompt = self._read_system_prompt()

        tools = []
        if self.notebook_manager:
            tools = create_notebook_context_tools(self.notebook_id, self.notebook_manager)
            investigation_report_agent_logger.info(f"Notebook context tools ({[tool.__name__ for tool in tools]}) created for InvestigationReportAgent.")

        agent = Agent[None, InvestigationReport](
            model=SafeOpenAIModel(
                "openai/gpt-4.1",
                provider=OpenAIProvider(
                    base_url='https://openrouter.ai/api/v1',
                    api_key=self.settings.openrouter_api_key,
                ),
            ),
            output_type=InvestigationReport,
            system_prompt=system_prompt,
            tools=tools,
            mcp_servers=self.mcp_servers
        )
        return agent # type: ignore

    async def run_report_generation(
        self,
        step: InvestigationStepModel,
        context: str,
        session_id: str,
        notebook_id: str
    ) -> AsyncGenerator[Union[StatusUpdateEvent, InvestigationReport], None]:
        """Generate an InvestigationReport from findings, yielding status updates."""
        
        reporter_agent_type = AgentType.INVESTIGATION_REPORTER 
        yield StatusUpdateEvent(status=StatusType.STARTING, agent_type=reporter_agent_type, message="Initializing report generation...", step_id="final_report", attempt=None, max_attempts=None, reason=None, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)
        
        try:
            if not self.agent:
                 self.agent = self._initialize_agent()
        except Exception as init_err:
            error_msg = f"Failed to initialize InvestigationReportAgent: {init_err}"
            investigation_report_agent_logger.error(error_msg, exc_info=True)
            yield StatusUpdateEvent(status=StatusType.ERROR, agent_type=reporter_agent_type, message=error_msg, reason="Initialization failed", step_id="final_report", attempt=None, max_attempts=None, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)
            return

        max_attempts = 2
        last_error = None
        final_report_data: Optional[InvestigationReport] = None
        
        input_prompt = f"""
            <prompt>
                <description>{step.description}</description>
                <parameters>{step.parameters}</parameters>
            </prompt>

            <context>
                {context}
            </context>
        """
 
        yield StatusUpdateEvent(status=StatusType.STARTING_ATTEMPTS, agent_type=reporter_agent_type, message=f"Attempting report generation (max {max_attempts} attempts)...", max_attempts=max_attempts, step_id="final_report", attempt=None, reason=None, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)

        for attempt in range(max_attempts):
            current_attempt = attempt + 1
            investigation_report_agent_logger.info(f"Report Generation Attempt {current_attempt}/{max_attempts}")
            yield StatusUpdateEvent(status=StatusType.ATTEMPT_START, agent_type=reporter_agent_type, attempt=current_attempt, max_attempts=max_attempts, step_id="final_report", message=f"Starting attempt {current_attempt}", reason=None, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)

            try:
                run_result_obj = await self.agent.run(input_prompt)
                investigation_report_agent_logger.info(f"Attempt {current_attempt}: Raw agent result object: {run_result_obj!r}")
                
                run_result = run_result_obj.output

                if isinstance(run_result, InvestigationReport):
                    yield run_result
                    return
                else:
                    error_msg = f"Agent run attempt {current_attempt} produced invalid result type: {type(run_result)}. Expected InvestigationReport."
                    investigation_report_agent_logger.error(error_msg + f" Raw result: {run_result!r}")
                    last_error = "Agent failed to produce the required structured report format."
                    yield StatusUpdateEvent(status=StatusType.MODEL_ERROR, agent_type=reporter_agent_type, message=last_error, reason="Invalid output format", attempt=current_attempt, step_id="final_report", max_attempts=max_attempts, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id) 

            except UnexpectedModelBehavior as e:
                investigation_report_agent_logger.error(f"UnexpectedModelBehavior during report generation attempt {current_attempt}: {e}", exc_info=True)
                last_error = f"Report generation failed due to unexpected model behavior: {str(e)}"
                yield StatusUpdateEvent(status=StatusType.MODEL_ERROR, agent_type=reporter_agent_type, message=last_error, reason="Unexpected model behavior", attempt=current_attempt, step_id="final_report", max_attempts=max_attempts, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id) 
            
            except Exception as e:
                investigation_report_agent_logger.error(f"General error during report generation attempt {current_attempt}: {e}", exc_info=True)
                last_error = f"Report generation failed unexpectedly: {str(e)}"
                yield StatusUpdateEvent(status=StatusType.GENERAL_ERROR_RUN, agent_type=reporter_agent_type, message=last_error, reason="General exception", attempt=current_attempt, step_id="final_report", max_attempts=max_attempts, original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id) 

            if attempt < max_attempts - 1:
                 yield StatusUpdateEvent(status=StatusType.RETRYING, agent_type=reporter_agent_type, attempt=current_attempt, reason=last_error or "unknown", max_attempts=max_attempts, step_id="final_report", message=f"Retrying after error on attempt {current_attempt}", original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)
            else:
                 investigation_report_agent_logger.error(f"Report generation failed after {max_attempts} attempts.")
                 break

        if final_report_data is None:
            final_error_msg = f"Report generation failed after {max_attempts} attempts. Last error: {last_error or 'Unknown failure'}"
            investigation_report_agent_logger.error(final_error_msg)
            yield StatusUpdateEvent(status=StatusType.FINISHED_ERROR, agent_type=reporter_agent_type, message=final_error_msg, attempt=current_attempt, max_attempts=max_attempts, reason=last_error or 'Unknown failure', step_id="final_report", original_plan_step_id=None, session_id=session_id, notebook_id=notebook_id)
