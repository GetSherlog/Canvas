import pytest
import os
from unittest.mock import patch, mock_open, MagicMock
import tempfile

from backend.ai.python_agent import PythonAgent, IMPORTED_DATA_BASE_PATH
from backend.ai.models import FileDataRef

# Make PythonAgent importable for tests by temporarily adding to path if needed,
# or ensure your test runner handles it. For now, assume it's discoverable.

@pytest.fixture
def python_agent_instance(monkeypatch):
    """Fixture to create a PythonAgent instance with mocked settings."""
    # Mock get_settings if it's used in __init__ or methods directly
    mock_settings = MagicMock()
    mock_settings.ai_model = "test_model"
    mock_settings.openrouter_api_key = "test_key"
    
    # If PythonAgent's __init__ takes notebook_id, provide a dummy one.
    # Based on current python_agent.py, it does.
    agent = PythonAgent(notebook_id="test_notebook_id_init") # This notebook_id is for __init__
                                                          # The one in FileDataRef is for path construction.
    
    # If settings are accessed globally via get_settings() in the module, patch that.
    # If they are accessed via self.settings, ensure __init__ sets them up (which it does).
    # monkeypatch.setattr("backend.ai.python_agent.get_settings", lambda: mock_settings)
    return agent

class TestPythonAgentPrepareLocalFile:

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.makedirs")
    @patch("backend.ai.python_agent.uuid.uuid4")
    @patch("builtins.open", new_callable=mock_open)
    async def test_prepare_local_file_success_with_original_filename(
        self, mock_file_open, mock_uuid, mock_makedirs, python_agent_instance
    ):
        mock_uuid.return_value = MagicMock(hex="12345678")
        data_ref = FileDataRef(
            type="content_string",
            value="col1,col2\nval1,val2",
            original_filename="test_data.csv",
            source_cell_id="cell1"
        )
        notebook_id = "nb1"
        session_id = "sess1"

        expected_dir_path = os.path.join(IMPORTED_DATA_BASE_PATH, notebook_id, session_id)
        expected_filename = "test_data_12345678.csv"
        expected_full_path = os.path.join(expected_dir_path, expected_filename)

        result_path = await python_agent_instance._prepare_local_file(data_ref, notebook_id, session_id)

        mock_makedirs.assert_called_once_with(expected_dir_path, exist_ok=True)
        mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
        mock_file_open().write.assert_called_once_with("col1,col2\nval1,val2")
        assert result_path == expected_full_path

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.makedirs")
    @patch("backend.ai.python_agent.uuid.uuid4")
    @patch("builtins.open", new_callable=mock_open)
    async def test_prepare_local_file_success_no_original_filename(
        self, mock_file_open, mock_uuid, mock_makedirs, python_agent_instance
    ):
        mock_uuid.return_value = MagicMock(hex="abcdef01")
        data_ref = FileDataRef(
            type="content_string",
            value="data",
            original_filename=None, # No original filename
            source_cell_id="cell2"
        )
        notebook_id = "nb2"
        session_id = "sess2"

        expected_dir_path = os.path.join(IMPORTED_DATA_BASE_PATH, notebook_id, session_id)
        expected_filename = "dataset_abcdef01.csv" # Default base "dataset"
        expected_full_path = os.path.join(expected_dir_path, expected_filename)

        result_path = await python_agent_instance._prepare_local_file(data_ref, notebook_id, session_id)

        mock_makedirs.assert_called_once_with(expected_dir_path, exist_ok=True)
        mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
        mock_file_open().write.assert_called_once_with("data")
        assert result_path == expected_full_path

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.makedirs")
    @patch("backend.ai.python_agent.uuid.uuid4")
    @patch("builtins.open", new_callable=mock_open)
    async def test_filename_sanitization_and_extension(
        self, mock_file_open, mock_uuid, mock_makedirs, python_agent_instance
    ):
        notebook_id = "nb3" # Define notebook_id and session_id for this test
        session_id = "sess3"
        expected_dir = os.path.join(IMPORTED_DATA_BASE_PATH, notebook_id, session_id)

        # Test case 1: Sanitization of spaces
        mock_uuid.return_value = MagicMock(hex="sanitize") # Reset mock for consistent UUID
        data_ref_simple_sanitize = FileDataRef(
            type="content_string", 
            value="c", 
            original_filename="file with space.csv",
            source_cell_id="cell_sanitize_space"
        )
        expected_simple_sanitized_filename = "file_with_space_sanitize.csv"
        expected_dir = os.path.join(IMPORTED_DATA_BASE_PATH, notebook_id, session_id)
        expected_path_simple = os.path.join(expected_dir, expected_simple_sanitized_filename)

        result_path = await python_agent_instance._prepare_local_file(data_ref_simple_sanitize, notebook_id, session_id)
        assert result_path == expected_path_simple
        mock_file_open.assert_called_with(expected_path_simple, 'w', encoding='utf-8')
        mock_makedirs.assert_any_call(expected_dir, exist_ok=True) # Use assert_any_call if makedirs is called multiple times in test class

        # Test case 2: No extension in original filename
        mock_file_open.reset_mock() # Reset for this sub-test
        mock_makedirs.reset_mock() 
        mock_uuid.return_value = MagicMock(hex="noext")
        data_ref_no_ext = FileDataRef(
            type="content_string", 
            value="c", 
            original_filename="filenoext", # No extension
            source_cell_id="cell_no_ext"
        )
        expected_no_ext_filename = "filenoext_noext.csv" 
        expected_path_no_ext = os.path.join(expected_dir, expected_no_ext_filename)
        result_path_no_ext = await python_agent_instance._prepare_local_file(data_ref_no_ext, notebook_id, session_id)
        assert result_path_no_ext == expected_path_no_ext
        mock_file_open.assert_called_with(expected_path_no_ext, 'w', encoding='utf-8')
        mock_makedirs.assert_any_call(expected_dir, exist_ok=True)

        # Test case 3: Special characters and different extension
        mock_file_open.reset_mock()
        mock_makedirs.reset_mock()
        mock_uuid.return_value = MagicMock(hex="special")
        data_ref_special_ext = FileDataRef(
            type="content_string",
            value="content",
            original_filename="My Data File (Special!).txt", 
            source_cell_id="cell_special_ext"
        )
        # sanitized_name = re.sub(r'[^\w\.-]', '_', "My Data File (Special!).txt") -> "My_Data_File_Special__.txt"
        # name_part, ext_part = os.path.splitext("My_Data_File_Special__.txt") -> ("My_Data_File_Special__", ".txt")
        # ext_part.lower() != ".csv" is true.
        # sanitized_name = name_part + ".csv" -> "My_Data_File__Special__.csv"
        # base_filename = "My_Data_File__Special__.csv"
        # filename = f"{os.path.splitext(base_filename)[0]}_{unique_id}.csv" -> "My_Data_File__Special___special.csv"
        expected_special_ext_filename = "My_Data_File__Special___special.csv" # Corrected: two underscores after "File"
        expected_path_special_ext = os.path.join(expected_dir, expected_special_ext_filename)
        result_path_special_ext = await python_agent_instance._prepare_local_file(data_ref_special_ext, notebook_id, session_id)
        assert result_path_special_ext == expected_path_special_ext
        mock_file_open.assert_called_with(expected_path_special_ext, 'w', encoding='utf-8')
        mock_makedirs.assert_any_call(expected_dir, exist_ok=True)

    @pytest.mark.asyncio
    async def test_prepare_local_file_unsupported_type(self, python_agent_instance):
        data_ref = FileDataRef(
            type="some_unknown_type", 
            value="/path/on/mcp.csv", 
            original_filename="mcp_file.csv", # Optional, but good to include
            source_cell_id="cell_fsmcp_err"
        )
        with pytest.raises(ValueError) as excinfo:
            await python_agent_instance._prepare_local_file(data_ref, "nb_err", "sess_err")
        assert "received unsupported data_ref type 'some_unknown_type'" in str(excinfo.value)

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.path.exists")
    async def test_prepare_local_file_local_staged_path_success(self, mock_os_path_exists, python_agent_instance):
        """Test _prepare_local_file with type 'local_staged_path' successfully."""
        mock_os_path_exists.return_value = True
        staged_file_path = "/tmp/data/imported_datasets/nb_staged/sess_staged/staged_file_abc.csv"
        data_ref = FileDataRef(
            type="local_staged_path",
            value=staged_file_path,
            original_filename="staged_file.csv", # Can be different from value's basename
            source_cell_id="cell_staged"
        )
        notebook_id = "nb_staged" # These are not used for path construction for local_staged_path
        session_id = "sess_staged"

        result_path = await python_agent_instance._prepare_local_file(data_ref, notebook_id, session_id)
        
        assert result_path == staged_file_path
        mock_os_path_exists.assert_called_once_with(staged_file_path)
        # No os.makedirs or file open/write should be called for local_staged_path

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.path.exists")
    async def test_prepare_local_file_local_staged_path_not_exists(self, mock_os_path_exists, python_agent_instance):
        """Test _prepare_local_file with 'local_staged_path' when file doesn't exist."""
        mock_os_path_exists.return_value = False
        non_existent_path = "/tmp/data/imported_datasets/nb_staged/sess_staged/non_existent.csv"
        data_ref = FileDataRef(
            type="local_staged_path",
            value=non_existent_path,
            original_filename="non_existent.csv",
            source_cell_id="cell_staged_err"
        )
        notebook_id = "nb_staged_err"
        session_id = "sess_staged_err"

        with pytest.raises(FileNotFoundError) as excinfo:
            await python_agent_instance._prepare_local_file(data_ref, notebook_id, session_id)
        
        assert f"Local staged file path provided does not exist: {non_existent_path}" in str(excinfo.value)
        mock_os_path_exists.assert_called_once_with(non_existent_path)

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.makedirs")
    async def test_prepare_local_file_makedirs_oserror(self, mock_makedirs, python_agent_instance):
        mock_makedirs.side_effect = OSError("Test makedirs error")
        data_ref = FileDataRef(
            type="content_string", 
            value="content", 
            original_filename="file.csv",
            source_cell_id="cell_os_err"
            )
        
        with pytest.raises(OSError) as excinfo:
            await python_agent_instance._prepare_local_file(data_ref, "nb_os_err", "sess_os_err")
        assert "Test makedirs error" in str(excinfo.value)

    @pytest.mark.asyncio
    @patch("backend.ai.python_agent.os.makedirs") # Mock makedirs to succeed
    @patch("builtins.open", new_callable=mock_open)
    async def test_prepare_local_file_write_ioerror(
        self, mock_file_open, mock_makedirs_success, python_agent_instance
    ):
        mock_file_open.side_effect = IOError("Test write error")
        data_ref = FileDataRef(
            type="content_string", 
            value="content", 
            original_filename="file.csv",
            source_cell_id="cell_io_err"
            )

        with pytest.raises(IOError) as excinfo:
            await python_agent_instance._prepare_local_file(data_ref, "nb_io_err", "sess_io_err")
        assert "Test write error" in str(excinfo.value)

# TODO: Add tests for the main run_query method, mocking _prepare_local_file,
# _get_stdio_server, _initialize_agent, and the agent.iter() flow.
# This will be more involved due to the async generator nature and event yielding.

# --- Tests for _prepare_local_file with direct_host_path ---

@pytest.mark.asyncio
async def test_prepare_local_file_direct_host_path_valid(python_agent_instance):
    """Test _prepare_local_file with a valid, existing direct_host_path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmpfile:
        valid_path = tmpfile.name
    
    data_ref = FileDataRef(
        type="direct_host_path", 
        value=valid_path, 
        original_filename="test.csv", 
        source_cell_id="cell1"
    )
    
    try:
        # No os mocks needed as we created a real temp file for os.path.exists and os.path.isabs
        result_path = await python_agent_instance._prepare_local_file(
            data_ref, notebook_id="test_nb", session_id="test_session"
        )
        assert result_path == valid_path
    finally:
        if os.path.exists(valid_path):
            os.remove(valid_path)

@pytest.mark.asyncio
async def test_prepare_local_file_direct_host_path_non_existent(python_agent_instance):
    """Test _prepare_local_file with a non-existent direct_host_path."""
    non_existent_path = "/absolute/path/that/does/not/exist/file.csv"
    data_ref = FileDataRef(
        type="direct_host_path", 
        value=non_existent_path, 
        original_filename="test.csv", 
        source_cell_id="cell1"
    )
    
    with patch('os.path.isabs', return_value=True), \
         patch('os.path.exists', return_value=False):
        with pytest.raises(FileNotFoundError, match=f"Direct host path '{non_existent_path}' does not exist"):
            await python_agent_instance._prepare_local_file(
                data_ref, notebook_id="test_nb", session_id="test_session"
            )

@pytest.mark.asyncio
async def test_prepare_local_file_direct_host_path_not_absolute(python_agent_instance):
    """Test _prepare_local_file with a non-absolute direct_host_path."""
    relative_path = "relative/path/file.csv"
    data_ref = FileDataRef(
        type="direct_host_path", 
        value=relative_path, 
        original_filename="test.csv", 
        source_cell_id="cell1"
    )
    
    with patch('os.path.isabs', return_value=False):
        with pytest.raises(ValueError, match=f"Direct host path '{relative_path}' provided is not absolute"):
            await python_agent_instance._prepare_local_file(
                data_ref, notebook_id="test_nb", session_id="test_session"
            )

@pytest.mark.asyncio
@patch('backend.ai.python_agent.os.makedirs') # Mock makedirs for content_string
@patch('builtins.open', new_callable=MagicMock) # Mock open for content_string
async def test_prepare_local_file_content_string(mock_open, mock_makedirs, python_agent_instance, tmp_path):
    """Test _prepare_local_file with type content_string."""
    # Override IMPORTED_DATA_BASE_PATH for this test to use pytest's tmp_path
    with patch('backend.ai.python_agent.IMPORTED_DATA_BASE_PATH', str(tmp_path)):
        csv_content = "col1,col2\nval1,val2"
        data_ref = FileDataRef(
            type="content_string", 
            value=csv_content, 
            original_filename="my_data.csv", 
            source_cell_id="cell2"
        )
        
        # Mock the behavior of open().write()
        mock_file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file_handle

        result_path = await python_agent_instance._prepare_local_file(
            data_ref, notebook_id="test_nb_content", session_id="test_session_content"
        )
        
        mock_makedirs.assert_called_once()
        # Path construction: IMPORTED_DATA_BASE_PATH / notebook_id / session_id / filename
        # Check if the path structure is as expected (partially)
        assert str(tmp_path / "test_nb_content" / "test_session_content") in result_path
        assert result_path.endswith(".csv")
        
        # Verify that open was called with the result_path and 'w' mode
        mock_open.assert_called_once_with(result_path, 'w', encoding='utf-8')
        # Verify that content was written
        mock_file_handle.write.assert_called_once_with(csv_content)

# Consider adding a similar test for "local_staged_path" if not already present,
# ensuring it checks for file existence and returns the path.
