"""
Repository module for database operations
"""

import logging
from typing import Dict, List, Optional, Any, TypeVar, Union
from datetime import datetime, timezone

from sqlalchemy import select, delete, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.db.models import Connection, DefaultConnection, Notebook, Cell, CellDependency
from backend.core.cell import CellStatus

# Configure logging
logger = logging.getLogger(__name__)

# Type variable for generic repository functions
T = TypeVar('T')


class ConnectionRepository:
    """Repository for connection database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        logger.info("ConnectionRepository initialized with session: %s", session, extra={'correlation_id': 'N/A'})
    
    async def get_all(self) -> List[Connection]:
        """Get all connections"""
        logger.info("Fetching all connections", extra={'correlation_id': 'N/A'})
        try:
            query = select(Connection)
            result = await self.session.execute(query)
            connections = list(result.scalars().all())
            logger.info("Retrieved %d connections", len(connections), extra={'correlation_id': 'N/A'})
            return connections
        except SQLAlchemyError as e:
            logger.error("Error fetching all connections: %s", str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def get_by_id(self, connection_id: str) -> Optional[Connection]:
        """Get a connection by ID"""
        logger.info("Fetching connection with ID: %s", connection_id, extra={'correlation_id': 'N/A'})
        try:
            query = select(Connection).where(Connection.id == connection_id)
            result = await self.session.execute(query)
            connection = result.scalar_one_or_none()
            if connection:
                logger.info("Found connection: %s", connection.name, extra={'correlation_id': 'N/A'})
            else:
                logger.info("No connection found with ID: %s", connection_id, extra={'correlation_id': 'N/A'})
            return connection
        except SQLAlchemyError as e:
            logger.error("Error fetching connection with ID %s: %s", connection_id, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def get_by_type(self, connection_type: str) -> List[Connection]:
        """Get connections by type"""
        logger.info("Fetching connections of type: %s", connection_type, extra={'correlation_id': 'N/A'})
        try:
            query = select(Connection).where(Connection.type == connection_type)
            result = await self.session.execute(query)
            connections = list(result.scalars().all())
            logger.info("Retrieved %d connections of type %s", len(connections), connection_type, extra={'correlation_id': 'N/A'})
            return connections
        except SQLAlchemyError as e:
            logger.error("Error fetching connections of type %s: %s", connection_type, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def get_by_name_and_type(self, name: str, connection_type: str) -> Optional[Connection]:
        """Get connection by name and type"""
        logger.info("Getting connection with name %s and type %s", name, connection_type, extra={'correlation_id': 'N/A'})
        try:
            query = select(Connection).where(
                and_(
                    Connection.name == name,
                    Connection.type == connection_type
                )
            )
            result = await self.session.execute(query)
            connection = result.scalars().first()
            if connection:
                logger.info("Found connection: %s", connection.name, extra={'correlation_id': 'N/A'})
            else:
                logger.info("No connection found with name %s and type %s", name, connection_type, extra={'correlation_id': 'N/A'})
            return connection
        except SQLAlchemyError as e:
            logger.error("Error fetching connection with name %s and type %s: %s", name, connection_type, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def create(self, name: str, connection_type: str, config: Dict[str, Any]) -> Connection:
        """Create a new connection"""
        logger.info("Creating new connection: %s (type: %s)", name, connection_type, extra={'correlation_id': 'N/A'})
        try:
            connection = Connection(
                name=name,
                type=connection_type,
                config=config
            )
            self.session.add(connection)
            await self.session.commit()
            await self.session.refresh(connection)
            logger.info("Connection created successfully with ID: %s", connection.id, extra={'correlation_id': 'N/A'})
            return connection
        except IntegrityError as e:
            await self.session.rollback()
            logger.error("Integrity error creating connection: %s", str(e), extra={'correlation_id': 'N/A'})
            raise
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error("Error creating connection: %s", str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def update(self, connection_id: str, name: str, config: Dict[str, Any]) -> Optional[Connection]:
        """Update an existing connection"""
        logger.info("Updating connection with ID: %s", connection_id, extra={'correlation_id': 'N/A'})
        try:
            connection = await self.get_by_id(connection_id)
            if not connection:
                logger.info("Cannot update connection: ID %s not found", connection_id, extra={'correlation_id': 'N/A'})
                return None
            
            # Use SQLAlchemy update statement instead of direct attribute assignment
            stmt = update(Connection).where(Connection.id == connection_id).values(name=name, config=config)
            await self.session.execute(stmt)
            await self.session.commit()
            
            # Refresh and return the updated connection
            updated_connection = await self.get_by_id(connection_id)
            logger.info("Connection %s updated successfully", connection_id, extra={'correlation_id': 'N/A'})
            return updated_connection
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error("Error updating connection %s: %s", connection_id, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def delete(self, connection_id: str) -> bool:
        """Delete a connection"""
        logger.info("Deleting connection with ID: %s", connection_id, extra={'correlation_id': 'N/A'})
        try:
            query = delete(Connection).where(Connection.id == connection_id)
            result = await self.session.execute(query)
            await self.session.commit()
            success = result.rowcount > 0
            if success:
                logger.info("Connection %s deleted successfully", connection_id, extra={'correlation_id': 'N/A'})
            else:
                logger.info("Connection %s not found for deletion", connection_id, extra={'correlation_id': 'N/A'})
            return success
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error("Error deleting connection %s: %s", connection_id, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def get_default_connection(self, connection_type: str) -> Optional[Connection]:
        """Get the default connection for a type"""
        logger.info("Fetching default connection for type: %s", connection_type, extra={'correlation_id': 'N/A'})
        try:
            query = select(DefaultConnection).where(DefaultConnection.connection_type == connection_type)
            result = await self.session.execute(query)
            default_conn = result.scalar_one_or_none()
            
            if default_conn:
                # Safely extract the connection ID
                conn_id = default_conn.connection_id
                conn_id_str = str(conn_id) if conn_id is not None else None
                if conn_id_str:
                    logger.info("Found default connection ID: %s", conn_id_str, extra={'correlation_id': 'N/A'})
                    return await self.get_by_id(conn_id_str)
            logger.info("No default connection found for type: %s", connection_type, extra={'correlation_id': 'N/A'})
            return None
        except SQLAlchemyError as e:
            logger.error("Error fetching default connection for type %s: %s", connection_type, str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def set_default_connection(self, connection_type: str, connection_id: str) -> DefaultConnection:
        """Set a connection as default for its type"""
        logger.info("Setting connection %s as default for type: %s", connection_id, connection_type, extra={'correlation_id': 'N/A'})
        try:
            # First validate the connection exists
            connection = await self.get_by_id(connection_id)
            if not connection:
                raise ValueError(f"Connection with ID {connection_id} does not exist")
                
            # Check if a default connection already exists for this type
            query = select(DefaultConnection).where(DefaultConnection.connection_type == connection_type)
            result = await self.session.execute(query)
            default_conn = result.scalar_one_or_none()
            
            if default_conn:
                logger.info("Updating existing default connection for type: %s", connection_type, extra={'correlation_id': 'N/A'})
                # Update existing default using SQLAlchemy update statement
                stmt = update(DefaultConnection).where(
                    DefaultConnection.connection_type == connection_type
                ).values(connection_id=connection_id)
                await self.session.execute(stmt)
            else:
                logger.info("Creating new default connection entry for type: %s", connection_type, extra={'correlation_id': 'N/A'})
                # Create new default
                default_conn = DefaultConnection(
                    connection_type=connection_type,
                    connection_id=connection_id
                )
                self.session.add(default_conn)
            
            await self.session.commit()
            
            # Re-fetch the default connection to return
            query = select(DefaultConnection).where(DefaultConnection.connection_type == connection_type)
            result = await self.session.execute(query)
            default_conn = result.scalar_one()
            logger.info("Successfully set connection %s as default for type: %s", connection_id, connection_type, extra={'correlation_id': 'N/A'})
            return default_conn
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error("Error setting default connection: %s", str(e), extra={'correlation_id': 'N/A'})
            raise


class NotebookRepository:
    """Repository for notebook operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        logger.info("NotebookRepository initialized with session: %s", db, extra={'correlation_id': 'N/A'})
    
    def _ensure_str_id(self, id_value: Union[str, Any]) -> Optional[str]:
        """Ensure ID is a string"""
        if id_value is None:
            return None
        return str(id_value)
    
    async def _update_notebook_timestamp(self, notebook_id: Optional[str]):
        """Update notebook's updated_at timestamp"""
        if not notebook_id:
            return
        
        try:
            stmt = update(Notebook).where(Notebook.id == notebook_id).values(
                updated_at=datetime.now(timezone.utc)
            )
            await self.db.execute(stmt)
        except SQLAlchemyError as e:
            logger.error("Error updating notebook timestamp: %s", str(e), extra={'correlation_id': 'N/A'})
            raise
    
    async def create_notebook(self, title: str, description: Optional[str] = None,
                        created_by: Optional[str] = None, tags: Optional[List[str]] = None) -> Notebook:
        """Create a new notebook in the database"""
        logger.info("Attempting to create notebook: Title='%s', Description='%s', CreatedBy='%s', Tags=%s",
                    title, description, created_by, tags, extra={'correlation_id': 'N/A'})
        try:
            from uuid import uuid4

            notebook = Notebook(
                id=str(uuid4()),
                title=title,
                description=description,
                created_by=created_by,
                tags=tags or [],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            self.db.add(notebook)
            await self.db.flush()  # Flush to get the ID before commit
            await self.db.refresh(notebook)
            logger.info("Successfully created notebook: ID='%s', Title='%s'", notebook.id, notebook.title, extra={'correlation_id': 'N/A'})
            
            return notebook
        except SQLAlchemyError as e:
            logger.error("Error creating notebook: %s", str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def get_notebook(self, notebook_id: str) -> Optional[Notebook]:
        """Get a notebook by ID with its cells and their dependencies"""
        logger.info("Fetching notebook with ID: %s", notebook_id, extra={'correlation_id': 'N/A'})
        try:
            stmt = (
                select(Notebook)
                .where(Notebook.id == notebook_id)
                # Chain selectinload for nested relationship
                .options(selectinload(Notebook.cells).selectinload(Cell.dependencies)) 
            )
            result = await self.db.execute(stmt)
            # Add .unique() before scalar_one_or_none
            notebook = result.unique().scalar_one_or_none()
            if notebook:
                logger.info("Successfully fetched notebook: ID='%s', Title='%s'", notebook.id, notebook.title, extra={'correlation_id': 'N/A'})
            else:
                logger.warning("Notebook not found: ID='%s'", notebook_id, extra={'correlation_id': 'N/A'})
            return notebook
        except SQLAlchemyError as e:
            logger.error("Error fetching notebook %s: %s", notebook_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def list_notebooks(self) -> List[Notebook]:
        """Get a list of all notebooks with their cells and dependencies"""
        logger.info("Fetching all notebooks", extra={'correlation_id': 'N/A'})
        try:
            stmt = (
                select(Notebook)
                 # Chain selectinload for nested relationship
                .options(selectinload(Notebook.cells).selectinload(Cell.dependencies))
                .order_by(Notebook.updated_at.desc()) # Example ordering
            )
            result = await self.db.execute(stmt)
            # Use unique() here as well because of the nested eager load
            notebooks = result.unique().scalars().all() 
            logger.info("Retrieved %d notebooks", len(notebooks), extra={'correlation_id': 'N/A'})
            return list(notebooks)
        except SQLAlchemyError as e:
            logger.error("Error fetching notebooks: %s", str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def list_cells_by_notebook(self, notebook_id: str) -> List[Cell]:
        """Get all cells for a specific notebook, ordered by position."""
        logger.info(f"Fetching cells for notebook ID: {notebook_id}", extra={'correlation_id': 'N/A'})
        try:
            stmt = (
                select(Cell)
                .where(Cell.notebook_id == notebook_id)
                .options(selectinload(Cell.dependencies)) # Eager load dependencies
                .order_by(Cell.position)
            )
            result = await self.db.execute(stmt)
            cells = list(result.unique().scalars().all()) # Add unique() here too
            logger.info(f"Retrieved {len(cells)} cells for notebook {notebook_id}", extra={'correlation_id': 'N/A'})
            return cells
        except SQLAlchemyError as e:
            logger.error(f"Error fetching cells for notebook {notebook_id}: {str(e)}", extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def update_notebook(self, notebook_id: str, **kwargs) -> Optional[Notebook]:
        """Update a notebook by ID"""
        logger.info("Attempting to update notebook: ID='%s', Updates=%s", notebook_id, kwargs, extra={'correlation_id': 'N/A'})
        try:
            notebook = await self.get_notebook(notebook_id) # Use get_notebook which logs
            if not notebook:
                # get_notebook already logs the 'not found' case
                return None

            # Filter kwargs to only include valid attributes of Notebook model
            valid_attrs = {k: v for k, v in kwargs.items() if hasattr(Notebook, k)}
            if not valid_attrs:
                logger.warning("No valid attributes provided for update on notebook %s", notebook_id, extra={'correlation_id': 'N/A'})
                return notebook # Return current notebook if no valid updates

            valid_attrs['updated_at'] = datetime.now(timezone.utc)
            logger.info("Valid update attributes for notebook %s: %s", notebook_id, valid_attrs, extra={'correlation_id': 'N/A'})

            # Use SQLAlchemy update statement
            stmt = update(Notebook).where(Notebook.id == notebook_id).values(**valid_attrs)
            result = await self.db.execute(stmt)
            if result.rowcount == 0:
                 logger.warning("No rows updated for notebook %s, possibly concurrent modification?", notebook_id, extra={'correlation_id': 'N/A'})
                 raise SQLAlchemyError("Update affected 0 rows.")
            logger.info("Notebook %s updated successfully with attributes: %s", notebook_id, list(valid_attrs.keys()), extra={'correlation_id': 'N/A'})

            return await self.get_notebook(notebook_id) # Fetch again to get refreshed data
        except SQLAlchemyError as e:
            logger.error("Error updating notebook %s: %s", notebook_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def delete_notebook(self, notebook_id: str) -> bool:
        """Delete a notebook"""
        logger.info("Attempting to delete notebook: ID='%s'", notebook_id, extra={'correlation_id': 'N/A'})
        try:
            notebook = await self.get_notebook(notebook_id) # Use get_notebook which logs
            if not notebook:
                # get_notebook already logs the 'not found' case
                return False

            cell_ids_to_delete = [cell.id for cell in notebook.cells]
            logger.info("Found %d cells to delete for notebook %s: %s", len(cell_ids_to_delete), notebook_id, cell_ids_to_delete, extra={'correlation_id': 'N/A'})

            if cell_ids_to_delete:
                # Delete dependencies first
                dep_delete_stmt = delete(CellDependency).where(
                    (CellDependency.dependent_id.in_(cell_ids_to_delete)) |
                    (CellDependency.dependency_id.in_(cell_ids_to_delete))
                )
                dep_result = await self.db.execute(dep_delete_stmt)
                logger.info("Deleted %d dependencies associated with notebook %s", dep_result.rowcount, notebook_id, extra={'correlation_id': 'N/A'})

                # Delete cells
                cell_delete_stmt = delete(Cell).where(Cell.notebook_id == notebook_id)
                cell_result = await self.db.execute(cell_delete_stmt)
                if cell_result.rowcount != len(cell_ids_to_delete):
                     logger.warning("Expected to delete %d cells for notebook %s, but deleted %d.", len(cell_ids_to_delete), notebook_id, cell_result.rowcount, extra={'correlation_id': 'N/A'})
                else:
                     logger.info("Deleted %d cells for notebook %s", cell_result.rowcount, notebook_id, extra={'correlation_id': 'N/A'})

            await self.db.delete(notebook) # Use session delete for cascading if configured, or manual delete works too
            logger.info("Notebook %s deleted successfully", notebook_id, extra={'correlation_id': 'N/A'})

            return True
        except SQLAlchemyError as e:
            logger.error("Error deleting notebook %s: %s", notebook_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def create_cell(self, notebook_id: str, cell_type: str, content: str,
                    position: int, 
                    tool_call_id: str,
                    connection_id: Optional[str] = None,
                    metadata: Optional[Dict] = None, 
                    settings: Optional[Dict] = None,
                    tool_name: Optional[str] = None,
                    tool_arguments: Optional[Dict[str, Any]] = None,
                    result_content: Optional[Any] = None,
                    result_error: Optional[str] = None,
                    result_execution_time: Optional[float] = None,
                    status: Optional[str] = None,
                    ) -> Optional[Cell]:
        """Create a new cell in a notebook"""
        logger.info("Attempting to create cell in notebook %s: Type='%s', Position=%d, ConnectionID='%s', Metadata=%s, Settings=%s, ToolName='%s'",
                    notebook_id, cell_type, position, connection_id, metadata, settings, tool_name, extra={'correlation_id': 'N/A'})
        try:
            # Check if notebook exists first (get_notebook logs this)
            notebook = await self.get_notebook(notebook_id)
            if not notebook:
                return None

            from uuid import uuid4

            cell = Cell(
                id=str(uuid4()),
                notebook_id=notebook_id,
                type=cell_type,
                content=content,
                position=position,
                connection_id=connection_id,
                cell_metadata=metadata or {},
                settings=settings or {},
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                result_content=result_content,
                result_error=result_error,
                result_execution_time=result_execution_time,
                result_timestamp=datetime.now(timezone.utc) if result_content is not None or result_error is not None else None,
                status=status or "idle"
            )
            
            self.db.add(cell)
            await self.db.flush()  # Flush to get the ID before commit
            await self.db.refresh(cell)
            
            # Update notebook timestamp
            await self._update_notebook_timestamp(notebook_id)
            logger.info("Successfully created cell: ID='%s' in notebook '%s'", cell.id, notebook_id, extra={'correlation_id': 'N/A'})
            
            return cell
        except SQLAlchemyError as e:
            logger.error("Error creating cell in notebook %s: %s", notebook_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def get_cell(self, cell_id: str) -> Optional[Cell]:
        """Get a cell by ID (async)"""
        logger.info("Fetching cell with ID: %s", cell_id, extra={'correlation_id': 'N/A'})
        try:
            stmt = (
                select(Cell).options(
                    joinedload(Cell.dependencies),
                    joinedload(Cell.dependents)
                ).where(Cell.id == cell_id)
            )
            result = await self.db.execute(stmt)
            cell = result.unique().scalar_one_or_none()
            
            if cell:
                logger.info("Found cell: ID='%s', Type='%s', NotebookID='%s'", cell.id, cell.type, cell.notebook_id, extra={'correlation_id': 'N/A'})
            else:
                logger.info("No cell found with ID: %s", cell_id, extra={'correlation_id': 'N/A'})
            return cell
        except SQLAlchemyError as e:
            logger.error("Error fetching cell %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def update_cell(self, cell_id: str, **kwargs) -> Optional[Cell]:
        """Update cell attributes"""
        logger.info("Attempting to update cell: ID='%s', Updates=%s", cell_id, kwargs, extra={'correlation_id': 'N/A'})
        try:
            cell = await self.get_cell(cell_id) # get_cell logs retrieval status
            if not cell:
                return None

            # Cell's notebook_id is available if needed: self._ensure_str_id(cell.notebook_id)

            # Filter kwargs to only include valid attributes of the Cell model
            valid_attrs = {k: v for k, v in kwargs.items() if hasattr(Cell, k)}
            if not valid_attrs:
                 logger.warning("No valid attributes provided for update on cell %s", cell_id, extra={'correlation_id': 'N/A'})
                 return cell # Return current cell if no valid updates

            valid_attrs['updated_at'] = datetime.now(timezone.utc)
            logger.info("Valid update attributes for cell %s: %s", cell_id, valid_attrs, extra={'correlation_id': 'N/A'})

            stmt = update(Cell).where(Cell.id == cell_id).values(**valid_attrs)
            result = await self.db.execute(stmt)
            if result.rowcount == 0:
                 logger.warning("No rows updated for cell %s, possibly concurrent modification?", cell_id, extra={'correlation_id': 'N/A'})
                 # Not necessarily an error if updates didn't change any values, but for content update it should change.
                 # For now, let's proceed, the re-fetch will confirm.
                 # raise SQLAlchemyError("Update affected 0 rows.") # Commenting out to allow no-op updates

            # Update notebook timestamp (this also executes an update)
            await self._update_notebook_timestamp(self._ensure_str_id(cell.notebook_id))
            
            # Commit the changes to the database so they are visible to subsequent queries
            # Expire the cell instance from the session.
            # The commit will be handled by the session context manager (e.g., get_db_session).
            # So, subsequent accesses within the same session scope (if any after this method returns
            # but before the context manager commits) might see cached state unless explicitly refreshed
            # or if the session is configured to auto-refresh after flush.
            # However, re-fetching via self.get_cell() after the main transaction commits is safer.
            if cell: # Ensure cell object exists before expiring
                self.db.expire(cell) 
            
            # The commit will be handled by the context manager that provided the session.
            # logger.info("Cell %s update transaction will be committed by session manager.", cell_id, extra={'correlation_id': 'N/A'})
            
            # After the calling code's session manager commits, 
            # the 'cell' instance might be expired or reflect committed state.
            # Re-fetching via self.get_cell() is the most reliable way to get the truly fresh state post-commit.
            # If 'cell' was None initially (should not happen due to prior get_cell), this would error.
            # The re-fetch via self.get_cell() is a safer way to get a fully fresh object.
            refreshed_cell = await self.get_cell(cell_id) # Re-fetch to ensure fresh state

            if refreshed_cell:
                logger.info("Cell %s updated and re-fetched successfully with attributes: %s", cell_id, list(valid_attrs.keys()), extra={'correlation_id': 'N/A'})
            else:
                # This would be unexpected if the update succeeded and cell still exists
                logger.error("Failed to re-fetch cell %s after update and commit.", cell_id, extra={'correlation_id': 'N/A'})
            return refreshed_cell
        except SQLAlchemyError as e:
            logger.error("Error updating cell %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def delete_cell(self, cell_id: str) -> bool:
        """Delete a cell"""
        logger.info("Attempting to delete cell: ID='%s'", cell_id, extra={'correlation_id': 'N/A'})
        try:
            cell = await self.get_cell(cell_id) # get_cell logs retrieval status
            if not cell:
                return False

            # Cell's notebook_id is available if needed: self._ensure_str_id(cell.notebook_id)

            # Delete the cell itself - cascade should delete dependencies
            await self.db.delete(cell) # Session delete handles the object
            logger.info("Cell %s marked for deletion", cell_id, extra={'correlation_id': 'N/A'})

            # Update notebook timestamp - this will trigger a flush which performs the delete + cascade
            await self._update_notebook_timestamp(self._ensure_str_id(cell.notebook_id))
            # Assuming commit happens in middleware or higher level function
            logger.info("Notebook timestamp updated after cell deletion request for %s", cell_id, extra={'correlation_id': 'N/A'})

            return True
        except SQLAlchemyError as e:
            logger.error("Error deleting cell %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            # Consider rolling back here if not handled by middleware
            # await self.db.rollback()
            raise
    
    async def add_dependency(self, dependent_id: str, dependency_id: str) -> bool:
        """Add a dependency between cells"""
        logger.info("Attempting to add dependency: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})
        try:
            dependent = await self.get_cell(dependent_id) # get_cell logs retrieval
            dependency = await self.get_cell(dependency_id) # get_cell logs retrieval

            if not dependent or not dependency:
                logger.error("Cannot add dependency: One or both cells not found (Dependent: %s, Dependency: %s)",
                             'Found' if dependent else 'Not Found', 'Found' if dependency else 'Not Found', extra={'correlation_id': 'N/A'})
                return False

            # Check if dependent and dependency are in the same notebook
            dep_notebook_id = self._ensure_str_id(dependent.notebook_id)
            dependency_notebook_id = self._ensure_str_id(dependency.notebook_id)
            if dep_notebook_id != dependency_notebook_id:
                logger.error("Cannot add dependency: Cells belong to different notebooks ('%s' vs '%s')",
                             dep_notebook_id, dependency_notebook_id, extra={'correlation_id': 'N/A'})
                return False

            # Extract notebook_id for timestamp update
            notebook_id = dep_notebook_id

            # Corrected: Check if dependency already exists using execute/select
            existing_dep_stmt = select(CellDependency).where(
                and_(
                    CellDependency.dependent_id == dependent_id, 
                    CellDependency.dependency_id == dependency_id
                )
            )
            existing_result = await self.db.execute(existing_dep_stmt)
            if existing_result.scalar_one_or_none() is not None:
                logger.info("Dependency already exists: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})
                return True

            new_dependency = CellDependency(dependent_id=dependent_id, dependency_id=dependency_id)
            self.db.add(new_dependency)
            
            # Update dependent cell status using async update_cell
            await self.update_cell(dependent_id, status=CellStatus.STALE.value)
            logger.info("Marked dependent cell %s as stale after adding dependency", dependent_id, extra={'correlation_id': 'N/A'})
            
            await self._update_notebook_timestamp(notebook_id)
            logger.info("Dependency added successfully: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})

            return True
        except SQLAlchemyError as e:
            logger.error("Error adding dependency between %s and %s: %s", dependent_id, dependency_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def remove_dependency(self, dependent_id: str, dependency_id: str) -> bool:
        """Remove a dependency between cells"""
        logger.info("Attempting to remove dependency: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})
        try:
            # Get dependent cell to find notebook ID (get_cell logs retrieval)
            dependent = await self.get_cell(dependent_id)
            if not dependent:
                logger.warning("Cannot remove dependency: Dependent cell %s not found", dependent_id, extra={'correlation_id': 'N/A'})
                return False

            # Extract notebook_id for timestamp update
            notebook_id = self._ensure_str_id(dependent.notebook_id)

            stmt = delete(CellDependency).where(
                and_(
                    CellDependency.dependent_id == dependent_id,
                    CellDependency.dependency_id == dependency_id
                )
            )
            result = await self.db.execute(stmt)

            if result.rowcount == 0:
                logger.warning("Dependency not found for removal: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})
                return False

            # Potentially mark dependent as stale after removing dependency?
            # await self.update_cell(dependent_id, status=CellStatus.STALE.value)
            # logger.info("Marked dependent cell %s as stale after removing dependency", dependent_id, extra={'correlation_id': 'N/A'})
                 
            await self._update_notebook_timestamp(notebook_id)
            logger.info("Dependency removed successfully: Dependent='%s' -> Dependency='%s'", dependent_id, dependency_id, extra={'correlation_id': 'N/A'})

            return True
        except SQLAlchemyError as e:
            logger.error("Error removing dependency between %s and %s: %s", dependent_id, dependency_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def set_cell_result(self, cell_id: str, content: Any, error: Optional[str] = None, 
                        execution_time: float = 0.0) -> Optional[Cell]:
        """Set the execution result for a cell"""
        logger.info("Setting result for cell %s", cell_id, extra={'correlation_id': 'N/A'})
        try:
            cell = await self.get_cell(cell_id)
            if not cell:
                logger.info("Cannot set result: Cell ID %s not found", cell_id, extra={'correlation_id': 'N/A'})
                return None
            
            # Cell's notebook_id is available if needed: self._ensure_str_id(cell.notebook_id)
            
            updates = {
                'result_content': content,
                'result_error': error,
                'result_execution_time': execution_time,
                'result_timestamp': datetime.now(timezone.utc),
                'status': CellStatus.ERROR.value if error else CellStatus.SUCCESS.value
            }
            
            updated_cell = await self.update_cell(cell_id, **updates)
            
            if updated_cell:
                 logger.info("Cell result set successfully for cell %s", cell_id, extra={'correlation_id': 'N/A'})
            else:
                 logger.warning("Failed to update cell %s after setting result (update_cell returned None)", cell_id, extra={'correlation_id': 'N/A'})
                 
            return updated_cell
        except SQLAlchemyError as e:
            logger.error("Error setting cell result for %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def mark_cell_stale(self, cell_id: str) -> Optional[Cell]:
        """Mark a cell as stale"""
        logger.info("Marking cell %s as stale", cell_id, extra={'correlation_id': 'N/A'})
        try:
            cell = await self.get_cell(cell_id)
            if not cell:
                logger.info("Cannot mark cell stale: ID %s not found", cell_id, extra={'correlation_id': 'N/A'})
                return None
            
            # Cell's notebook_id is available if needed: self._ensure_str_id(cell.notebook_id)
            
            updated_cell = await self.update_cell(cell_id, status=CellStatus.STALE.value)
            if not updated_cell:
                 logger.warning("Failed to update cell %s status to stale (update_cell returned None)", cell_id, extra={'correlation_id': 'N/A'})
                 return None
            
            dependents = await self.get_dependents(cell_id)
            for dependent in dependents:
                dependent_id = self._ensure_str_id(dependent.id)
                if dependent_id and dependent_id != cell_id:  
                    await self.mark_cell_stale(dependent_id)
            
            logger.info("Cell %s marked as stale", cell_id, extra={'correlation_id': 'N/A'})
            
            return updated_cell
        except SQLAlchemyError as e:
            logger.error("Error marking cell %s stale: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def get_dependents(self, cell_id: str) -> List[Cell]:
        """Get all cells that depend on this cell (async)"""
        logger.info("Getting dependents of cell %s", cell_id, extra={'correlation_id': 'N/A'})
        try:
            # Fetch the cell and explicitly load its 'dependents' relationship
            stmt = select(Cell).options(joinedload(Cell.dependents)).where(Cell.id == cell_id)
            result = await self.db.execute(stmt)
            cell = result.scalar_one_or_none()
            
            if cell and hasattr(cell, 'dependents'):
                dependents = list(cell.dependents)
                logger.info("Found %d dependents for cell %s", len(dependents), cell_id, extra={'correlation_id': 'N/A'})
                return dependents
            else:
                 logger.info("Cell %s not found or has no loaded dependents relation.", cell_id, extra={'correlation_id': 'N/A'})
                 return [] # Return empty list if cell not found or relation not loaded
                 
        except SQLAlchemyError as e:
            logger.error("Error getting dependents for cell %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def get_dependencies(self, cell_id: str) -> List[Cell]:
        """Get all cells this cell depends on (async)"""
        logger.info("Getting dependencies of cell %s", cell_id, extra={'correlation_id': 'N/A'})
        try:
            # Fetch the cell and explicitly load its 'dependencies' relationship
            stmt = select(Cell).options(joinedload(Cell.dependencies)).where(Cell.id == cell_id)
            result = await self.db.execute(stmt)
            cell = result.scalar_one_or_none()
            
            if cell and hasattr(cell, 'dependencies'):
                dependencies = list(cell.dependencies)
                logger.info("Found %d dependencies for cell %s", len(dependencies), cell_id, extra={'correlation_id': 'N/A'})
                return dependencies
            else:
                 logger.info("Cell %s not found or has no loaded dependencies relation.", cell_id, extra={'correlation_id': 'N/A'})
                 return [] # Return empty list
                 
        except SQLAlchemyError as e:
            logger.error("Error getting dependencies for cell %s: %s", cell_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
    
    async def reorder_cells(self, notebook_id: str, cell_order: List[str]) -> bool:
        """Update the order of cells in a notebook"""
        logger.info("Reordering cells in notebook %s", notebook_id, extra={'correlation_id': 'N/A'})
        try:
            notebook = await self.get_notebook(notebook_id)
            if not notebook:
                logger.info("Cannot reorder cells: Notebook ID %s not found", notebook_id, extra={'correlation_id': 'N/A'})
                return False
            
            # Corrected: Validate that all cells exist using execute/select
            existing_cells_stmt = select(Cell.id).where(Cell.notebook_id == notebook_id)
            existing_cells_result = await self.db.execute(existing_cells_stmt)
            current_cell_ids = {str(cell_id_tuple[0]) for cell_id_tuple in existing_cells_result.fetchall()} # Fetch all IDs
            
            if not set(cell_order).issubset(current_cell_ids):
                missing_ids = set(cell_order) - current_cell_ids
                logger.error(f"Cannot reorder cells: Invalid or missing cell IDs provided: {missing_ids}")
                return False

            for index, cell_id in enumerate(cell_order):
                stmt = update(Cell).where(Cell.id == cell_id).values(position=index)
                await self.db.execute(stmt)
                
            await self._update_notebook_timestamp(notebook_id)
            logger.info("Cells reordered successfully in notebook %s", notebook_id, extra={'correlation_id': 'N/A'})
            
            return True
        except SQLAlchemyError as e:
            logger.error("Error reordering cells in notebook %s: %s", notebook_id, str(e), extra={'correlation_id': 'N/A'}, exc_info=True)
            raise
