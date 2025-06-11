import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY as AnyMock # Import ANY
from uuid import uuid4, UUID # Import UUID

from backend.ai.agent import AIAgent
from backend.ai.models import InvestigationPlanModel, InvestigationStepModel, StepType
from backend.ai.events import StepExecutionCompleteEvent, StepStartedEvent, PlanCreatedEvent, InvestigationCompleteEvent
from backend.core.notebook import Notebook # Added import

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_notebook_manager():
    manager = MagicMock()
    # Mock the get_notebook method to return an AsyncMock that resolves to a Notebook instance
    mock_notebook_instance = MagicMock(spec=Notebook)
    mock_notebook_instance.id = uuid4() # Give it a UUID
    manager.get_notebook = AsyncMock(return_value=mock_notebook_instance)
    manager.save_notebook = AsyncMock() # Mock save_notebook as well
    return manager

@pytest.fixture
def mock_connection_manager():
    return MagicMock()

@pytest.fixture
def mock_step_processor():
    processor = MagicMock()
    # Make process_step an async generator
    async def mock_process_step_gen(*args, **kwargs):
        step_being_processed = kwargs.get('step') or (args[0] if args else None)
        if step_being_processed:
            # Yield a StepExecutionCompleteEvent for the step being processed
            # Provide all required fields for StepExecutionCompleteEvent
            yield StepExecutionCompleteEvent(
                step_id=step_being_processed.step_id,
                notebook_id=str(uuid4()),
                session_id=str(uuid4()), # Added
                final_result_data=None,   # Added
                step_error=None,          # Added
                github_step_has_tool_errors=False, # Added
                filesystem_step_has_tool_errors=False, # Added
                python_step_has_tool_errors=False, # Added
                step_outputs=None         # Added
            )
        # Keep it simple, just yield one event to signify completion for the test's purpose
        # For more complex tests, this mock would need to be more sophisticated

    processor.process_step = mock_process_step_gen
    return processor

@pytest.fixture
def mock_cell_tools():
    tools = MagicMock()
    tools.create_cell = AsyncMock(return_value={"cell_id": str(uuid4())})
    return tools

async def test_investigate_step_dependency_resolution(
    mock_notebook_manager, mock_connection_manager, mock_step_processor, mock_cell_tools
):
    """
    Tests that a step dependent on another step is executed after the dependency is met.
    """
    notebook_id = str(uuid4())
    session_id = str(uuid4())
    
    # Create an AIAgent instance with mocks
    # Patch the StepProcessor instantiation within AIAgent
    with patch('backend.ai.agent.StepProcessor', return_value=mock_step_processor):
        ai_agent = AIAgent(
            notebook_id=notebook_id,
            available_data_sources=["markdown"],
            notebook_manager=mock_notebook_manager,
            connection_manager=mock_connection_manager
        )

    # Define a simple two-step plan
    step1_id = "step_1_markdown"
    step2_id = "step_2_markdown"
    test_plan = InvestigationPlanModel(
        steps=[
            InvestigationStepModel(step_id=step1_id, step_type=StepType.MARKDOWN, description="First step", dependencies=[]),
            InvestigationStepModel(step_id=step2_id, step_type=StepType.MARKDOWN, description="Second step", dependencies=[step1_id]),
        ],
        thinking="Test plan for dependency resolution.",
        hypothesis="If step 1 completes, step 2 should run."
    )

    # Mock create_investigation_plan to return our test plan
    ai_agent.create_investigation_plan = AsyncMock(return_value=test_plan)
    
    # Mock _get_step_summary_content to avoid issues with None results if StepResult isn't fully mocked
    ai_agent._get_step_summary_content = MagicMock(return_value="Mocked summary content")


    # Collect events from the investigate method
    collected_events = []
    async for event in ai_agent.investigate(
        query="Test query for dependency", 
        session_id=session_id, 
        notebook_id=notebook_id,
        cell_tools=mock_cell_tools
    ):
        collected_events.append(event)

    # Assertions
    # Check for PlanCreatedEvent
    assert any(isinstance(event, PlanCreatedEvent) for event in collected_events), "PlanCreatedEvent not found"

    # Check that StepStartedEvent was yielded for both steps
    step_started_ids = [event.step_id for event in collected_events if isinstance(event, StepStartedEvent)]
    assert step1_id in step_started_ids, f"{step1_id} did not start"
    assert step2_id in step_started_ids, f"{step2_id} did not start, dependency likely not resolved"
    
    # Ensure step_1 started before step_2
    step1_start_index = -1
    step2_start_index = -1
    for i, event in enumerate(collected_events):
        if isinstance(event, StepStartedEvent):
            if event.step_id == step1_id and step1_start_index == -1:
                step1_start_index = i
            elif event.step_id == step2_id and step2_start_index == -1:
                step2_start_index = i
    
    assert step1_start_index != -1, "Step 1 never started (based on index)"
    assert step2_start_index != -1, "Step 2 never started (based on index)"
    assert step1_start_index < step2_start_index, "Step 1 did not start before Step 2"

    # Check for InvestigationCompleteEvent
    assert any(isinstance(event, InvestigationCompleteEvent) for event in collected_events), "InvestigationCompleteEvent not found"

    # Verify that StepProcessor.process_step was called for both steps
    # This is a bit more involved due to how mock_calls stores args/kwargs
    process_step_calls = mock_step_processor.process_step.mock_calls
    
    # Check call for step1
    step1_called = False
    for call in process_step_calls:
        # call is a tuple: (name, args, kwargs)
        # We need to check kwargs['step'].step_id
        if 'step' in call.kwargs and call.kwargs['step'].step_id == step1_id:
            step1_called = True
            break
    assert step1_called, f"StepProcessor.process_step not called for {step1_id}"

    # Check call for step2
    step2_called = False
    for call in process_step_calls:
        if 'step' in call.kwargs and call.kwargs['step'].step_id == step2_id:
            step2_called = True
            break
    assert step2_called, f"StepProcessor.process_step not called for {step2_id}"

    # Ensure NotebookManager.get_notebook was called
    mock_notebook_manager.get_notebook.assert_called_once_with(db=AnyMock, notebook_id=UUID(notebook_id)) # Use AnyMock

    # Ensure NotebookManager.save_notebook was called
    mock_notebook_manager.save_notebook.assert_called_once()
