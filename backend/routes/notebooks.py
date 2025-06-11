"""
Notebook API Endpoints
"""

import logging
import asyncio # Added for asyncio.wait_for
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone

import json # Added for parsing incoming WebSocket messages
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel, ValidationError # Added for Pydantic validation
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.cell import CellType, CellStatus, CellResult
from backend.core.types import ToolCallID
from backend.services.notebook_manager import NotebookManager, get_notebook_manager
from backend.db.database import get_async_db_session
# Import specific message types and payloads
from backend.websockets import WebSocketManager, RERUN_INVESTIGATION_CELL, RerunInvestigationCellPayload
from backend.db.repositories import NotebookRepository

# Initialize logger
route_logger = logging.getLogger("api.routes.notebooks")

# Add correlation ID filter to the route logger
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

route_logger.addFilter(CorrelationIdFilter())

router = APIRouter()

# Dependency for WebSocket manager
# ws_dep: Callable[..., WebSocketManager] = Depends(get_ws_manager)


class NotebookCreate(BaseModel):
    """Parameters for creating a notebook"""
    title: str
    description: Optional[str] = None
    metadata: Optional[Dict] = None


class NotebookUpdate(BaseModel):
    """Parameters for updating a notebook"""
    title: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict] = None


class CellCreate(BaseModel):
    """Parameters for creating a cell"""
    cell_type: CellType
    content: str = ""
    position: Optional[int] = None
    metadata: Optional[Dict] = None
    settings: Optional[Dict] = None
    connection_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None


class CellUpdate(BaseModel):
    """Parameters for updating a cell"""
    content: Optional[str] = None
    metadata: Optional[Dict] = None
    settings: Optional[Dict] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None


class CellReorder(BaseModel):
    """Parameters for reordering cells"""
    cell_order: List[str]  # List of cell IDs (as strings) in the new order


class CellExecutionRequest(BaseModel):
    """Request body for cell execution, allowing content/args update"""
    content: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None


class ToolCellCreate(BaseModel):
    """Parameters for creating a cell from a tool call"""
    tool_name: str
    tool_args: Dict[str, Any] = {}
    result: Optional[Any] = None
    error: Optional[str] = None
    agent_type: str = "unknown"
    metadata: Optional[Dict] = None


@router.get("/")
async def list_notebooks(
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> List[Dict]:
    """
    Get a list of all notebooks
    
    Returns:
        List of notebook metadata
    """
    route_logger.info("Listing all notebooks")
    notebooks = await notebook_manager.list_notebooks(db)
    route_logger.info(f"Found {len(notebooks)} notebooks")
    return [nb.model_dump() for nb in notebooks]


@router.post("/", status_code=201)
async def create_notebook(
    notebook_data: NotebookCreate,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Create a new notebook
    
    Args:
        notebook_data: Parameters for creating the notebook
        
    Returns:
        The created notebook data
    """
    route_logger.info(f"Creating new notebook with title: {notebook_data.title}")
    try:
        notebook = await notebook_manager.create_notebook(
            db=db,
            name=notebook_data.title,
            description=notebook_data.description,
            metadata=notebook_data.metadata
        )
        route_logger.info(f"Created notebook with ID: {notebook.id}")
        return notebook.model_dump()
    except Exception as e:
        route_logger.error(f"Error creating notebook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create notebook")


@router.get("/{notebook_id}")
async def get_notebook(
    notebook_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Get a notebook by ID
    
    Args:
        notebook_id: The ID of the notebook
        
    Returns:
        The notebook data
    """
    route_logger.info(f"Fetching notebook with ID: {notebook_id}")
    try:
        notebook = await notebook_manager.get_notebook(db, notebook_id)
        route_logger.info(f"Successfully retrieved notebook: {notebook_id}")
        return notebook.model_dump()
    except KeyError:
        route_logger.error(f"Notebook not found: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except Exception as e:
        route_logger.error(f"Error fetching notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch notebook")


@router.put("/{notebook_id}")
async def update_notebook(
    notebook_id: UUID,
    notebook_data: NotebookUpdate,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Update a notebook
    
    Args:
        notebook_id: The ID of the notebook
        notebook_data: Parameters for updating the notebook
        
    Returns:
        The updated notebook data
    """
    route_logger.info(f"Updating notebook: {notebook_id}")
    try:
        notebook = await notebook_manager.get_notebook(db, notebook_id)
        
        # Update fields if provided
        if notebook_data.title is not None:
            route_logger.info(f"Updating notebook title to: {notebook_data.title}")
            notebook.metadata.title = notebook_data.title
        
        if notebook_data.description is not None:
            route_logger.info("Updating notebook description")
            notebook.metadata.description = notebook_data.description
        
        if notebook_data.metadata is not None:
            route_logger.info("Updating notebook metadata")
            for key, value in notebook_data.metadata.items():
                if hasattr(notebook.metadata, key):
                    setattr(notebook.metadata, key, value)
        
        # Save the notebook
        await notebook_manager.save_notebook(db=db, notebook_id=notebook_id, notebook=notebook)
        route_logger.info(f"Successfully updated notebook: {notebook_id}")
        
        return notebook.model_dump()
    except KeyError:
        route_logger.error(f"Notebook not found for update: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except Exception as e:
        route_logger.error(f"Error updating notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update notebook")


@router.delete("/{notebook_id}", status_code=204)
async def delete_notebook(
    notebook_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> None:
    """
    Delete a notebook
    
    Args:
        notebook_id: The ID of the notebook
    """
    route_logger.info(f"Deleting notebook: {notebook_id}")
    try:
        await notebook_manager.delete_notebook(db, notebook_id)
        route_logger.info(f"Successfully deleted notebook: {notebook_id}")
    except KeyError:
        route_logger.error(f"Notebook not found for deletion: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except Exception as e:
        route_logger.error(f"Error deleting notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete notebook")


@router.post("/{notebook_id}/cells", response_model=Dict)
async def create_cell(
    notebook_id: UUID,
    cell_data: CellCreate,
    tool_call_id: Optional[ToolCallID] = None,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Create a new cell in a notebook
    
    Args:
        notebook_id: The ID of the notebook
        cell_data: Parameters for creating the cell
        
    Returns:
        The created cell data
    """
    route_logger.info(f"Creating new cell in notebook: {notebook_id} with type {cell_data.cell_type}")
    
    # If client did not provide a tool_call_id, generate one automatically
    if tool_call_id is None:
        tool_call_id = uuid4()
        route_logger.debug(f"Generated new tool_call_id {tool_call_id} for cell creation request.")
    
    try:
        cell = await notebook_manager.create_cell(
            db=db,
            notebook_id=notebook_id,
            cell_type=cell_data.cell_type,
            content=cell_data.content,
            tool_call_id=tool_call_id,
            position=cell_data.position,
            connection_id=cell_data.connection_id,  # Pass through if provided, but not required
            metadata=cell_data.metadata,
            settings=cell_data.settings
        )
        
        # Fetch the notebook state after cell creation to pass to save_notebook
        notebook = await notebook_manager.get_notebook(db, notebook_id)
        # Save the notebook
        await notebook_manager.save_notebook(db=db, notebook_id=notebook_id, notebook=notebook)
        route_logger.info(f"Created cell {cell.id} in notebook {notebook_id}")
        
        return cell.model_dump()
    except KeyError:
        route_logger.error(f"Notebook not found for cell creation: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except ValueError as e:
        route_logger.error(f"Invalid data for cell creation in notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        route_logger.error(f"Error creating cell in notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create cell")


@router.get("/{notebook_id}/cells", response_model=List[Dict])
async def list_cells(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_async_db_session)
) -> List[Dict]:
    """
    List all cells in a notebook
    
    Args:
        notebook_id: The ID of the notebook
        
    Returns:
        List of cell data
    """
    route_logger.info(f"Listing cells for notebook: {notebook_id}")
    try:
        repository = NotebookRepository(db)
        
        # Await the async repository method
        db_cells = await repository.list_cells_by_notebook(str(notebook_id))
        
        # Manually convert Cell model attributes to dictionary
        # Assuming necessary attributes exist on the SQLAlchemy Cell model
        cells_data = []
        for cell in db_cells:
            # Corrected: Explicit None checks for defaulting
            result_dict = None
            if cell.result_content is not None or cell.result_error is not None:
                 result_timestamp = cell.result_timestamp if cell.result_timestamp is not None else cell.updated_at
                 result_timestamp = result_timestamp if result_timestamp is not None else datetime.now(timezone.utc)
                 result_dict = {
                      "content": cell.result_content,
                      "error": cell.result_error,
                      "execution_time": cell.result_execution_time if cell.result_execution_time is not None else 0.0,
                      "timestamp": result_timestamp.isoformat()
                 }

            # Use getattr for relationship access just in case it's not loaded
            dependencies_list = getattr(cell, 'dependencies', [])
            dependency_ids = [str(dep.id) for dep in dependencies_list if hasattr(dep, 'id')]
            
            created_at_ts = cell.created_at if cell.created_at is not None else datetime.now(timezone.utc)
            updated_at_ts = cell.updated_at if cell.updated_at is not None else datetime.now(timezone.utc)

            cells_data.append({
                "id": str(cell.id),
                "notebook_id": str(cell.notebook_id),
                "type": cell.type,
                "content": cell.content if cell.content is not None else "",
                "tool_call_id": str(cell.tool_call_id) if cell.tool_call_id is not None else None,
                "tool_name": cell.tool_name,
                "tool_arguments": cell.tool_arguments if cell.tool_arguments is not None else {},
                "connection_id": cell.connection_id,
                "status": cell.status if cell.status is not None else CellStatus.IDLE.value,
                "dependencies": dependency_ids,
                "result": result_dict,
                "metadata": cell.cell_metadata if cell.cell_metadata is not None else {},
                "settings": cell.settings if cell.settings is not None else {},
                "created_at": created_at_ts.isoformat(),
                "updated_at": updated_at_ts.isoformat(),
                "position": cell.position
            })
            
        route_logger.info(f"Found {len(cells_data)} cells in notebook {notebook_id}")
        return cells_data
    except Exception as e:
        route_logger.error(f"Error listing cells for notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list cells")


@router.get("/{notebook_id}/cells/{cell_id}", response_model=Dict)
async def get_cell(
    notebook_id: UUID,
    cell_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Get a specific cell from a notebook
    
    Args:
        notebook_id: The ID of the notebook
        cell_id: The ID of the cell
        
    Returns:
        The cell data
    """
    route_logger.info(f"Fetching cell {cell_id} from notebook {notebook_id}")
    try:
        cell = await notebook_manager.get_cell(db, notebook_id, cell_id)
        route_logger.info(f"Cell fetched successfully: {cell_id}")
        return cell.model_dump()
    except KeyError:
        route_logger.error(f"Cell {cell_id} not found in notebook {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Cell {cell_id} not found in notebook {notebook_id}")
    except Exception as e:
        route_logger.error(f"Error fetching cell {cell_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch cell")


@router.put("/{notebook_id}/cells/{cell_id}")
async def update_cell(
    notebook_id: UUID,
    cell_id: UUID,
    cell_data: CellUpdate,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Update a cell in a notebook
    
    Args:
        notebook_id: The ID of the notebook
        cell_id: The ID of the cell
        cell_data: Parameters for updating the cell
        
    Returns:
        The updated cell data
    """
    route_logger.info(f"Updating cell {cell_id} in notebook {notebook_id}")
    try:
        # Ensure cell exists, will raise 404 if not.
        # This initial get_cell is mostly for the 404 check if no updates are made,
        # or as a base if update_cell_content isn't called.
        final_cell_state_model = await notebook_manager.get_cell(db, notebook_id, cell_id) 

        # Ensure cell exists, will raise 404 if not.
        current_cell_state = await notebook_manager.get_cell(db, notebook_id, cell_id)
        
        updates_for_repo: Dict[str, Any] = {}

        if cell_data.content is not None:
            if cell_data.content:  # Check for non-empty string
                route_logger.info(f"Updating content for cell {cell_id} to: '{cell_data.content[:100]}...'") # Log new content (truncated for brevity)
                updates_for_repo['content'] = cell_data.content
            else:  # This means cell_data.content == ""
                route_logger.info(f"Received empty string for content update for cell {cell_id}. Existing content will be preserved.")
        # If cell_data.content is None, it means the client didn't intend to update content, so we do nothing.
        
        if cell_data.metadata is not None:
            route_logger.info(f"Updating cell_metadata for cell {cell_id}")
            updates_for_repo['cell_metadata'] = cell_data.metadata

        if cell_data.settings is not None:
            route_logger.info(f"Updating settings for cell {cell_id}")
            updates_for_repo['settings'] = cell_data.settings

        if cell_data.tool_name is not None:
            route_logger.info(f"Updating tool_name for cell {cell_id}")
            updates_for_repo['tool_name'] = cell_data.tool_name
        
        if cell_data.tool_arguments is not None:
            route_logger.info(f"Updating tool_arguments for cell {cell_id}")
            updates_for_repo['tool_arguments'] = cell_data.tool_arguments

        if updates_for_repo:
            await notebook_manager.update_cell_fields(db, notebook_id, cell_id, updates_for_repo)
            # Re-fetch the cell state after updates to ensure the returned data is fresh
            final_cell_state_model = await notebook_manager.get_cell(db, notebook_id, cell_id)
        else:
            # No actual updates were provided, return the current state
            final_cell_state_model = current_cell_state
        
        route_logger.info(f"Successfully processed update for cell {cell_id} and returning fresh state.")
        return final_cell_state_model.model_dump()
    except KeyError:
        route_logger.error(f"Cell {cell_id} not found for update in notebook {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Cell {cell_id} not found in notebook {notebook_id}")
    except Exception as e:
        route_logger.error(f"Error updating cell {cell_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update cell")


@router.delete("/{notebook_id}/cells/{cell_id}", status_code=204)
async def delete_cell(
    notebook_id: UUID,
    cell_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> None:
    """
    Delete a cell from a notebook
    
    Args:
        notebook_id: The ID of the notebook
        cell_id: The ID of the cell
    """
    route_logger.info(f"Deleting cell {cell_id} from notebook {notebook_id}")
    try:
        await notebook_manager.delete_cell(db, notebook_id, cell_id)
        route_logger.info(f"Successfully deleted cell {cell_id}")
    except KeyError:
        route_logger.error(f"Cell {cell_id} not found for deletion in notebook {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Cell {cell_id} not found in notebook {notebook_id}")
    except Exception as e:
        route_logger.error(f"Error deleting cell {cell_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete cell")


class DependencyCreate(BaseModel):
    """Parameters for creating a dependency between cells"""
    dependent_id: UUID
    dependency_id: UUID


@router.post("/{notebook_id}/dependencies")
async def add_dependency(
    notebook_id: UUID,
    dependency_data: DependencyCreate,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Add a dependency relationship between cells
    
    Args:
        notebook_id: The ID of the notebook
        dependency_data: The dependency relationship to add
        
    Returns:
        Success message
    """
    route_logger.info(f"Adding dependency in notebook {notebook_id}: {dependency_data.dependent_id} -> {dependency_data.dependency_id}")
    try:
        notebook = await notebook_manager.get_notebook(db, notebook_id)
        await notebook_manager.add_dependency(
            db=db,
            notebook_id=notebook_id,
            dependent_id=dependency_data.dependent_id,
            dependency_id=dependency_data.dependency_id
        )
        
        # Save the notebook
        await notebook_manager.save_notebook(db=db, notebook_id=notebook_id, notebook=notebook)
        route_logger.info("Successfully added dependency")
        
        return {
            "message": "Dependency added successfully",
            "dependent_id": str(dependency_data.dependent_id),
            "dependency_id": str(dependency_data.dependency_id)
        }
    except KeyError:
        route_logger.error(f"Notebook not found: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except ValueError as e:
        route_logger.error(f"Error adding dependency: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{notebook_id}/cells/from-tool", response_model=None)
async def create_cell_from_tool(
    notebook_id: UUID,
    tool_data: ToolCellCreate,
    request: Request,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Create a cell from a tool call result
    
    This endpoint simplifies cell creation by automatically determining
    the cell type based on the tool name and handling all the metadata.
    
    Args:
        notebook_id: The ID of the notebook
        tool_data: Tool call information and result
        
    Returns:
        The created cell
    """
    route_logger.info(f"Creating cell from tool {tool_data.tool_name} in notebook {notebook_id}")
    
    try:
        # All tool calls use the TOOL cell type
        cell_type = CellType.TOOL
        
        # Create metadata combining tool info and custom metadata
        metadata = {
            "tool_name": tool_data.tool_name,
            "agent_type": tool_data.agent_type,
            **(tool_data.metadata or {})
        }
        
        # Create the cell
        cell = await notebook_manager.create_cell(
            db=db,
            notebook_id=notebook_id,
            cell_type=cell_type,
            content=json.dumps(tool_data.tool_args, indent=2) if tool_data.tool_args else "",
            tool_call_id=uuid4(),  # Generate a new tool call ID
            metadata=metadata,
            tool_name=tool_data.tool_name,
            tool_arguments=tool_data.tool_args
        )
        
        # If result is provided, update the cell with it
        if tool_data.result is not None or tool_data.error is not None:
            cell_result = CellResult(
                content=tool_data.result,
                error=tool_data.error,
                execution_time=0.0
            )
            cell.result = cell_result
            cell.status = CellStatus.ERROR if tool_data.error else CellStatus.SUCCESS
            
            # Save the updated cell with result
            await notebook_manager.set_cell_result(
                db=db,
                notebook_id=notebook_id,
                cell_id=cell.id,
                result=cell_result
            )
        
        # Notify via WebSocket if available
        if request and hasattr(request.app.state, 'ws_manager'):
            ws_manager = request.app.state.ws_manager
            await ws_manager.send_message(
                notebook_id=str(notebook_id),
                message={
                    "type": "cell_created",
                    "cell_id": str(cell.id),
                    "notebook_id": str(notebook_id),
                    "tool_name": tool_data.tool_name
                }
            )
        
        route_logger.info(f"Successfully created cell {cell.id} from tool {tool_data.tool_name}")
        
        return {
            "id": str(cell.id),
            "type": cell.type,
            "tool_name": tool_data.tool_name,
            "status": cell.status,
            "created": True
        }
        
    except Exception as e:
        route_logger.error(f"Error creating cell from tool: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create cell from tool: {str(e)}")


@router.delete("/{notebook_id}/dependencies")
async def remove_dependency(
    notebook_id: UUID,
    dependency_data: DependencyCreate,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Remove a dependency relationship between cells
    
    Args:
        notebook_id: The ID of the notebook
        dependency_data: The dependency relationship to remove
        
    Returns:
        Success message
    """
    route_logger.info(f"Removing dependency in notebook {notebook_id}: {dependency_data.dependent_id} -> {dependency_data.dependency_id}")
    try:
        notebook = await notebook_manager.get_notebook(db, notebook_id)
        await notebook_manager.remove_dependency(
            db=db,
            notebook_id=notebook_id,
            dependent_id=dependency_data.dependent_id,
            dependency_id=dependency_data.dependency_id
        )
        
        # Save the notebook
        await notebook_manager.save_notebook(db=db, notebook_id=notebook_id, notebook=notebook)
        route_logger.info("Successfully removed dependency")
        
        return {
            "message": "Dependency removed successfully",
            "dependent_id": str(dependency_data.dependent_id),
            "dependency_id": str(dependency_data.dependency_id)
        }
    except KeyError:
        route_logger.error(f"Notebook not found: {notebook_id}")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except ValueError as e:
        route_logger.error(f"Error removing dependency: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{notebook_id}/cells/{cell_id}/execute")
async def execute_cell(
    notebook_id: UUID,
    cell_id: UUID,
    execution_data: CellExecutionRequest,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Queue a cell for execution, potentially updating its content/args first.
    
    Args:
        notebook_id: The ID of the notebook
        cell_id: The ID of the cell to execute
        execution_data: Optional updated content and/or tool arguments
        
    Returns:
        Status message
    """
    route_logger.info(f"Received request to execute cell {cell_id} in notebook {notebook_id} with execution_data: {execution_data.model_dump_json(indent=2)}")
    DB_OPERATION_TIMEOUT = 10 # seconds
    try:
        # Fetch current cell state to log its type
        route_logger.debug(f"Attempting to get current cell {cell_id} state.")
        current_cell = await asyncio.wait_for(
            notebook_manager.get_cell(db, notebook_id, cell_id),
            timeout=DB_OPERATION_TIMEOUT
        )
        route_logger.info(f"Cell {cell_id} to be executed is of type: {current_cell.type}")

        if execution_data.content is not None or execution_data.tool_arguments is not None:
            route_logger.info(f"Updating cell {cell_id} with provided execution_data before queueing.")
            updates_to_apply = {}
            if execution_data.content is not None:
                updates_to_apply['content'] = execution_data.content
            if execution_data.tool_arguments is not None:
                updates_to_apply['tool_arguments'] = execution_data.tool_arguments
            
            if updates_to_apply:
                try:
                    route_logger.debug(f"Attempting to update cell {cell_id} fields.")
                    await asyncio.wait_for(
                        notebook_manager.update_cell_fields(db, notebook_id, cell_id, updates_to_apply),
                        timeout=DB_OPERATION_TIMEOUT
                    )
                    route_logger.info(f"Successfully updated cell {cell_id} with new content/args: {updates_to_apply}")
                except asyncio.TimeoutError:
                    route_logger.error(f"Timeout updating cell {cell_id} fields before execution.")
                    raise HTTPException(status_code=504, detail="Database operation timed out while updating cell for execution.")
                except Exception as update_err:
                    route_logger.error(f"Error updating cell {cell_id} before execution: {update_err}", exc_info=True)
                    raise HTTPException(status_code=500, detail="Failed to update cell before execution")
            else:
                route_logger.debug(f"No content or argument updates provided for cell {cell_id} in execution_data.")

        # Re-fetch the cell to ensure we have the latest state after potential updates
        route_logger.debug(f"Attempting to re-fetch cell {cell_id} after potential updates.")
        updated_cell_for_execution = await asyncio.wait_for(
            notebook_manager.get_cell(db, notebook_id, cell_id),
            timeout=DB_OPERATION_TIMEOUT
        )
        route_logger.info(f"Cell {cell_id} (type: {updated_cell_for_execution.type}) current tool_name: '{updated_cell_for_execution.tool_name}', tool_arguments: {updated_cell_for_execution.tool_arguments}")

        route_logger.debug(f"Attempting to update cell {cell_id} status to QUEUED.")
        await asyncio.wait_for(
            notebook_manager.update_cell_status(db, notebook_id, cell_id, CellStatus.QUEUED),
            timeout=DB_OPERATION_TIMEOUT
        )
        route_logger.info(f"Successfully queued cell {cell_id} (type: {updated_cell_for_execution.type}) for execution.")
        return {
            "message": "Cell queued for execution",
            "cell_id": str(cell_id),
            "status": CellStatus.QUEUED.value
        }
    except asyncio.TimeoutError:
        route_logger.error(f"Timeout during one of the DB operations for execute_cell {cell_id}.")
        raise HTTPException(status_code=504, detail="Database operation timed out during cell execution request.")
    except KeyError as e:
        detail = str(e).strip("\' ")
        error_message = f"Resource not found: {detail}"
        route_logger.error(f"Resource not found for execution request: {detail}")
        raise HTTPException(status_code=404, detail=error_message)
    except Exception as e:
        route_logger.error(f"Unexpected error queueing cell {cell_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error processing cell execution request")


@router.post("/{notebook_id}/reorder", status_code=200, response_model=Dict)
async def reorder_cells(
    notebook_id: UUID,
    reorder_data: CellReorder,
    notebook_manager: NotebookManager = Depends(get_notebook_manager),
    db: AsyncSession = Depends(get_async_db_session)
) -> Dict:
    """
    Reorder cells in a notebook
    
    Args:
        notebook_id: The ID of the notebook
        reorder_data: The new order of cells
        
    Returns:
        Success message
    """
    route_logger.info(f"Reordering cells in notebook: {notebook_id}")
    try:
        cell_order_uuids = [UUID(cell_id) for cell_id in reorder_data.cell_order]
        await notebook_manager.reorder_cells(db, notebook_id, cell_order_uuids)
        route_logger.info(f"Cells reordered successfully for notebook: {notebook_id}")
        return {"message": "Cells reordered successfully"}
    except KeyError:
        route_logger.error(f"Notebook {notebook_id} not found for reordering")
        raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
    except ValueError as e:
        route_logger.error(f"Error reordering cells for notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        route_logger.error(f"Error reordering cells for notebook {notebook_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reorder cells")


@router.websocket("/ws/notebook/{notebook_id}")
async def notebook_websocket(
    websocket: WebSocket, 
    notebook_id: str,
    # Remove dependency on get_ws_manager
    # ws_manager: WebSocketManager = Depends(get_ws_manager)
):
    # Get the manager from the application state via the websocket
    try:
        ws_manager: WebSocketManager = websocket.app.state.ws_manager
    except AttributeError:
        route_logger.error("WebSocketManager not found in application state. Cannot establish WebSocket connection.")
        await websocket.close(code=1011) # Internal Error
        return
        
    route_logger.info(f"Attempting WebSocket connection for notebook ID: {notebook_id}, Client: {websocket.client}")
    try:
        notebook_uuid = UUID(notebook_id)
    except ValueError:
        route_logger.error(f"Invalid notebook_id format received: {notebook_id}")
        await websocket.close(code=4001, reason="Invalid notebook ID format")
        return
        
    await ws_manager.connect(websocket, notebook_uuid)
    route_logger.info(f"WebSocket connected for notebook: {notebook_id}")
    try:
        while True:
            data = await websocket.receive_text()
            route_logger.debug(f"WebSocket received data for notebook {notebook_id}: {data[:200]}...") # Log received data

            try:
                message_data = json.loads(data)
                message_type = message_data.get("type")
                payload_data = message_data.get("payload")

                if message_type == RERUN_INVESTIGATION_CELL:
                    route_logger.info(f"Received '{RERUN_INVESTIGATION_CELL}' message for notebook {notebook_id}")
                    if payload_data:
                        try:
                            payload = RerunInvestigationCellPayload(**payload_data)
                            
                            # Get NotebookManager and DB session
                            # Note: Accessing request.app.state directly in WebSocket is tricky.
                            # We rely on ws_manager being set up with app state access.
                            # For DB session, we need a way to get it per request/operation.
                            # A common pattern is to have a dependency that can be called.
                            # For simplicity here, we'll try to get it from app state if available,
                            # or create a new one. This part might need refinement based on app structure.
                            
                            notebook_manager: Optional[NotebookManager] = getattr(websocket.app.state, 'notebook_manager', None)
                            
                            if not notebook_manager:
                                route_logger.error("NotebookManager not found in application state. Cannot process rerun.")
                                # Optionally send an error back to client
                                await websocket.send_text(json.dumps({"type": "error", "message": "Internal server error: NotebookManager not available."}))
                                continue

                            # Get a new async DB session for this operation
                            async_session_factory = websocket.app.state.async_session_factory # Assuming this is set up in lifespan
                            async with async_session_factory() as db_session:
                                await notebook_manager.rerun_investigation_cell(
                                    db=db_session,
                                    notebook_id=payload.notebook_id,
                                    cell_id=payload.cell_id,
                                    session_id=payload.session_id # Pass session_id from payload
                                )
                            route_logger.info(f"Successfully processed '{RERUN_INVESTIGATION_CELL}' for cell {payload.cell_id}")

                        except ValidationError as e:
                            route_logger.error(f"Invalid payload for '{RERUN_INVESTIGATION_CELL}': {e.errors()}", exc_info=True)
                            await websocket.send_text(json.dumps({"type": "error", "message": f"Invalid payload: {e.errors()}"}))
                        except Exception as e_process:
                            route_logger.error(f"Error processing '{RERUN_INVESTIGATION_CELL}' for cell {payload_data.get('cell_id', 'unknown')}: {e_process}", exc_info=True)
                            await websocket.send_text(json.dumps({"type": "error", "message": f"Error processing rerun request: {str(e_process)}"}))
                    else:
                        route_logger.warning(f"'{RERUN_INVESTIGATION_CELL}' message received without payload.")
                        await websocket.send_text(json.dumps({"type": "error", "message": "Rerun message missing payload."}))
                
                else:
                    route_logger.debug(f"Received unknown WebSocket message type: {message_type} for notebook {notebook_id}")
                    # Optionally, send a message back to client indicating unknown type
                    # await websocket.send_text(json.dumps({"type": "info", "message": f"Unknown message type: {message_type}"}))

            except json.JSONDecodeError:
                route_logger.error(f"Failed to decode JSON from WebSocket message: {data[:200]}...", exc_info=True)
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON format."}))
            except Exception as e_outer:
                route_logger.error(f"Generic error in WebSocket message handling loop for notebook {notebook_id}: {e_outer}", exc_info=True)
                # Avoid flooding client with errors for every minor issue, but consider critical ones.

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, notebook_uuid)
        route_logger.info(f"WebSocket disconnected for notebook: {notebook_id}")
    except Exception as e:
         route_logger.error(f"WebSocket error for notebook {notebook_id}: {str(e)}", exc_info=True)
         ws_manager.disconnect(websocket, notebook_uuid)


# Server management endpoints
@router.get("/{notebook_id}/server-status")
async def get_notebook_server_status(
    notebook_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager)
) -> Dict[str, Any]:
    """Get the status of the LogAI MCP server for a notebook"""
    return await notebook_manager.get_notebook_server_status(notebook_id)


@router.post("/{notebook_id}/server/start")
async def start_notebook_server(
    notebook_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager)
) -> Dict[str, bool]:
    """Start the LogAI MCP server for a notebook"""
    success = await notebook_manager._start_notebook_server(notebook_id)
    return {"success": success}


@router.post("/{notebook_id}/server/stop")
async def stop_notebook_server(
    notebook_id: UUID,
    notebook_manager: NotebookManager = Depends(get_notebook_manager)
) -> Dict[str, bool]:
    """Stop the LogAI MCP server for a notebook"""
    success = await notebook_manager.stop_notebook_server(notebook_id)
    return {"success": success}
