"""
Notebook Manager Service
"""

import logging
import json # Added
import time # Added
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.core.notebook import Notebook, NotebookMetadata, DependencyGraph
from backend.core.cell import Cell, CellType, CellStatus, CellResult
from backend.core.types import ToolCallID
from backend.db.repositories import NotebookRepository
from backend.ai.investigation_system import InvestigationSystem 
from backend.core.execution import ExecutionQueue, CellExecutor


# Configure logging
logger = logging.getLogger(__name__)

# Make sure correlation_id is set for all logs
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

# Add the filter to our logger
logger.addFilter(CorrelationIdFilter())

# Type hint for session dependency
DbSession = Session # Restore alias temporarily for sync methods

def get_notebook_manager(request: Request) -> "NotebookManager":
    """Dependency function to get the NotebookManager instance from app state."""
    # Check if manager exists in state (it should if lifespan ran correctly)
    if not hasattr(request.app.state, 'notebook_manager') or not request.app.state.notebook_manager:
        # This case should ideally not happen if lifespan setup is correct
        logger.error("NotebookManager not found in application state. Lifespan setup might be incorrect.")
        # Raise an internal server error or handle appropriately
        raise RuntimeError("NotebookManager service not available")
    return request.app.state.notebook_manager


class NotebookManager:
    """
    Service layer for managing notebooks.
    Handles interactions between API/agents and the database repository.
    Database session is injected per method call.
    Now accepts ExecutionQueue and CellExecutor for handling queuing.
    """
    def __init__(self, execution_queue: Optional[ExecutionQueue] = None, cell_executor: Optional[CellExecutor] = None):
        correlation_id = str(uuid4())
        self.settings = get_settings()
        self.notify_callback: Optional[Callable] = None
        self.execution_queue = execution_queue
        self.cell_executor = cell_executor
        
        logger.info(
            "NotebookManager instance created", 
            extra={
                'correlation_id': correlation_id,
                'has_execution_queue': execution_queue is not None,
                'has_cell_executor': cell_executor is not None
            }
        )
    
    def set_notify_callback(self, callback: Callable) -> None:
        """
        Set the callback function for notifying clients of changes
        
        Args:
            callback: The callback function
        """
        self.notify_callback = callback
    
    async def create_notebook(self, db: AsyncSession, name: str, description: Optional[str] = None, metadata: Optional[Dict] = None) -> Notebook:
        """Create a new notebook (async)"""
        correlation_id = str(uuid4())
        logger.info(f"Creating new notebook with name '{name}'", extra={'correlation_id': correlation_id})
        repository = NotebookRepository(db) 
        # Await async repo call
        db_notebook_created = await repository.create_notebook(
            title=name,
            description=description,
            created_by=metadata.get("created_by") if metadata else None,
            tags=metadata.get("tags", []) if metadata else []
        )
        # Fetch the notebook again using get_notebook to ensure relationships are loaded
        # Pass the ID of the newly created notebook
        notebook = await self.get_notebook(db, UUID(str(db_notebook_created.id)))
        
        # Start LogAI MCP server for this notebook
        await self._start_notebook_server(notebook.id)
        
        logger.info(f"Successfully created and re-fetched notebook {notebook.id}", extra={'correlation_id': correlation_id})
        return notebook
    
    async def get_notebook(self, db: AsyncSession, notebook_id: UUID) -> Notebook:
        """Get a notebook by ID (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        db_notebook = await repository.get_notebook(str(notebook_id))
        if not db_notebook:
            logger.error(f"Notebook {notebook_id} not found")
            raise KeyError(f"Notebook {notebook_id} not found")
        notebook = self._db_notebook_to_model(db_notebook) # Conversion is sync
        logger.info(f"Retrieved notebook {notebook_id}")
        return notebook
    
    async def list_notebooks(self, db: AsyncSession) -> List[Notebook]:
        """Get a list of all notebooks (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        db_notebooks = await repository.list_notebooks()
        # Conversion is sync
        return [self._db_notebook_to_model(db_notebook) for db_notebook in db_notebooks]
    
    async def save_notebook(self, db: AsyncSession, notebook_id: UUID, notebook: Notebook) -> None:
        """Save the complete state of a Notebook object (async)."""
        correlation_id = str(uuid4())
        logger.info(f"Saving full state for notebook {notebook_id}", extra={'correlation_id': correlation_id})
        try:
            repository = NotebookRepository(db)
            # Assuming repository methods called within save are async if needed
            # e.g., if update_cell_order becomes async:
            if notebook.cell_order:
                # str_cell_order = [str(cell_id) for cell_id in notebook.cell_order]
                # await repository.update_cell_order(str(notebook_id), str_cell_order)
                logger.info(f"[{correlation_id}] Placeholder: Would save cell order (async).")
            # Update metadata
            update_data = {}
            if notebook.metadata.title is not None:
                update_data['title'] = notebook.metadata.title
            if notebook.metadata.description is not None:
                update_data['description'] = notebook.metadata.description
            # Add other metadata fields if they are direct columns on the Notebook table
            # For example, if 'tags' and 'created_by' are part of NotebookCreate/Update but stored in Notebook.metadata Pydantic model
            # and also direct columns on the DB model, they would be updated here.
            # For now, assuming only title and description are directly updatable on the Notebook DB model via kwargs.
            
            if update_data:
                await repository.update_notebook(str(notebook_id), **update_data)
                logger.info(f"[{correlation_id}] Updated notebook metadata (async).")
            else:
                # Still update timestamp even if no other metadata changed
                await repository._update_notebook_timestamp(str(notebook_id))
                logger.info(f"[{correlation_id}] Updated notebook timestamp (async, no other metadata changes).")

            # Persist cell order if it has changed (repository.update_notebook should handle this if cell_order is a column)
            # Or, if cell_order is managed by individual cell positions, this part might not be needed here
            # if notebook.cell_order:
            #     str_cell_order = [str(cell_id) for cell_id in notebook.cell_order]
            #     # This assumes repository.update_notebook can also take cell_order
            #     # await repository.update_notebook(str(notebook_id), cell_order=str_cell_order) 
            #     logger.info(f"[{correlation_id}] Updated notebook cell_order (async).")


            logger.info(f"Successfully completed save operations for notebook {notebook_id}", extra={'correlation_id': correlation_id})
        except Exception as e:
            logger.error(f"Error saving full state for notebook {notebook_id}: {e}", extra={'correlation_id': correlation_id}, exc_info=True)
            raise
    
    async def delete_notebook(self, db: AsyncSession, notebook_id: UUID) -> None:
        """Delete a notebook (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        success = await repository.delete_notebook(str(notebook_id))
        if not success:
            logger.error(f"Cannot delete notebook {notebook_id}: not found")
            raise KeyError(f"Notebook {notebook_id} not found")
        logger.info(f"Successfully deleted notebook {notebook_id}")
    
    async def create_cell(self, db: AsyncSession, notebook_id: UUID, cell_type: CellType, content: str, 
                    tool_call_id: ToolCallID,
                    tool_name: Optional[str] = None,
                    tool_arguments: Optional[Dict[str, Any]] = None,
                    position: Optional[int] = None, 
                    connection_id: Optional[str] = None,
                    metadata: Optional[Dict] = None, 
                    settings: Optional[Dict] = None,
                    dependencies: Optional[List[UUID]] = None,
                    result: Optional[CellResult] = None,
                    status: Optional[CellStatus] = None
                    ) -> Cell:
        """Create a new cell in a notebook (async)"""
        repository = NotebookRepository(db)
        # Await potentially async get_notebook call
        notebook_for_pos = await self.get_notebook(db, notebook_id)
        
        if position is None:
            position = len(notebook_for_pos.cells)
        
        # Await async repo call
        db_cell = await repository.create_cell(
            notebook_id=str(notebook_id),
            cell_type=cell_type.value,
            content=content,
            position=position,
            connection_id=connection_id,
            metadata=metadata,
            settings=settings,
            # Pass new fields to repository (will require repo update)
            tool_call_id=str(tool_call_id), # Convert UUID to string here
            tool_name=tool_name, # TODO: Uncomment when repository updated
            tool_arguments=tool_arguments, # TODO: Uncomment when repository updated
            # Initial result/status if provided
            result_content=result.content if result else None, # TODO: Uncomment when repository updated
            result_error=result.error if result else None, # TODO: Uncomment when repository updated
            result_execution_time=result.execution_time if result else None, # TODO: Uncomment when repository updated
            status=status.value if status else None # TODO: Uncomment when repository updated
        )
        
        if not db_cell:
            raise ValueError(f"Failed to create cell in notebook {notebook_id}")
        
        if dependencies:
            cell_id_str = str(db_cell.id) # Access ID after await
            for dep_id in dependencies:
                try:
                    # Await async repo call
                    await repository.add_dependency(dependent_id=cell_id_str, dependency_id=str(dep_id))
                except Exception as dep_err:
                    logger.error(f"Failed to add dependency {dep_id} to cell {cell_id_str}: {dep_err}", exc_info=True)

        # Await async repo call
        db_cell_with_deps = await repository.get_cell(str(db_cell.id))
        if not db_cell_with_deps:
            logger.error(f"Failed to re-fetch cell {db_cell.id} after creation and adding dependencies.")
            db_cell_with_deps = db_cell # Fallback
 
        cell = self._db_cell_to_model(db_cell_with_deps) # Conversion is sync
        
        logger.info(f"Created cell {cell.id} in notebook {notebook_id}")
        
        # Notify clients about the new cell
        if self.notify_callback:
            await self.notify_callback(notebook_id, cell.model_dump(mode='json'))
            
        return cell
    
    async def get_cell(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID) -> Cell:
        """Get a cell by ID (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        db_cell = await repository.get_cell(str(cell_id))
        if not db_cell or str(db_cell.notebook_id) != str(notebook_id):
            logger.error(f"Cell {cell_id} not found in notebook {notebook_id}")
            raise KeyError(f"Cell {cell_id} not found in notebook {notebook_id}")
        return self._db_cell_to_model(db_cell) # Conversion is sync

    async def update_cell_content(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID, content: str) -> Cell:
        """Update the content of a cell (async)"""
        correlation_id = str(uuid4())
        log_extra = {'correlation_id': correlation_id, 'notebook_id': str(notebook_id), 'cell_id': str(cell_id)}
        logger.info(f"Updating content for cell {cell_id}", extra=log_extra)
        
        repository = NotebookRepository(db)
        # Await async repo call
        updated_cell_data = await repository.update_cell(
            cell_id=str(cell_id),
            content=content # Pass as keyword argument directly
        )
        
        if not updated_cell_data:
            logger.error(f"Cell {cell_id} not found for content update", extra=log_extra)
            raise KeyError(f"Cell {cell_id} not found")
            
        updated_cell_model = self._db_cell_to_model(updated_cell_data)
        
        logger.info(f"Successfully updated content for cell {cell_id}", extra=log_extra)
        
        # Await async manager call
        stale_dependents = await self.mark_dependents_stale(db, notebook_id, cell_id)
        logger.info(f"Marked {len(stale_dependents)} dependents of cell {cell_id} as stale")
        
        # Notify clients about the change (including potentially stale dependents)
        if self.notify_callback:
            # We might want a specific notification type for content + stale updates
            # For now, just send the updated cell data
            await self.notify_callback(notebook_id, updated_cell_model.model_dump(mode='json'))
            # Consider sending updates for stale cells too
            # for stale_id in stale_dependents:
            #     stale_cell = self.get_cell(db, notebook_id, stale_id)
            #     asyncio.create_task(self.notify_callback(notebook_id, stale_cell.model_dump()))
                
        return updated_cell_model

    async def delete_cell(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID) -> None:
        """Delete a cell from a notebook (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        success = await repository.delete_cell(str(cell_id))
        if not success:
            logger.error(f"Cannot delete cell {cell_id}: not found")
            raise KeyError(f"Cell {cell_id} not found")
        logger.info(f"Successfully deleted cell {cell_id} from notebook {notebook_id}")
        
        # TODO: Update notebook cell_order and dependency graph
        # This requires fetching the notebook, modifying it, and potentially saving
        # For now, just logging the deletion.
        
        # Notify clients (might need a specific 'cell_deleted' type)
        if self.notify_callback:
             # Send a simple notification indicating deletion
             await self.notify_callback(notebook_id, {"id": str(cell_id), "deleted": True})
             

    async def update_cell_status(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID, status: CellStatus, correlation_id: Optional[str] = None) -> None:
        """Update the status of a cell (async) and add to queue if needed."""
        correlation_id = correlation_id or str(uuid4())
        log_extra = {'correlation_id': correlation_id, 'notebook_id': str(notebook_id), 'cell_id': str(cell_id), 'new_status': status.value}
        logger.info(f"Updating status for cell {cell_id} to {status.value}", extra=log_extra)

        try:
            repository = NotebookRepository(db)
            # Await async repo call
            updated_cell_data = await repository.update_cell(
                cell_id=str(cell_id),
                status=status.value # Pass as keyword argument directly
            )
            if not updated_cell_data:
                logger.error(f"Cell {cell_id} not found for status update", extra=log_extra)
                raise KeyError(f"Cell {cell_id} not found")

            logger.info(f"Successfully updated status for cell {cell_id} to {status.value} in DB", extra=log_extra)

            # Get the full cell model after update
            updated_cell_model = self._db_cell_to_model(updated_cell_data)

            # *** Add to Execution Queue if status is QUEUED ***
            if status == CellStatus.QUEUED:
                if self.execution_queue and self.cell_executor:
                    logger.info(f"Attempting to add cell {cell_id} (type: {updated_cell_model.type}, tool: '{updated_cell_model.tool_name}') to execution queue.", extra=log_extra)
                    try:
                        await self.execution_queue.add_cell(notebook_id, cell_id, self.cell_executor)
                        logger.info(f"Successfully added cell {cell_id} (type: {updated_cell_model.type}) to execution queue.", extra=log_extra)
                    except Exception as q_err:
                         logger.error(f"Failed to add cell {cell_id} (type: {updated_cell_model.type}) to execution queue: {q_err}", extra=log_extra, exc_info=True)
                         # Decide if we should revert status or just log the error
                         # For now, just log and continue with notification
                else:
                    logger.warning(
                        f"ExecutionQueue or CellExecutor not available in NotebookManager. Cannot queue cell {cell_id}.", 
                        extra=log_extra
                    )

            # Notify clients about the change via WebSocket
            if self.notify_callback:
                # Use asyncio.create_task if calling from sync context, but this method is async
                await self.notify_callback(notebook_id, updated_cell_model.model_dump(mode='json')) 
                logger.debug("WebSocket notification sent for cell status update", extra=log_extra)
            else:
                 logger.warning("notify_callback not set in NotebookManager. WebSocket update skipped.", extra=log_extra)

        except KeyError as e:
            logger.error(f"Resource not found during cell status update: {e}", extra=log_extra)
            raise # Re-raise KeyError for API layer to handle (404)
        except Exception as e:
            logger.error(f"Error updating cell status for {cell_id}: {e}", extra=log_extra, exc_info=True)
            raise # Re-raise other exceptions for API layer to handle (500)
    
    async def add_dependency(self, db: AsyncSession, notebook_id: UUID, dependent_id: UUID, dependency_id: UUID) -> None:
        """Add a dependency between two cells (async)"""
        repository = NotebookRepository(db)
        # Await async repo call
        await repository.add_dependency(str(dependent_id), str(dependency_id))
        logger.info(f"Added dependency from {dependency_id} to {dependent_id} in notebook {notebook_id}")
        
        # TODO: Update Notebook model state if needed
        
    async def remove_dependency(self, db: AsyncSession, notebook_id: UUID, dependent_id: UUID, dependency_id: UUID) -> None:
        """Remove a dependency between two cells (async)"""
        # Instantiate repository locally (Repository now expects AsyncSession)
        repository = NotebookRepository(db)
        # Await the async repository method
        success = await repository.remove_dependency(str(dependent_id), str(dependency_id))
        if success:
            logger.info(f"Removed dependency from {dependency_id} to {dependent_id} in notebook {notebook_id}")
        else:
            # Repository logs if dependency wasn't found
            logger.warning(f"Attempted to remove non-existent dependency from {dependency_id} to {dependent_id} in notebook {notebook_id}")
        
        # TODO: Update Notebook model state if needed (consider if this should be async too)

    async def set_cell_result(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID, result: Any, error: Optional[str] = None, 
                        execution_time: float = 0.0) -> None:
        """Set the result of a cell execution (async)"""
        correlation_id = str(uuid4())
        final_status = CellStatus.ERROR if error else CellStatus.SUCCESS
        log_extra = {
            'correlation_id': correlation_id, 
            'notebook_id': str(notebook_id), 
            'cell_id': str(cell_id), 
            'final_status': final_status.value,
            'has_error': error is not None,
            'execution_time_sec': execution_time
        }
        logger.info(f"Setting result for cell {cell_id}", extra=log_extra)
        
        try:
            repository = NotebookRepository(db)
            
            # --- Serialize result_content before saving --- 
            serializable_result_content = None
            if result is not None:
                if hasattr(result, 'model_dump'): # Check for Pydantic-like models
                    try:
                        serializable_result_content = result.model_dump(mode='json')
                    except Exception as dump_err:
                         logger.warning(f"Failed to model_dump result for cell {cell_id}: {dump_err}. Falling back to dict/str.", extra=log_extra)
                         serializable_result_content = str(result) # Fallback
                elif isinstance(result, (dict, list, str, int, float, bool)):
                     serializable_result_content = result # Already JSON serializable
                else:
                     # Attempt to convert other types to string as a fallback
                     logger.warning(f"Result content for cell {cell_id} is of unexpected type {type(result)}. Converting to string.", extra=log_extra)
                     serializable_result_content = str(result)
            # --- End Serialization --- 
            
            # Prepare updates dictionary using the serialized content
            updates = {
                'status': final_status.value,
                'result_content': serializable_result_content,
                'result_error': error,
                'result_execution_time': execution_time,
            }
            
            # Await async repo call
            updated_cell_data = await repository.update_cell(
                cell_id=str(cell_id),
                **updates # Spread the dictionary
            )
            
            if not updated_cell_data:
                 logger.error(f"Cell {cell_id} not found when trying to set result", extra=log_extra)
                 raise KeyError(f"Cell {cell_id} not found")
                 
            updated_cell_model = self._db_cell_to_model(updated_cell_data)
            logger.info(f"Successfully set result for cell {cell_id}", extra=log_extra)
            
             # Notify clients about the change
            if self.notify_callback:
                await self.notify_callback(notebook_id, updated_cell_model.model_dump(mode='json'))
                logger.debug("WebSocket notification sent for cell result update", extra=log_extra)
            else:
                 logger.warning("notify_callback not set. WebSocket update skipped.", extra=log_extra)
                 
        except KeyError as e:
            logger.error(f"Resource not found when setting cell result: {e}", extra=log_extra)
            raise
        except Exception as e:
            logger.error(f"Error setting cell result for {cell_id}: {e}", extra=log_extra, exc_info=True)
            # Attempt to mark the cell as error in DB if result setting failed mid-way
            try:
                error_update = {
                    'status': CellStatus.ERROR.value,
                    'result_error': f"Internal error setting result: {str(e)}"
                }
                await repository.update_cell(cell_id=str(cell_id), updates=error_update)
            except Exception as inner_e:
                 logger.critical(f"Failed to mark cell {cell_id} as ERROR after outer error: {inner_e}", extra=log_extra)
            raise # Re-raise original exception

    async def update_cell_fields(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID, updates: Dict[str, Any]) -> None:
        """Update specific fields of a cell (async)."""
        correlation_id = str(uuid4())
        log_extra = {
            'correlation_id': correlation_id, 
            'notebook_id': str(notebook_id), 
            'cell_id': str(cell_id), 
            'updated_fields': list(updates.keys())
        }
        logger.info(f"Updating fields for cell {cell_id}", extra=log_extra)
        
        if not updates:
            logger.warning("update_cell_fields called with empty updates dictionary. No action taken.", extra=log_extra)
            # If we need to ensure notification even for no-op, we might fetch and proceed.
            # For now, if updates dict is empty, it's a true no-op for fields.
            return 
            
        try:
            # Make a copy to modify, to avoid changing the input dict if it's used elsewhere
            effective_updates = updates.copy()

            # Check if 'tool_arguments' is being updated to an "empty" value.
            # "Empty" could mean None or an empty dictionary.
            # If so, prevent it from being passed to the repository to preserve existing args.
            if 'tool_arguments' in effective_updates:
                tool_args_update_value = effective_updates.get('tool_arguments')
                if tool_args_update_value is None or tool_args_update_value == {}:
                    logger.info(f"Received an empty update for 'tool_arguments' for cell {cell_id} (value: {tool_args_update_value}). "
                                f"Preserving existing tool_arguments by not including this field in the DB update.", extra=log_extra)
                    del effective_updates['tool_arguments']
            
            repository = NotebookRepository(db) # Initialize repository

            if not effective_updates:
                # This means the original 'updates' might have only contained an empty 'tool_arguments'
                # or was otherwise emptied by the logic above. No actual field update to DB.
                logger.info(f"Effective updates for cell {cell_id} are empty after processing. "
                            f"No database field update will be performed. Original updates: {updates}", extra=log_extra)
                # Fetch the current cell state for notification purposes
                updated_cell_data = await repository.get_cell(str(cell_id))
                if not updated_cell_data:
                    logger.error(f"Cell {cell_id} not found when trying to fetch for no-op field update.", extra=log_extra)
                    raise KeyError(f"Cell {cell_id} not found")
            else:
                # Proceed with updating the non-empty effective_updates
                updated_cell_data = await repository.update_cell(
                    cell_id=str(cell_id),
                    **effective_updates 
                )
                if not updated_cell_data:
                    logger.error(f"Cell {cell_id} not found when trying to update fields with effective_updates: {effective_updates}", extra=log_extra)
                    raise KeyError(f"Cell {cell_id} not found")
                 
            updated_cell_model = self._db_cell_to_model(updated_cell_data)
            logger.info(f"Successfully processed field update for cell {cell_id}. Effective updates applied: {list(effective_updates.keys())}", extra=log_extra)
            
            # Notify clients about the change
            if self.notify_callback:
                await self.notify_callback(notebook_id, updated_cell_model.model_dump(mode='json'))
                logger.debug("WebSocket notification sent for cell field update", extra=log_extra)
            else:
                 logger.warning("notify_callback not set. WebSocket update skipped.", extra=log_extra)

        except KeyError as e:
            logger.error(f"Resource not found when updating cell fields: {e}", extra=log_extra)
            raise
        except Exception as e:
            logger.error(f"Error updating cell fields for {cell_id}: {e}", extra=log_extra, exc_info=True)
            raise
            
    async def mark_dependents_stale(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID) -> Set[UUID]:
        """Mark all direct and indirect dependents of a cell as stale (async)"""
        correlation_id = str(uuid4())
        log_extra = {'correlation_id': correlation_id, 'notebook_id': str(notebook_id), 'cell_id': str(cell_id)}
        logger.info(f"Marking dependents of cell {cell_id} as stale", extra=log_extra)
        
        try:
            repository = NotebookRepository(db)
            # Await async manager call
            notebook = await self.get_notebook(db, notebook_id) 
            dependency_graph = notebook.dependency_graph
            
            if not dependency_graph:
                logger.warning("No dependency graph found for notebook {notebook_id}. Cannot mark stale.")
                return set()
            
            # Get all dependents (direct and indirect)
            all_dependents = dependency_graph.get_all_dependents(cell_id)
            
            stale_ids = set()
            if all_dependents:
                logger.info(f"Found dependents to mark stale: {all_dependents}", extra=log_extra)
                for dep_id in all_dependents:
                    try:
                        # Await async repo call
                        current_dep_cell = await repository.get_cell(str(dep_id))
                        current_status = getattr(current_dep_cell, 'status', None)
                        if current_dep_cell is not None and current_status != CellStatus.STALE.value:
                            # Await async repo call
                            await repository.update_cell(
                                cell_id=str(dep_id),
                                status=CellStatus.STALE.value # Pass as keyword argument
                            )
                            stale_ids.add(dep_id)
                            logger.debug(f"Marked dependent cell {dep_id} as stale", extra=log_extra)
                        elif current_dep_cell is None: 
                             logger.warning(f"Dependent cell {dep_id} not found during stale marking.", extra=log_extra)
                             
                    except Exception as e:
                        logger.error(f"Error marking dependent cell {dep_id} as stale: {e}", extra=log_extra, exc_info=True)
                        # Continue trying to mark others
                        
            logger.info(f"Finished marking dependents. Marked {len(stale_ids)} cells as stale.", extra=log_extra)
            return stale_ids
            
        except KeyError:
             logger.warning(f"Notebook {notebook_id} not found when trying to mark dependents stale.", extra=log_extra)
             return set()
        except Exception as e:
            logger.error(f"Error marking dependents stale for cell {cell_id}: {e}", extra=log_extra, exc_info=True)
            return set() # Return empty set on error

    async def reorder_cells(self, db: AsyncSession, notebook_id: UUID, cell_order: List[UUID]) -> None:
        """Reorder cells in a notebook (async)"""
        repository = NotebookRepository(db)
        str_cell_order = [str(cell_id) for cell_id in cell_order]
        
        # Call the repository method to update cell positions
        success = await repository.reorder_cells(str(notebook_id), str_cell_order)
        
        if success:
            logger.info(f"Successfully reordered cells in repository for notebook {notebook_id} (positions updated)")
            # The cell_order is derived from cell positions, so no separate update to Notebook.cell_order field is needed here.
            # The Notebook._db_notebook_to_model method will reconstruct it.
            
            # Notify clients (might need a specific 'reorder' type)
            if self.notify_callback:
                 # Send the new order, or perhaps the whole notebook state?
                 # Fetching the full notebook to send its updated state might be better
                 updated_notebook = await self.get_notebook(db, notebook_id)
                 await self.notify_callback(notebook_id, updated_notebook.model_dump(mode='json'))
                 # Old notification: await self.notify_callback(notebook_id, {"type": "cell_reorder", "order": str_cell_order})
        else:
            logger.error(f"Failed to reorder cells in repository for notebook {notebook_id}")
            # Consider raising an error or handling this failure case

    async def rerun_investigation_cell(self, db: AsyncSession, notebook_id: UUID, cell_id: UUID, session_id: str) -> None:
        """
        Re-run the generation of an investigation report cell using Investigation System.
        """
        correlation_id = str(uuid4())
        log_extra = {'correlation_id': correlation_id, 'notebook_id': str(notebook_id), 'cell_id': str(cell_id), 'session_id': session_id}
        logger.info(f"Attempting to re-run investigation report cell {cell_id}", extra=log_extra)

        try:
            # 1. Fetch the target cell and the full notebook
            report_cell_model = await self.get_cell(db, notebook_id, cell_id)
            # Check if this is an investigation report tool cell
            is_investigation_report = (
                report_cell_model.type == CellType.TOOL and 
                (report_cell_model.tool_name == "investigation_report" or 
                 report_cell_model.metadata.get("original_type") == "investigation_report")
            )
            if not is_investigation_report:
                logger.error(f"Cell {cell_id} is not an investigation report cell. Type: {report_cell_model.type}, tool_name: {report_cell_model.tool_name}", extra=log_extra)
                # Optionally notify client of error
                if self.notify_callback:
                    await self.notify_callback(notebook_id, {
                        "type": "error", 
                        "message": f"Cell {cell_id} is not an investigation report cell.",
                        "cell_id": str(cell_id)
                    })
                return

            notebook = await self.get_notebook(db, notebook_id)
            logger.info(f"Fetched report cell {cell_id} and notebook {notebook_id}", extra=log_extra)

            # 2. Update cell status to RUNNING
            await self.update_cell_status(db, notebook_id, cell_id, CellStatus.RUNNING, correlation_id=correlation_id)

            # 3. Extract original_query from the cell's existing result
            original_query = None
            if report_cell_model.result and report_cell_model.result.content and isinstance(report_cell_model.result.content, dict):
                original_query = report_cell_model.result.content.get('query')
            
            if not original_query:
                logger.error(f"Could not find original_query in existing result for report cell {cell_id}", extra=log_extra)
                await self.set_cell_result(db, notebook_id, cell_id, result=report_cell_model.result.content if report_cell_model.result else {}, error="Could not find original query for re-run.", execution_time=0.0)
                return
            logger.info(f"Extracted original_query: '{original_query[:100]}...' for cell {cell_id}", extra=log_extra)

            # 4. Reconstruct findings_summary from dependencies
            findings_summary_lines = []
            dependency_ids = report_cell_model.dependencies # These are UUIDs
            
            logger.info(f"Report cell {cell_id} has dependencies: {dependency_ids}", extra=log_extra)

            for dep_cell_id_uuid in dependency_ids:
                dep_cell_id = str(dep_cell_id_uuid)
                if dep_cell_id_uuid == cell_id : # Should not happen if graph is correct
                    continue

                dep_cell = notebook.cells.get(dep_cell_id_uuid) # Get Cell object from notebook.cells
                if not dep_cell:
                    logger.warning(f"Dependency cell {dep_cell_id} not found in notebook model for report {cell_id}", extra=log_extra)
                    findings_summary_lines.append(f"Step (ID: {dep_cell_id}): Error - Cell data not found.")
                    continue

                desc = dep_cell.content # Or some metadata field if content is code/tool specific
                cell_type_str = dep_cell.type.value
                
                result_str = ""
                if dep_cell.status == CellStatus.ERROR and dep_cell.result and dep_cell.result.error:
                    result_str = f"Error: {dep_cell.result.error}"
                elif dep_cell.result and dep_cell.result.content is not None:
                    # Adapt formatting based on cell type
                    if dep_cell.type == CellType.MARKDOWN:
                        result_str = f"Data: {str(dep_cell.result.content)[:500]}..."
                    elif isinstance(dep_cell.result.content, dict) or isinstance(dep_cell.result.content, list):
                        # For tool cells (GitHub, Python, etc.) that store dict/list results
                        result_str = f"Data: {json.dumps(dep_cell.result.content)[:500]}..."
                    else:
                        result_str = f"Data: {str(dep_cell.result.content)[:500]}..."
                else:
                    result_str = "Step completed, but no specific outputs captured or status is not SUCCESS/ERROR."
                
                findings_summary_lines.append(f"Step (ID: {dep_cell_id}, Type: {cell_type_str}): {desc}\nResult:\n{result_str}")

            findings_summary = "\n---\n".join(findings_summary_lines)
            if not findings_summary:
                findings_summary = "No preceding investigation steps were successfully executed or produced results for this re-run."
            
            logger.info(f"Reconstructed findings_summary for cell {cell_id}:\n{findings_summary[:500]}...", extra=log_extra)

            # 5. Initialize Investigation System for report generation
            investigation_system = InvestigationSystem(
                notebook_id=str(notebook_id),
                notebook_manager=self,  # Pass self for notebook operations
                connection_manager=None  # Will use default
            )
            logger.info(f"Initialized InvestigationSystem for re-run of cell {cell_id}", extra=log_extra)

            # 6. Generate report using Investigation System
            report_query = f"""
Generate a comprehensive investigation report based on the following:

Original Query: {original_query}

Investigation Findings:
{findings_summary}

Please create a structured investigation report with:
1. Executive Summary
2. Key Findings  
3. Root Cause Analysis
4. Recommendations
5. Next Steps

Format as a professional investigation report.
"""

            final_report_content = None
            start_time = time.time()

            # Stream report generation using Investigation System
            async for result in investigation_system.investigate(
                query=report_query,
                investigation_type="general",
                notebook_context=f"Session: {session_id}, Notebook: {notebook_id}"
            ):
                if result.get("type") == "final_report":
                    final_report_content = result.get("content", "")
                    break
                elif result.get("type") in ["investigation_progress", "status"]:
                    # Forward progress updates to clients
                    if self.notify_callback:
                        await self.notify_callback(notebook_id, {
                            "type": "status_update", 
                            "data": {
                                "message": "Generating investigation report...",
                                "cell_id": str(cell_id),
                                "status": "processing"
                            }
                        })
            
            execution_time = time.time() - start_time

            # 7. Update cell with new report
            if final_report_content:
                # Create a simple InvestigationReport-like structure
                report_data = {
                    "title": f"Investigation Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "query": original_query,
                    "content": final_report_content,
                    "generated_at": datetime.now().isoformat(),
                    "session_id": session_id
                }
                
                # Update cell content (title) if it changed
                new_title = report_data["title"]
                current_display_content = f"# Investigation Report: {new_title}\n\n_Structured report data generated using Investigation System._"
                
                updates_for_cell = {
                    'status': CellStatus.SUCCESS.value,
                    'result_content': report_data,
                    'result_error': None,
                    'result_execution_time': execution_time,
                    'content': current_display_content # Update the display content as well
                }
                await self.update_cell_fields(db, notebook_id, cell_id, updates_for_cell)
                logger.info(f"Successfully updated cell {cell_id} with re-run report using Investigation System.", extra=log_extra)
            else:
                error_msg = "Re-run: Investigation System did not produce a final report."
                logger.error(error_msg, extra=log_extra)
                await self.set_cell_result(db, notebook_id, cell_id, result=report_cell_model.result.content if report_cell_model.result else {}, error=error_msg, execution_time=execution_time)

        except KeyError as e:
            logger.error(f"KeyError during investigation cell re-run for {cell_id}: {e}", extra=log_extra, exc_info=True)
            await self.set_cell_result(db, notebook_id, cell_id, result={}, error=f"Error during re-run: {str(e)}", execution_time=0.0)
        except Exception as e:
            logger.error(f"Unexpected error during investigation cell re-run for {cell_id}: {e}", extra=log_extra, exc_info=True)
            # Attempt to set cell to error status
            try:
                await self.set_cell_result(db, notebook_id, cell_id, result={}, error=f"Unexpected error during re-run: {str(e)}", execution_time=0.0)
            except Exception as e_final:
                logger.critical(f"Failed to even set error status for cell {cell_id} after re-run failure: {e_final}", extra=log_extra)
        finally:
            # The main try/except blocks already handle sending WebSocket notifications
            pass


    def _db_notebook_to_model(self, db_notebook) -> Notebook:
        """Convert DB Notebook object to Pydantic Notebook model"""
        # Fetch cells associated with the notebook
        db_cells = db_notebook.cells # Access the relationship
        
        # Convert cells first (includes fetching/setting dependencies)
        cells_dict = {str(db_cell.id): self._db_cell_to_model(db_cell) for db_cell in db_cells}
        
        # Reconstruct cell_order from position attribute (if necessary)
        # Or rely on a separate cell_order field in the DB Notebook model
        # Assuming db_notebook has a cell_order attribute (e.g., List[str])
        cell_order_uuids = []
        if hasattr(db_notebook, 'cell_order') and db_notebook.cell_order:
            try:
                cell_order_uuids = [UUID(cell_id_str) for cell_id_str in db_notebook.cell_order]
            except (ValueError, TypeError) as e:
                 logger.error(f"Error parsing cell_order for notebook {db_notebook.id}: {e}. Falling back to position sort.", exc_info=True)
                 # Fallback to sorting by position if order is invalid or missing
                 sorted_cells = sorted(db_cells, key=lambda c: c.position or 0)
                 cell_order_uuids = [UUID(c.id) for c in sorted_cells]
        else:
             # Fallback if no cell_order field exists
             sorted_cells = sorted(db_cells, key=lambda c: c.position or 0)
             cell_order_uuids = [UUID(c.id) for c in sorted_cells]
             
        # *** Correctly build dependency graph ***
        dependency_graph = DependencyGraph() # Initialize empty graph
        for cell_model in cells_dict.values():
            dependency_graph.add_cell(cell_model) # Add cell first
            for dep_id in cell_model.dependencies:
                # Ensure the dependency cell also exists in the dict before adding edge
                if str(dep_id) in cells_dict:
                    dependency_graph.add_dependency(cell_model.id, dep_id)
                else:
                    logger.warning(f"Dependency {dep_id} for cell {cell_model.id} not found in current notebook cells.")

        return Notebook(
            id=UUID(db_notebook.id),
            created_at=db_notebook.created_at,
            updated_at=db_notebook.updated_at,
            metadata=NotebookMetadata(
                title=db_notebook.title,
                description=db_notebook.description or "",
                created_by=db_notebook.created_by,
                tags=db_notebook.tags or []
            ),
            cells=cells_dict,
            cell_order=cell_order_uuids, # Use the previously determined order
            dependency_graph=dependency_graph # Use the built graph
        )

    def _db_cell_to_model(self, db_cell) -> Cell:
        """Convert DB Cell object to Pydantic Cell model"""
        # Handle potential string representation of UUID for tool_call_id
        tool_call_id_uuid = None
        if db_cell.tool_call_id:
            try:
                tool_call_id_uuid = UUID(db_cell.tool_call_id)
            except ValueError:
                 logger.warning(f"Invalid UUID format for tool_call_id: {db_cell.tool_call_id} in cell {db_cell.id}")
                 # Assign a new one or handle as appropriate
                 tool_call_id_uuid = uuid4() # Example: assign a new one
        else:
             # If null/empty in DB, generate a new one (cells should have this)
             logger.warning(f"Missing tool_call_id for cell {db_cell.id}, generating a new one.")
             tool_call_id_uuid = uuid4()
             
        # Get dependencies (assuming db_cell has a 'dependencies' relationship)
        dependencies_uuids = set()
        if hasattr(db_cell, 'dependencies') and db_cell.dependencies:
            dependencies_uuids = {UUID(dep.id) for dep in db_cell.dependencies}
        else:
            # If relationship not loaded or empty, log a warning maybe
            # logger.debug(f"No dependencies found or loaded for cell {db_cell.id}")
            pass

        # Construct CellResult if there is existing result data, regardless of the current status.
        # This ensures that cells marked STALE still expose their last known output so that
        # planners / summarizers can read and display it.
        result_model = None
        if db_cell.result_content is not None or db_cell.result_error is not None:
            result_model = CellResult(
                content=db_cell.result_content,
                error=db_cell.result_error,
                execution_time=db_cell.result_execution_time or 0.0,
                # Use cell's updated_at as a proxy for result timestamp if needed
                timestamp=db_cell.updated_at or datetime.now(timezone.utc)
            )

        return Cell(
            id=UUID(db_cell.id),
            notebook_id=UUID(db_cell.notebook_id),
            type=CellType(db_cell.type),
            content=db_cell.content,
            tool_call_id=tool_call_id_uuid, 
            tool_name=db_cell.tool_name,
            tool_arguments=db_cell.tool_arguments,
            connection_id=db_cell.connection_id,
            status=CellStatus(db_cell.status or CellStatus.IDLE.value), # Default to IDLE if status is null
            dependencies=dependencies_uuids, # Ensure this is set
            result=result_model,
            metadata=db_cell.cell_metadata or {},
            settings=db_cell.settings or {},
            created_at=db_cell.created_at,
            updated_at=db_cell.updated_at,
            position=db_cell.position
        )
    
    async def _start_notebook_server(self, notebook_id: UUID) -> bool:
        """Start the LogAI MCP server for a notebook"""
        try:
            from backend.services.logai_container_manager import get_container_manager
            from backend.services.connection_manager import get_connection_manager
            
            # Get workspace configuration
            conn_manager = get_connection_manager()
            workspace_connections = await conn_manager.get_connections_by_type("logai_workspace")
            
            if not workspace_connections:
                logger.warning(f"No workspace configured, cannot start server for notebook {notebook_id}")
                return False
            
            # Use the first (and should be only) workspace configuration
            workspace_config = workspace_connections[0].config
            
            # Start container
            container_manager = get_container_manager()
            container_info = await container_manager.start_container(
                notebook_id=str(notebook_id),
                config=workspace_config
            )
            
            logger.info(f"Started LogAI MCP server for notebook {notebook_id} at {container_info.sse_url}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start server for notebook {notebook_id}: {e}", exc_info=True)
            return False
    
    async def stop_notebook_server(self, notebook_id: UUID) -> bool:
        """Stop the LogAI MCP server for a notebook"""
        try:
            from backend.services.logai_container_manager import get_container_manager
            
            container_manager = get_container_manager()
            success = await container_manager.stop_container(str(notebook_id))
            
            if success:
                logger.info(f"Stopped LogAI MCP server for notebook {notebook_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to stop server for notebook {notebook_id}: {e}", exc_info=True)
            return False
    
    async def get_notebook_server_status(self, notebook_id: UUID) -> Dict[str, Any]:
        """Get the status of the LogAI MCP server for a notebook"""
        try:
            from backend.services.logai_container_manager import get_container_manager
            
            container_manager = get_container_manager()
            container_info = await container_manager.get_container_info(str(notebook_id))
            
            if container_info:
                return {
                    "running": True,
                    "port": container_info.port,
                    "sse_url": container_info.sse_url,
                    "started_at": container_info.started_at
                }
            else:
                return {
                    "running": False
                }
                
        except Exception as e:
            logger.error(f"Failed to get server status for notebook {notebook_id}: {e}", exc_info=True)
            return {
                "running": False,
                "error": str(e)
            }
