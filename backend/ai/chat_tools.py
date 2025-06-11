"""
Chat Agent Tools

This module defines tools that allow the AI agent to manage notebook cells.
"""

from typing import Dict, List, Optional, Any, Callable
from uuid import UUID
from dataclasses import dataclass

import logging
from pydantic import BaseModel, Field

from backend.core.cell import CellType, CellResult, CellStatus
from backend.core.types import ToolCallID
from backend.services.notebook_manager import NotebookManager
from backend.db.database import get_db_session

# Initialize logger
tools_logger = logging.getLogger("ai.chat_tools")

# Add correlation ID filter to the logger
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

tools_logger.addFilter(CorrelationIdFilter())


class CreateCellParams(BaseModel):
    """Parameters for creating a cell"""
    notebook_id: str = Field(description="The UUID of the notebook")
    cell_type: str = Field(description="Type of cell to create: markdown, python, sql, log, metric, s3, ai_query")
    content: str = Field(description="Content for the cell (query, code, text)")
    position: Optional[int] = Field(description="Position to insert the cell (optional)", default=None)
    metadata: Optional[Dict[str, Any]] = Field(description="Additional metadata for the cell", default=None)
    dependencies: Optional[List[UUID]] = Field(description="List of cell UUIDs this cell depends on", default=None)
    tool_call_id: ToolCallID = Field(description="ID of the associated tool call (Generated UUID)")
    tool_name: Optional[str] = Field(description="Name of the tool called", default=None)
    tool_arguments: Optional[Dict[str, Any]] = Field(description="Arguments passed to the tool", default=None)
    result: Optional[CellResult] = Field(description="Pre-computed result for the cell (e.g., structured report data)", default=None)
    status: Optional[CellStatus] = Field(description="Initial status for the cell", default=None)
    connection_id: Optional[str] = Field(description="ID of the data source connection to use (e.g., for GitHub)", default=None)


class UpdateCellParams(BaseModel):
    """Parameters for updating a cell"""
    notebook_id: str = Field(description="The UUID of the notebook")
    cell_id: str = Field(description="The UUID of the cell to update")
    content: Optional[str] = Field(description="New content for the cell", default=None)
    metadata: Optional[Dict[str, Any]] = Field(description="Updated metadata for the cell", default=None)


class ExecuteCellParams(BaseModel):
    """Parameters for executing a cell"""
    notebook_id: str = Field(description="The UUID of the notebook")
    cell_id: str = Field(description="The UUID of the cell to execute")


class ListCellsParams(BaseModel):
    """Parameters for listing cells"""
    notebook_id: str = Field(description="The UUID of the notebook")


class GetCellParams(BaseModel):
    """Parameters for getting a cell"""
    notebook_id: str = Field(description="The UUID of the notebook")
    cell_id: str = Field(description="The UUID of the cell to get")


class ExecuteAIQueryParams(BaseModel):
    """Parameters for executing an AI query"""
    notebook_id: str = Field(description="The UUID of the notebook")
    query: str = Field(description="The query to execute")
    position: Optional[int] = Field(description="Position to insert the cell (optional)", default=None)


@dataclass
class Tool:
    name: str
    function: Callable[..., Any]
    description: str = ""

    def __call__(self, *args, **kwargs):
        return self.function(*args, **kwargs)


class NotebookCellTools:
    """
    Tools for the AI agent to manage notebook cells.
    """
    def __init__(self, notebook_manager: NotebookManager):
        self.notebook_manager = notebook_manager
        
        # Create tool for creating cells
        create_cell_tool = Tool(name="create_cell", function=self.create_cell)
        create_cell_tool.description = "Create a new cell in a notebook"
        
        # Create tool for updating cells
        update_cell_tool = Tool(name="update_cell", function=self.update_cell)
        update_cell_tool.description = "Update an existing cell in a notebook"
        
        # Create tool for executing cells
        execute_cell_tool = Tool(name="execute_cell", function=self.execute_cell)
        execute_cell_tool.description = "Queue a cell for execution"
        
        # Create tool for listing cells
        list_cells_tool = Tool(name="list_cells", function=self.list_cells)
        list_cells_tool.description = "List all cells in a notebook"
        
        # Create tool for getting cell details
        get_cell_tool = Tool(name="get_cell", function=self.get_cell)
        get_cell_tool.description = "Get a specific cell by ID"
        
        # Store all tools in a list
        self.tools = [
            create_cell_tool,
            # Temporarily disable registration of other tools
            # update_cell_tool, 
            # execute_cell_tool, 
            list_cells_tool, # Re-enable list_cells
            # get_cell_tool,
        ]
    
    def get_tools(self) -> List[Tool]:
        """Get all available tools"""
        return self.tools
    
    def get_raw_tools(self, notebook_id: Optional[str] = None) -> List[Callable]:
        """Get raw functions for Agno agents"""
        # Capture the notebook_id in the closure
        captured_notebook_id = notebook_id
        
        # Create wrapper functions that Agno can use
        async def create_cell(
            cell_type: str,
            content: str,
            position: Optional[int] = None,
            metadata: Optional[Dict[str, Any]] = None,
            tool_call_id: Optional[str] = None,
            notebook_id: Optional[str] = None
        ) -> Dict:
            """Create a new cell in a notebook
            
            Args:
                cell_type: Type of cell to create (markdown, python, sql, log, metric, s3, ai_query)
                content: Content for the cell
                position: Position to insert the cell (optional)
                metadata: Additional metadata for the cell (optional)
                tool_call_id: ID of the tool call (optional, will be generated if not provided)
                notebook_id: The UUID of the notebook (optional, uses captured notebook_id if not provided)
            
            Returns:
                Dict with success status and cell details
            """
            import uuid
            # Use the provided notebook_id or fall back to the captured one
            actual_notebook_id = notebook_id or captured_notebook_id
            if not actual_notebook_id:
                return {
                    "success": False,
                    "error": "notebook_id is required but was not provided"
                }
            
            params = CreateCellParams(
                notebook_id=actual_notebook_id,
                cell_type=cell_type,
                content=content,
                position=position,
                metadata=metadata,
                tool_call_id=tool_call_id or str(uuid.uuid4())
            )
            return await self.create_cell(params)
        
        async def list_cells(notebook_id: Optional[str] = None) -> Dict:
            """List all cells in a notebook
            
            Args:
                notebook_id: The UUID of the notebook (optional, uses captured notebook_id if not provided)
                
            Returns:
                Dict with list of cells
            """
            # Use the provided notebook_id or fall back to the captured one
            actual_notebook_id = notebook_id or captured_notebook_id
            if not actual_notebook_id:
                return {
                    "success": False,
                    "error": "notebook_id is required but was not provided"
                }
            
            params = ListCellsParams(notebook_id=actual_notebook_id)
            return await self.list_cells(params)
        
        return [create_cell, list_cells]
    
    async def create_cell(self, params: CreateCellParams, **kwargs) -> Dict:
        """Create a new cell in a notebook (using async session)"""
        async with get_db_session() as db:
            try:
                notebook_id = UUID(params.notebook_id)
                tools_logger.info(f"Creating cell in notebook: {notebook_id}")
                cell_type = getattr(CellType, params.cell_type.upper())
                cell_metadata = params.metadata or {}
                if 'tool_name' in kwargs:
                    cell_metadata['tool_name'] = kwargs['tool_name']
                if 'tool_arguments' in kwargs:
                    cell_metadata['tool_arguments'] = kwargs['tool_arguments']

                cell = await self.notebook_manager.create_cell(
                    db=db, 
                    notebook_id=notebook_id,
                    cell_type=cell_type,
                    content=params.content,
                    position=params.position,
                    metadata=cell_metadata,
                    dependencies=params.dependencies,
                    tool_call_id=params.tool_call_id,
                    tool_name=params.tool_name,
                    tool_arguments=params.tool_arguments,
                    result=params.result,
                    status=params.status,
                    connection_id=params.connection_id
                )
                
                tools_logger.info(f"Created cell {cell.id} in notebook {notebook_id}")
                return {
                    "success": True,
                    "notebook_id": str(notebook_id),
                    "cell_id": str(cell.id),
                    "cell_type": params.cell_type,
                    "position": params.position
                }
            except Exception as e:
                tools_logger.error(f"Error creating cell: {str(e)}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e)
                }
    
    async def update_cell(self, params: UpdateCellParams) -> Dict:
        """Update an existing cell in a notebook"""
        # Temporarily disabled
        return {"success": False, "error": "Update cell tool temporarily disabled"}
        # db_gen = get_db()
        # db: Session = next(db_gen)
        # ... (original implementation commented out) ...
   
    async def execute_cell(self, params: ExecuteCellParams) -> Dict:
        """Queue a cell for execution"""
        # Temporarily disabled
        return {"success": False, "error": "Execute cell tool temporarily disabled"}
        # db_gen = get_db()
        # db: Session = next(db_gen)
        # ... (original implementation commented out) ...
   
    async def list_cells(self, params: ListCellsParams) -> Dict:
        """List all cells in a notebook, providing detailed information."""
        async with get_db_session() as db:
            try:
                notebook_id_uuid = UUID(params.notebook_id)
                tools_logger.info(f"Listing cells for notebook: {notebook_id_uuid}")
                
                # Fetch the entire notebook object, which contains the cells
                notebook = await self.notebook_manager.get_notebook(db=db, notebook_id=notebook_id_uuid)
                
                cells_data = list(notebook.cells.values()) # Get list of Cell models

                detailed_cells = []
                if cells_data:
                    for cell_model in cells_data: # Iterate over Cell Pydantic models
                        # Safely access attributes from the Cell Pydantic model
                        cell_id = str(getattr(cell_model, 'id', None))
                        cell_type_enum = getattr(cell_model, 'type', None)
                        content = getattr(cell_model, 'content', None)
                        metadata = getattr(cell_model, 'metadata', {}) # metadata is 'cell_metadata' in Cell model
                        if not metadata: # Fallback if 'cell_metadata' was intended from DB layer
                             metadata = getattr(cell_model, 'cell_metadata', {})

                        status_enum = getattr(cell_model, 'status', None)
                        result_obj: Optional[CellResult] = getattr(cell_model, 'result', None)
                        created_at_dt = getattr(cell_model, 'created_at', None)
                        updated_at_dt = getattr(cell_model, 'updated_at', None)

                        # Process result (output)
                        output_details = None
                        if result_obj and isinstance(result_obj, CellResult):
                            output_details = {
                                # 'content' is the primary store for outputs (stdout, structured data)
                                "content": result_obj.content, 
                                "error": result_obj.error,
                                "execution_time": result_obj.execution_time,
                                # Use result_obj.timestamp for when the result was generated
                                "timestamp": result_obj.timestamp.isoformat() if result_obj.timestamp else None
                            }
                        elif isinstance(result_obj, dict): # If result was stored as a dict somehow (less likely for CellResult)
                            output_details = result_obj


                        detailed_cells.append({
                            "id": cell_id,
                            "cell_type": cell_type_enum.value if cell_type_enum else None,
                            "content": content,
                            "metadata": metadata,
                            "status": status_enum.value if status_enum else None,
                            "output": output_details, 
                            "created_at": created_at_dt.isoformat() if created_at_dt else None,
                            "updated_at": updated_at_dt.isoformat() if updated_at_dt else None,
                            # Include dependencies and tool info from Cell model directly
                            "dependencies": [str(dep_id) for dep_id in getattr(cell_model, 'dependencies', set())],
                            "tool_call_id": str(getattr(cell_model, 'tool_call_id', None)),
                            "tool_name": getattr(cell_model, 'tool_name', None),
                            "tool_arguments": getattr(cell_model, 'tool_arguments', None),
                            "connection_id": getattr(cell_model, 'connection_id', None)
                        })
                
                tools_logger.info(f"Found {len(detailed_cells)} cells for notebook {notebook_id_uuid}")
                return {
                    "success": True,
                    "notebook_id": params.notebook_id,
                    "cells": detailed_cells
                }
            except Exception as e:
                tools_logger.error(f"Error listing cells for notebook {params.notebook_id}: {str(e)}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e),
                    "notebook_id": params.notebook_id,
                    "cells": []
                }
   
    async def get_cell(self, params: GetCellParams) -> Dict:
        """Get a specific cell by ID"""
        # Temporarily disabled
        return {"success": False, "error": "Get cell tool temporarily disabled"}
        # db_gen = get_db()
        # db: Session = next(db_gen)
        # ... (original implementation commented out) ...

# Temporarily removed update_cell, execute_cell, list_cells, get_cell methods 