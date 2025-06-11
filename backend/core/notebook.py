from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.core.cell import Cell, CellType, create_cell
from backend.core.dependency import DependencyGraph

# Initialize logger
notebook_logger = logging.getLogger("notebook")

class NotebookMetadata(BaseModel):
    """Metadata for a notebook"""
    title: str = "Untitled Investigation"
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Notebook(BaseModel):
    """
    A notebook containing a collection of cells with dependencies.
    Manages cell creation, updates, and execution.
    """
    id: UUID = Field(default_factory=uuid4)
    metadata: NotebookMetadata = Field(default_factory=NotebookMetadata)
    cells: Dict[UUID, Cell] = Field(default_factory=dict)
    cell_order: List[UUID] = Field(default_factory=list)
    dependency_graph: DependencyGraph = Field(default_factory=DependencyGraph)
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        notebook_logger.debug(
            "Notebook initialized",
            extra={
                'notebook_id': str(self.id),
                'title': self.metadata.title,
                'cells_count': len(self.cells)
            }
        )
    
    def add_cell(self, cell: Cell, position: Optional[int] = None) -> Cell:
        """
        Add a cell to the notebook
        
        Args:
            cell: The cell to add
            position: Optional position in the cell order (default: append to end)
        
        Returns:
            The added cell
        """
        start_time = time.time()
        
        self.cells[cell.id] = cell
        self.dependency_graph.add_cell(cell)
        
        # Update cell order
        if position is not None and 0 <= position <= len(self.cell_order):
            self.cell_order.insert(position, cell.id)
        else:
            self.cell_order.append(cell.id)
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Cell added to notebook",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell.id),
                'cell_type': cell.type.value,
                'position': position if position is not None else len(self.cell_order) - 1,
                'cells_count': len(self.cells),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        return cell
    
    def create_cell(
        self, 
        cell_type: CellType,
        content: str,
        dependencies: Optional[List[UUID]] = None,
        position: Optional[int] = None,
        **kwargs
    ) -> Cell:
        """
        Create a new cell and add it to the notebook
        
        Args:
            cell_type: Type of cell to create
            content: Content for the cell
            dependencies: Optional list of cell IDs this cell depends on
            position: Optional position in the cell order
            **kwargs: Additional arguments for the specific cell type
        
        Returns:
            The created cell
        """
        start_time = time.time()
        
        cell = create_cell(cell_type, content, **kwargs)
        
        notebook_logger.info(
            "Creating new cell",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell.id),
                'cell_type': cell_type.value,
                'dependencies_count': len(dependencies) if dependencies else 0,
                'position': position
            }
        )
        
        # Add dependencies if provided
        if dependencies:
            for dep_id in dependencies:
                try:
                    self.add_dependency(cell.id, dep_id)
                except ValueError as e:
                    notebook_logger.warning(
                        "Failed to add dependency",
                        extra={
                            'notebook_id': str(self.id),
                            'cell_id': str(cell.id),
                            'dependency_id': str(dep_id),
                            'error': str(e)
                        }
                    )
        
        result = self.add_cell(cell, position)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Cell creation completed",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell.id),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        return result
    
    def get_cell(self, cell_id: UUID) -> Cell:
        """Get a cell by ID"""
        if cell_id not in self.cells:
            notebook_logger.error(
                "Cell not found",
                extra={
                    'notebook_id': str(self.id),
                    'cell_id': str(cell_id)
                }
            )
            raise ValueError(f"Cell not found: {cell_id}")
        return self.cells[cell_id]
    
    def remove_cell(self, cell_id: UUID) -> None:
        """Remove a cell from the notebook"""
        start_time = time.time()
        
        if cell_id not in self.cells:
            notebook_logger.error(
                "Cannot remove cell: not found",
                extra={
                    'notebook_id': str(self.id),
                    'cell_id': str(cell_id)
                }
            )
            raise ValueError(f"Cell not found: {cell_id}")
        
        # Get cell info for logging
        cell = self.cells[cell_id]
        dependencies_count = len(cell.dependencies) if hasattr(cell, 'dependencies') else 0
        dependents_count = len(cell.dependents) if hasattr(cell, 'dependents') else 0
        
        # Remove from cells dict
        self.cells.pop(cell_id)
        
        # Remove from cell order
        if cell_id in self.cell_order:
            self.cell_order.remove(cell_id)
        
        # Remove from dependency graph
        self.dependency_graph.remove_cell(cell_id)
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Cell removed",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell_id),
                'cell_type': cell.type.value,
                'dependencies_count': dependencies_count,
                'dependents_count': dependents_count,
                'remaining_cells': len(self.cells),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def update_cell_content(self, cell_id: UUID, content: str) -> Cell:
        """
        Update a cell's content and mark it and its dependents as stale
        
        Args:
            cell_id: ID of the cell to update
            content: New content for the cell
        
        Returns:
            The updated cell
        """
        start_time = time.time()
        
        cell = self.get_cell(cell_id)
        cell.update_content(content)
        
        # Mark all dependent cells as stale
        stale_cells = self.mark_dependents_stale(cell_id)
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Cell content updated",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell_id),
                'cell_type': cell.type.value,
                'stale_dependents': len(stale_cells),
                'content_length': len(content),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        return cell
    
    def update_cell_metadata(self, cell_id: UUID, metadata: Dict) -> Cell:
        """Update a cell's metadata"""
        start_time = time.time()
        
        cell = self.get_cell(cell_id)
        cell.cell_metadata.update(metadata)
        cell.updated_at = datetime.now(timezone.utc)
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Cell metadata updated",
            extra={
                'notebook_id': str(self.id),
                'cell_id': str(cell_id),
                'cell_type': cell.type.value,
                'updated_fields': list(metadata.keys()),
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        
        return cell
    
    def add_dependency(self, dependent_id: UUID, dependency_id: UUID) -> None:
        """
        Add a dependency relationship between cells
        
        Args:
            dependent_id: ID of the cell that depends on another
            dependency_id: ID of the cell that is depended upon
        """
        start_time = time.time()
        
        # Ensure both cells exist
        if dependent_id not in self.cells:
            notebook_logger.error(
                "Cannot add dependency: dependent cell not found",
                extra={
                    'notebook_id': str(self.id),
                    'dependent_id': str(dependent_id),
                    'dependency_id': str(dependency_id)
                }
            )
            raise ValueError(f"Dependent cell not found: {dependent_id}")
        
        if dependency_id not in self.cells:
            notebook_logger.error(
                "Cannot add dependency: dependency cell not found",
                extra={
                    'notebook_id': str(self.id),
                    'dependent_id': str(dependent_id),
                    'dependency_id': str(dependency_id)
                }
            )
            raise ValueError(f"Dependency cell not found: {dependency_id}")
        
        # Check for circular dependency
        try:
            transitive_deps = self.dependency_graph.get_transitive_dependencies(dependency_id)
            if dependent_id in transitive_deps:
                notebook_logger.error(
                    "Cannot add dependency: would create cycle",
                    extra={
                        'notebook_id': str(self.id),
                        'dependent_id': str(dependent_id),
                        'dependency_id': str(dependency_id),
                        'transitive_deps': [str(d) for d in transitive_deps]
                    }
                )
                raise ValueError("Adding this dependency would create a cycle")
        except Exception as e:
            notebook_logger.error(
                "Error checking for circular dependency",
                extra={
                    'notebook_id': str(self.id),
                    'dependent_id': str(dependent_id),
                    'dependency_id': str(dependency_id),
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
            raise
        
        # Update the cells
        dependent_cell = self.cells[dependent_id]
        dependency_cell = self.cells[dependency_id]
        
        dependent_cell.add_dependency(dependency_id)
        dependency_cell.add_dependent(dependent_id)
        
        # Update the dependency graph
        self.dependency_graph.add_dependency(dependent_id, dependency_id)
        
        # Mark the dependent cell as stale
        dependent_cell.mark_stale()
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Dependency added",
            extra={
                'notebook_id': str(self.id),
                'dependent_id': str(dependent_id),
                'dependency_id': str(dependency_id),
                'dependent_type': dependent_cell.type.value,
                'dependency_type': dependency_cell.type.value,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def remove_dependency(self, dependent_id: UUID, dependency_id: UUID) -> None:
        """Remove a dependency relationship between cells"""
        start_time = time.time()
        
        # Ensure both cells exist
        if dependent_id not in self.cells:
            notebook_logger.error(
                "Cannot remove dependency: dependent cell not found",
                extra={
                    'notebook_id': str(self.id),
                    'dependent_id': str(dependent_id),
                    'dependency_id': str(dependency_id)
                }
            )
            raise ValueError(f"Dependent cell not found: {dependent_id}")
        
        if dependency_id not in self.cells:
            notebook_logger.error(
                "Cannot remove dependency: dependency cell not found",
                extra={
                    'notebook_id': str(self.id),
                    'dependent_id': str(dependent_id),
                    'dependency_id': str(dependency_id)
                }
            )
            raise ValueError(f"Dependency cell not found: {dependency_id}")
        
        # Update the cells
        dependent_cell = self.cells[dependent_id]
        dependency_cell = self.cells[dependency_id]
        
        dependent_cell.remove_dependency(dependency_id)
        dependency_cell.remove_dependent(dependent_id)
        
        # Update the dependency graph
        self.dependency_graph.remove_dependency(dependent_id, dependency_id)
        
        # Update notebook metadata
        self.metadata.updated_at = datetime.now(timezone.utc)
        
        process_time = time.time() - start_time
        notebook_logger.info(
            "Dependency removed",
            extra={
                'notebook_id': str(self.id),
                'dependent_id': str(dependent_id),
                'dependency_id': str(dependency_id),
                'dependent_type': dependent_cell.type.value,
                'dependency_type': dependency_cell.type.value,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
    
    def mark_dependents_stale(self, cell_id: UUID) -> Set[UUID]:
        """
        Mark all cells that depend on this cell as stale
        
        Args:
            cell_id: ID of the cell whose dependents should be marked stale
            
        Returns:
            Set of cell IDs that were marked stale
        """
        start_time = time.time()
        stale_cells = set()
        
        try:
            # Get all transitive dependents
            dependents = self.dependency_graph.get_all_dependents(cell_id)
            
            # Mark each dependent as stale
            for dep_id in dependents:
                if dep_id in self.cells:
                    self.cells[dep_id].mark_stale()
                    stale_cells.add(dep_id)
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Marked dependent cells as stale",
                extra={
                    'notebook_id': str(self.id),
                    'source_cell_id': str(cell_id),
                    'stale_cells_count': len(stale_cells),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            
            return stale_cells
        except Exception as e:
            notebook_logger.error(
                "Error marking dependents as stale",
                extra={
                    'notebook_id': str(self.id),
                    'source_cell_id': str(cell_id),
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise
    
    def get_execution_order(self, cell_ids: Optional[List[UUID]] = None) -> List[UUID]:
        """
        Get the order in which cells should be executed based on dependencies
        
        Args:
            cell_ids: Optional list of cell IDs to get execution order for
                     If not provided, all cells will be included
                     
        Returns:
            List of cell IDs in execution order
        """
        start_time = time.time()
        
        try:
            # If no cell IDs provided, use all cells
            if cell_ids is None:
                cell_ids = list(self.cells.keys())
            
            # Get execution order from dependency graph
            execution_order = self.dependency_graph.get_execution_order(cell_ids)
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Generated execution order",
                extra={
                    'notebook_id': str(self.id),
                    'cells_count': len(cell_ids),
                    'execution_order_length': len(execution_order),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            
            return execution_order
        except Exception as e:
            notebook_logger.error(
                "Error generating execution order",
                extra={
                    'notebook_id': str(self.id),
                    'cells_count': len(cell_ids) if cell_ids else 0,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise
    
    def move_cell(self, cell_id: UUID, position: int) -> None:
        """
        Move a cell to a new position in the notebook
        
        Args:
            cell_id: ID of the cell to move
            position: New position for the cell (0-based index)
        """
        start_time = time.time()
        
        try:
            if cell_id not in self.cells:
                notebook_logger.error(
                    "Cannot move cell: not found",
                    extra={
                        'notebook_id': str(self.id),
                        'cell_id': str(cell_id),
                        'target_position': position
                    }
                )
                raise ValueError(f"Cell not found: {cell_id}")
            
            if position < 0 or position >= len(self.cell_order):
                notebook_logger.error(
                    "Cannot move cell: invalid position",
                    extra={
                        'notebook_id': str(self.id),
                        'cell_id': str(cell_id),
                        'target_position': position,
                        'max_position': len(self.cell_order) - 1
                    }
                )
                raise ValueError(f"Invalid position: {position}")
            
            # Get current position
            current_position = self.cell_order.index(cell_id)
            
            # Remove from current position and insert at new position
            self.cell_order.remove(cell_id)
            self.cell_order.insert(position, cell_id)
            
            # Update notebook metadata
            self.metadata.updated_at = datetime.now(timezone.utc)
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Cell moved",
                extra={
                    'notebook_id': str(self.id),
                    'cell_id': str(cell_id),
                    'old_position': current_position,
                    'new_position': position,
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
        except Exception as e:
            if not isinstance(e, ValueError):
                notebook_logger.error(
                    "Error moving cell",
                    extra={
                        'notebook_id': str(self.id),
                        'cell_id': str(cell_id),
                        'target_position': position,
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    exc_info=True
                )
            raise
    
    def update_metadata(self, metadata: Dict) -> None:
        """Update notebook metadata"""
        start_time = time.time()
        
        try:
            # Update metadata fields
            for key, value in metadata.items():
                if hasattr(self.metadata, key):
                    setattr(self.metadata, key, value)
            
            # Update timestamp
            self.metadata.updated_at = datetime.now(timezone.utc)
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Notebook metadata updated",
                extra={
                    'notebook_id': str(self.id),
                    'updated_fields': list(metadata.keys()),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
        except Exception as e:
            notebook_logger.error(
                "Error updating notebook metadata",
                extra={
                    'notebook_id': str(self.id),
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise
    
    def serialize(self) -> Dict:
        """Serialize the notebook to a dictionary"""
        start_time = time.time()
        
        try:
            data = {
                "id": str(self.id),
                "metadata": self.metadata.dict(),
                "cells": {str(k): v.dict() for k, v in self.cells.items()},
                "cell_order": [str(id) for id in self.cell_order],
                "dependency_graph": {
                    "dependents": {str(k): [str(d) for d in v] for k, v in self.dependency_graph.dependents.items()},
                    "dependencies": {str(k): [str(d) for d in v] for k, v in self.dependency_graph.dependencies.items()}
                }
            }
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Notebook serialized",
                extra={
                    'notebook_id': str(self.id),
                    'cells_count': len(self.cells),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            
            return data
        except Exception as e:
            notebook_logger.error(
                "Error serializing notebook",
                extra={
                    'notebook_id': str(self.id),
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise
    
    @classmethod
    def deserialize(cls, data: Dict) -> 'Notebook':
        """Create a notebook from a serialized dictionary"""
        start_time = time.time()
        
        try:
            # Create cells
            cells = {}
            for cell_id, cell_data in data["cells"].items():
                cell_type = CellType(cell_data["type"])
                cell = create_cell(cell_type, "", id=UUID(cell_id))
                for key, value in cell_data.items():
                    if key != "type" and hasattr(cell, key):
                        setattr(cell, key, value)
                cells[UUID(cell_id)] = cell
            
            # Create notebook
            notebook = cls(
                id=UUID(data["id"]),
                metadata=NotebookMetadata(**data["metadata"]),
                cells=cells,
                cell_order=[UUID(id) for id in data["cell_order"]]
            )
            
            # Rebuild dependency graph
            for cell_id_str, deps in data["dependency_graph"]["dependencies"].items():
                cell_id = UUID(cell_id_str)
                for dep_id_str in deps:
                    notebook.dependency_graph.add_dependency(cell_id, UUID(dep_id_str))
            
            process_time = time.time() - start_time
            notebook_logger.info(
                "Notebook deserialized",
                extra={
                    'notebook_id': data["id"],
                    'cells_count': len(cells),
                    'processing_time_ms': round(process_time * 1000, 2)
                }
            )
            
            return notebook
        except Exception as e:
            notebook_logger.error(
                "Error deserializing notebook",
                extra={
                    'notebook_id': data.get("id", "unknown"),
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise