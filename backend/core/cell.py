"""
Cell Module for Sherlog Canvas

This module defines the core cell types and their functionality for the Sherlog Canvas
notebook system. It provides a flexible cell model that supports different data sources
and query types.

Key components:
- Cell class: Base class for all cell types with common functionality
- MarkdownCell: For documentation and text content
- ToolCell: For all tool-based operations (replaces all specific cell types)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Any, Dict, Optional, Set
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# Import ToolCallID
from backend.core.dependency import ToolCallID

# Initialize logger
cell_logger = logging.getLogger("cell")

class CellStatus(str, Enum):
    """
    Enumeration of possible cell execution states
    
    Attributes:
        IDLE: Cell has not been executed yet
        QUEUED: Cell is queued for execution
        RUNNING: Cell is currently executing
        SUCCESS: Cell executed successfully
        ERROR: Cell execution resulted in an error
        STALE: Cell needs to be re-executed due to dependency changes
    """
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    STALE = "stale"


class CellType(str, Enum):
    """
    Enumeration of supported cell types
    
    Attributes:
        MARKDOWN: Cell containing markdown text
        TOOL: Cell representing any tool operation (GitHub, Python, Filesystem, etc.)
    """
    MARKDOWN = "markdown"
    TOOL = "tool"


class CellResult(BaseModel):
    """
    The result of a cell execution
    
    Attributes:
        content: The primary result data (can be any type)
        error: Optional error message if execution failed
        execution_time: Time taken to execute the cell in seconds
        timestamp: When the result was generated
    """
    content: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Cell(BaseModel):
    """
    Base class for all notebook cells
    
    Attributes:
        id: Unique identifier for the cell
        type: The type of cell (MARKDOWN or TOOL)
        content: The cell's content (code, query, markdown, etc.)
        result: Optional result from cell execution
        status: Current execution status
        created_at: When the cell was created
        updated_at: When the cell was last updated
        dependencies: Set of cell IDs this cell depends on
        dependents: Set of cell IDs that depend on this cell
        tool_call_id: Optional ID for the specific tool call this cell represents
        tool_name: Name of the tool called (for TOOL cells)
        tool_arguments: Arguments passed to the tool (for TOOL cells)
        metadata: Additional cell metadata
        connection_id: ID of the connection to use (if applicable)
    """
    id: UUID = Field(default_factory=uuid4)
    type: CellType
    content: str
    result: Optional[CellResult] = None
    status: CellStatus = CellStatus.IDLE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    connection_id: Optional[str] = Field(default=None, description="ID of the associated connection, if any")
    
    # Dependency handling
    dependencies: Set[UUID] = Field(default_factory=set)
    dependents: Set[UUID] = Field(default_factory=set)
    
    # Tool call info (for TOOL cells)
    tool_call_id: ToolCallID = Field(default_factory=uuid4)
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Settings for cell execution
    settings: Dict[str, Any] = Field(default_factory=dict)
    
    def __init__(self, **data):
        # Map legacy cell types to TOOL type
        if 'type' in data and data['type'] not in ["markdown", "tool"]:
            # Store the original type in metadata for display purposes
            if 'metadata' not in data:
                data['metadata'] = {}
            data['metadata']['original_type'] = data['type']
            data['type'] = CellType.TOOL
            # Also set tool_name if not already set
            if 'tool_name' not in data or not data['tool_name']:
                data['tool_name'] = data['metadata']['original_type']
        
        super().__init__(**data)
        cell_logger.debug(
            "Cell initialized",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'tool_name': self.tool_name,
                'connection_id': self.connection_id
            }
        )
    
    def mark_stale(self) -> None:
        """Mark this cell as stale (needs re-execution)"""
        start_time = time.time()
        if self.status != CellStatus.STALE:
            self.status = CellStatus.STALE
            self.updated_at = datetime.now(timezone.utc)
            process_time = time.time() - start_time
            cell_logger.debug(
                "Cell marked as stale",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
    
    def update_content(self, content: str) -> None:
        """
        Update the cell content and mark as stale
        
        Args:
            content: The new content for the cell
        """
        start_time = time.time()
        self.content = content
        self.updated_at = datetime.now(timezone.utc)
        self.mark_stale()
        process_time = time.time() - start_time
        cell_logger.debug(
            "Cell content updated",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'content_length': len(content),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def set_result(self, result: Any, error: Optional[str] = None, execution_time: float = 0.0) -> None:
        """
        Set the execution result for this cell
        
        Args:
            result: The result data
            error: Optional error message
            execution_time: Time taken to execute the cell
        """
        start_time = time.time()
        self.result = CellResult(
            content=result,
            error=error,
            execution_time=execution_time,
            timestamp=datetime.now(timezone.utc)
        )
        self.status = CellStatus.ERROR if error else CellStatus.SUCCESS
        self.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        cell_logger.debug(
            "Cell result set",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'status': str(self.status),
                'execution_time': execution_time,
                'has_error': error is not None,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        if error:
            cell_logger.error(
                "Cell execution error",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'error': error
                }
            )
    
    def add_dependency(self, cell_id: UUID) -> None:
        """
        Add a dependency on another cell
        
        Args:
            cell_id: ID of the cell this cell depends on
        """
        start_time = time.time()
        self.dependencies.add(cell_id)
        process_time = time.time() - start_time
        cell_logger.debug(
            "Added cell dependency",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'dependency_id': str(cell_id),
                'total_dependencies': len(self.dependencies),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def add_dependent(self, cell_id: UUID) -> None:
        """
        Add a cell that depends on this cell
        
        Args:
            cell_id: ID of the dependent cell
        """
        start_time = time.time()
        self.dependents.add(cell_id)
        process_time = time.time() - start_time
        cell_logger.debug(
            "Added cell dependent",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'dependent_id': str(cell_id),
                'total_dependents': len(self.dependents),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def remove_dependency(self, cell_id: UUID) -> None:
        """
        Remove a dependency on another cell
        
        Args:
            cell_id: ID of the dependency to remove
        """
        start_time = time.time()
        if cell_id in self.dependencies:
            self.dependencies.remove(cell_id)
            process_time = time.time() - start_time
            cell_logger.debug(
                "Removed cell dependency",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'dependency_id': str(cell_id),
                    'total_dependencies': len(self.dependencies),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
        else:
            process_time = time.time() - start_time
            cell_logger.warning(
                "Attempted to remove non-existent dependency",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'dependency_id': str(cell_id),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
    
    def remove_dependent(self, cell_id: UUID) -> None:
        """
        Remove a cell that depends on this cell
        
        Args:
            cell_id: ID of the dependent to remove
        """
        start_time = time.time()
        if cell_id in self.dependents:
            self.dependents.remove(cell_id)
            process_time = time.time() - start_time
            cell_logger.debug(
                "Removed cell dependent",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'dependent_id': str(cell_id),
                    'total_dependents': len(self.dependents),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
        else:
            process_time = time.time() - start_time
            cell_logger.warning(
                "Attempted to remove non-existent dependent",
                extra={
                    'cell_id': str(self.id),
                    'cell_type': str(self.type),
                    'dependent_id': str(cell_id),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
    
    def clear_dependencies(self) -> None:
        """Clear all dependencies"""
        start_time = time.time()
        num_dependencies = len(self.dependencies)
        self.dependencies.clear()
        process_time = time.time() - start_time
        cell_logger.debug(
            "Cleared all dependencies",
            extra={
                'cell_id': str(self.id),
                'cell_type': str(self.type),
                'dependencies_cleared': num_dependencies,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )


class MarkdownCell(Cell):
    """
    A cell containing markdown content
    
    This cell type is used for documentation and explanations.
    """
    type: CellType = CellType.MARKDOWN
    
    def __init__(self, **data):
        super().__init__(**data)
        cell_logger.debug(
            "Markdown cell initialized",
            extra={
                'cell_id': str(self.id),
                'content_length': len(self.content)
            }
        )
    
    class Config:
        schema_extra = {
            "example": {
                "content": "# Analysis Results\nThe query found **15 users** who registered in the last 24 hours."
            }
        }


class ToolCell(Cell):
    """
    A cell representing any tool operation (GitHub, Python, Filesystem, etc.)
    
    This unified cell type replaces all specific tool cell types.
    The tool_name field indicates which tool is being used.
    """
    type: CellType = CellType.TOOL
    
    def __init__(self, **data):
        # Ensure tool_name is set for tool cells
        if 'tool_name' not in data or not data['tool_name']:
            # Try to infer from metadata if available
            if 'metadata' in data and 'original_type' in data['metadata']:
                data['tool_name'] = data['metadata']['original_type']
        
        super().__init__(**data)
        cell_logger.debug(
            "Tool cell initialized",
            extra={
                'cell_id': str(self.id),
                'tool_name': self.tool_name,
                'has_arguments': bool(self.tool_arguments)
            }
        )


# For backward compatibility, keep these as aliases
GitHubCell = ToolCell
SummarizationCell = ToolCell


def create_cell(cell_type: str, content: str, **kwargs) -> Cell:
    """
    Create a new cell of the specified type
    
    Args:
        cell_type: The type of cell to create (as string)
        content: Initial content for the cell
        **kwargs: Additional arguments to pass to the cell constructor
        
    Returns:
        A new cell instance of the appropriate type
    """
    start_time = time.time()
    
    try:
        # Normalize cell type
        if cell_type not in ["markdown", "tool"]:
            # Store original type in metadata
            if 'metadata' not in kwargs:
                kwargs['metadata'] = {}
            kwargs['metadata']['original_type'] = cell_type
            
            # Map to TOOL type
            actual_type = CellType.TOOL
            
            # Set tool_name if not already provided
            if 'tool_name' not in kwargs:
                kwargs['tool_name'] = cell_type
        else:
            actual_type = CellType(cell_type)
        
        # Create the cell
        if actual_type == CellType.MARKDOWN:
            cell = MarkdownCell(content=content, **kwargs)
        else:
            cell = ToolCell(content=content, **kwargs)
        
        process_time = time.time() - start_time
        cell_logger.debug(
            "Cell created",
            extra={
                'cell_id': str(cell.id),
                'cell_type': str(actual_type),
                'original_type': str(cell_type),
                'content_length': len(content),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        return cell
    except Exception as e:
        process_time = time.time() - start_time
        cell_logger.error(
            "Error creating cell",
            extra={
                'cell_type': str(cell_type),
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise