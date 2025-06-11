import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.notebook_manager import NotebookManager
from backend.db.repositories import NotebookRepository
from backend.core.notebook import Notebook, Cell
from backend.core.cell import CellType, CellStatus
from backend.db.models import Notebook as DBNotebookModel, Cell as DBCellModel # For mocking repository return

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_db_session():
    """Fixture for a mocked AsyncSession."""
    return AsyncMock(spec=AsyncSession)

@pytest.fixture
def mock_notebook_repo(mock_db_session):
    """Fixture for a mocked NotebookRepository."""
    # The repository is initialized with the session, so pass the mock session
    return MagicMock(spec=NotebookRepository)


@pytest.fixture
def notebook_manager_service(mock_notebook_repo):
    """Fixture for NotebookManager with mocked repository."""
    # Temporarily patch get_settings if NotebookManager constructor uses it directly
    # For this test, we assume NotebookManager doesn't need complex settings for the methods being tested.
    # If it does, those settings would need to be provided or patched.
    # The NotebookManager constructor also takes execution_queue and cell_executor,
    # which are not relevant for get_notebook, so we can pass None.
    manager = NotebookManager(execution_queue=None, cell_executor=None)
    # If NotebookManager relied on a global or complex way to get its repository,
    # we might need to patch that. Here, we assume methods take `db` and instantiate repo locally.
    return manager

async def test_get_notebook_success(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test successfully retrieving a notebook."""
    notebook_id = uuid.uuid4()
    mock_repo_instance = MagicMock(spec=NotebookRepository)

    # Mock the DBNotebookModel object that the repository's get_notebook would return
    mock_db_notebook = DBNotebookModel(
        id=str(notebook_id),
        title="Test Notebook Title",
        description="Test Notebook Description",
        created_by="test_user",
        tags=["test", "notebook"],
        created_at=MagicMock(), # datetime object
        updated_at=MagicMock(), # datetime object
        cells=[] # Assuming no cells for simplicity in this test
    )
    # Configure the mock repository's get_notebook method
    mock_repo_instance.get_notebook = AsyncMock(return_value=mock_db_notebook)

    # Patch the NotebookRepository instantiation within the manager's method
    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        notebook = await notebook_manager_service.get_notebook(mock_db_session, notebook_id)

    MockRepoClass.assert_called_once_with(mock_db_session)
    mock_repo_instance.get_notebook.assert_called_once_with(str(notebook_id))

    assert isinstance(notebook, Notebook)
    assert notebook.id == notebook_id
    assert notebook.metadata.title == "Test Notebook Title"
    assert notebook.metadata.description == "Test Notebook Description"
    assert notebook.metadata.created_by == "test_user"
    assert notebook.metadata.tags == ["test", "notebook"]
    assert len(notebook.cells) == 0


async def test_get_notebook_not_found(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test retrieving a notebook that does not exist."""
    notebook_id = uuid.uuid4()
    mock_repo_instance = MagicMock(spec=NotebookRepository)
    mock_repo_instance.get_notebook = AsyncMock(return_value=None) # Simulate notebook not found

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance):
        with pytest.raises(KeyError) as excinfo:
            await notebook_manager_service.get_notebook(mock_db_session, notebook_id)
    
    assert str(notebook_id) in str(excinfo.value)
    mock_repo_instance.get_notebook.assert_called_once_with(str(notebook_id))

# Example test for create_notebook (can be expanded)
async def test_create_notebook_success(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test successfully creating a notebook."""
    notebook_name = "New Test Notebook"
    notebook_desc = "Description for new notebook"
    notebook_id_created = uuid.uuid4() # ID that will be assigned by the mocked repo

    mock_repo_instance = MagicMock(spec=NotebookRepository)

    # Mock the DBNotebookModel object that repository's create_notebook would return
    mock_db_notebook_created = DBNotebookModel(
        id=str(notebook_id_created),
        title=notebook_name,
        description=notebook_desc,
        created_by=None,
        tags=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
        cells=[]
    )
    mock_repo_instance.create_notebook = AsyncMock(return_value=mock_db_notebook_created)

    # Mock the DBNotebookModel object that repository's get_notebook (called by manager.get_notebook) would return
    # This is because create_notebook in manager calls self.get_notebook after repo.create_notebook
    mock_db_notebook_fetched = DBNotebookModel(
        id=str(notebook_id_created), # Same ID as created
        title=notebook_name,
        description=notebook_desc,
        created_by=None,
        tags=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
        cells=[] # No cells initially
    )
    mock_repo_instance.get_notebook = AsyncMock(return_value=mock_db_notebook_fetched)


    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        created_notebook = await notebook_manager_service.create_notebook(
            db=mock_db_session,
            name=notebook_name,
            description=notebook_desc,
            metadata=None # Or provide some mock metadata
        )

    # Check that NotebookRepository was instantiated twice (once in create_notebook, once in the subsequent get_notebook)
    # Or, if the repo instance is passed around, adjust assertion.
    # Current manager code: instantiates repo in create_notebook, then calls self.get_notebook which also instantiates.
    assert MockRepoClass.call_count == 2 
    
    mock_repo_instance.create_notebook.assert_called_once_with(
        title=notebook_name,
        description=notebook_desc,
        created_by=None, # Based on metadata=None
        tags=[]         # Based on metadata=None
    )
    # get_notebook is called by the manager after creating, to fetch the full model
    mock_repo_instance.get_notebook.assert_called_once_with(str(notebook_id_created))


    assert isinstance(created_notebook, Notebook)
    assert created_notebook.id == notebook_id_created
    assert created_notebook.metadata.title == notebook_name
    assert created_notebook.metadata.description == notebook_desc


async def test_update_cell_content_success(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test successfully updating a cell's content."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    # original_content = "original content"
    new_content = "new updated content"
    
    mock_repo_instance = MagicMock(spec=NotebookRepository)

    # Mock the DB Cell object that repository.update_cell would return
    mock_db_cell_updated = DBCellModel( # Using DBCellModel for Cell model structure
        id=str(cell_id),
        notebook_id=str(notebook_id),
        type=CellType.TOOL.value,
        content=new_content, # Should reflect the new content
        tool_call_id=str(uuid.uuid4()),
        status=CellStatus.IDLE.value,
        created_at=MagicMock(),
        updated_at=MagicMock(),
        dependencies=[] # Mocking dependencies relationship
    )
    mock_repo_instance.update_cell = AsyncMock(return_value=mock_db_cell_updated)

    # Mock mark_dependents_stale and notify_callback
    notebook_manager_service.mark_dependents_stale = AsyncMock(return_value=set())
    notebook_manager_service.notify_callback = AsyncMock()

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        updated_cell = await notebook_manager_service.update_cell_content(
            db=mock_db_session,
            notebook_id=notebook_id,
            cell_id=cell_id,
            content=new_content
        )

    MockRepoClass.assert_called_once_with(mock_db_session)
    mock_repo_instance.update_cell.assert_called_once_with(
        cell_id=str(cell_id),
        updates={'content': new_content}
    )
    
    assert isinstance(updated_cell, Cell)
    assert updated_cell.id == cell_id
    assert updated_cell.content == new_content # Key assertion

    notebook_manager_service.mark_dependents_stale.assert_called_once_with(mock_db_session, notebook_id, cell_id)
    notebook_manager_service.notify_callback.assert_called_once()
    # Can add more specific assertions for notify_callback arguments if needed


async def test_update_cell_content_cell_not_found(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test updating content for a cell that does not exist."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    new_content = "new content"

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    mock_repo_instance.update_cell = AsyncMock(return_value=None) # Simulate cell not found by repo update

    notebook_manager_service.mark_dependents_stale = AsyncMock()
    notebook_manager_service.notify_callback = AsyncMock()

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance):
        with pytest.raises(KeyError) as excinfo:
            await notebook_manager_service.update_cell_content(
                db=mock_db_session,
                notebook_id=notebook_id,
                cell_id=cell_id,
                content=new_content
            )
            
    assert str(cell_id) in str(excinfo.value) # Check if cell_id is in the error message
    mock_repo_instance.update_cell.assert_called_once_with(
        cell_id=str(cell_id),
        updates={'content': new_content}
    )
    notebook_manager_service.mark_dependents_stale.assert_not_called()
    notebook_manager_service.notify_callback.assert_not_called()


async def test_delete_cell_success(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test successfully deleting a cell."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    # delete_cell in repository returns True on success
    mock_repo_instance.delete_cell = AsyncMock(return_value=True)

    notebook_manager_service.notify_callback = AsyncMock()

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        await notebook_manager_service.delete_cell(
            db=mock_db_session,
            notebook_id=notebook_id, # notebook_id is used for notification context
            cell_id=cell_id
        )

    MockRepoClass.assert_called_once_with(mock_db_session)
    mock_repo_instance.delete_cell.assert_called_once_with(str(cell_id))
    
    notebook_manager_service.notify_callback.assert_called_once_with(
        notebook_id, 
        {"id": str(cell_id), "deleted": True}
    )


async def test_delete_cell_not_found(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test deleting a cell that does not exist."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    # delete_cell in repository returns False if cell not found to delete
    mock_repo_instance.delete_cell = AsyncMock(return_value=False)

    notebook_manager_service.notify_callback = AsyncMock()

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance):
        with pytest.raises(KeyError) as excinfo:
            await notebook_manager_service.delete_cell(
                db=mock_db_session,
                notebook_id=notebook_id,
                cell_id=cell_id
            )
            
    assert str(cell_id) in str(excinfo.value) # Check if cell_id is in the error message
    mock_repo_instance.delete_cell.assert_called_once_with(str(cell_id))
    notebook_manager_service.notify_callback.assert_not_called()


@pytest.fixture
def mock_execution_queue():
    return AsyncMock()

@pytest.fixture
def mock_cell_executor():
    return AsyncMock()

@pytest.fixture
def notebook_manager_with_queue(mock_execution_queue, mock_cell_executor):
    """Fixture for NotebookManager with mocked execution queue and executor."""
    manager = NotebookManager(execution_queue=mock_execution_queue, cell_executor=mock_cell_executor)
    return manager


async def test_update_cell_status_success(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test successfully updating a cell's status (not to QUEUED)."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    new_status = CellStatus.RUNNING
    correlation_id_test = "test-correlation-id"

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    mock_db_cell_updated = DBCellModel(
        id=str(cell_id),
        notebook_id=str(notebook_id),
        type=CellType.TOOL.value,
        content="some content",
        tool_call_id=str(uuid.uuid4()),
        status=new_status.value, # Reflects the new status
        created_at=MagicMock(),
        updated_at=MagicMock(),
        dependencies=[]
    )
    mock_repo_instance.update_cell = AsyncMock(return_value=mock_db_cell_updated)
    notebook_manager_service.notify_callback = AsyncMock()

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        await notebook_manager_service.update_cell_status(
            db=mock_db_session,
            notebook_id=notebook_id,
            cell_id=cell_id,
            status=new_status,
            correlation_id=correlation_id_test
        )

    MockRepoClass.assert_called_once_with(mock_db_session)
    mock_repo_instance.update_cell.assert_called_once_with(
        cell_id=str(cell_id),
        updates={'status': new_status.value}
    )
    notebook_manager_service.notify_callback.assert_called_once()
    # Further assert arguments of notify_callback if needed


async def test_update_cell_status_to_queued_adds_to_execution_queue(
    notebook_manager_with_queue: NotebookManager, # Use manager with mocked queue
    mock_db_session: AsyncSession,
    mock_execution_queue: AsyncMock, # Inject the mock queue fixture
    mock_cell_executor: AsyncMock   # Inject the mock executor fixture
    ):
    """Test that updating status to QUEUED adds the cell to the execution queue."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    new_status = CellStatus.QUEUED
    correlation_id_test = "test-correlation-id-queued"

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    mock_db_cell_updated = DBCellModel(
        id=str(cell_id),
        notebook_id=str(notebook_id),
        type=CellType.TOOL.value,
        content="some content",
        tool_call_id=str(uuid.uuid4()),
        status=new_status.value,
        created_at=MagicMock(),
        updated_at=MagicMock(),
        dependencies=[]
    )
    mock_repo_instance.update_cell = AsyncMock(return_value=mock_db_cell_updated)
    
    # Assign mocks to the manager instance directly for notify_callback
    notebook_manager_with_queue.notify_callback = AsyncMock()
    # The execution_queue and cell_executor are already set by the fixture

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance) as MockRepoClass:
        await notebook_manager_with_queue.update_cell_status(
            db=mock_db_session,
            notebook_id=notebook_id,
            cell_id=cell_id,
            status=new_status,
            correlation_id=correlation_id_test
        )

    MockRepoClass.assert_called_once_with(mock_db_session)
    mock_repo_instance.update_cell.assert_called_once_with(
        cell_id=str(cell_id),
        updates={'status': new_status.value}
    )
    
    # Assert that add_cell was called on the execution_queue
    mock_execution_queue.add_cell.assert_called_once_with(
        notebook_id, 
        cell_id, 
        mock_cell_executor # The manager passes its cell_executor instance
    )
    notebook_manager_with_queue.notify_callback.assert_called_once()


async def test_update_cell_status_cell_not_found(notebook_manager_service: NotebookManager, mock_db_session: AsyncSession):
    """Test updating status for a cell that does not exist."""
    notebook_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    new_status = CellStatus.ERROR

    mock_repo_instance = MagicMock(spec=NotebookRepository)
    mock_repo_instance.update_cell = AsyncMock(return_value=None) # Simulate cell not found

    notebook_manager_service.notify_callback = AsyncMock()
    # If execution_queue was involved, ensure it's not called
    # For this test, using the standard notebook_manager_service which has queue=None is fine.

    with patch('backend.services.notebook_manager.NotebookRepository', return_value=mock_repo_instance):
        with pytest.raises(KeyError) as excinfo:
            await notebook_manager_service.update_cell_status(
                db=mock_db_session,
                notebook_id=notebook_id,
                cell_id=cell_id,
                status=new_status
            )
            
    assert str(cell_id) in str(excinfo.value)
    mock_repo_instance.update_cell.assert_called_once_with(
        cell_id=str(cell_id),
        updates={'status': new_status.value}
    )
    notebook_manager_service.notify_callback.assert_not_called()
