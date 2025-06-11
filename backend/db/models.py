"""
Database models for connections
"""

import uuid
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Integer, Float, UUID, Index
from sqlalchemy.orm import relationship

from backend.db.database import Base


class Connection(Base):
    """Connection model for storing connection configurations"""
    __tablename__ = "connections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # grafana, kubernetes, s3, postgres, etc.
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "config": self.config,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else None,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else None,
        }


class DefaultConnection(Base):
    """Default connection mapping for connection types"""
    __tablename__ = "default_connections"

    connection_type = Column(String, primary_key=True)
    connection_id = Column(String, ForeignKey("connections.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to the connection
    connection = relationship("Connection")


class SQLiteUUID:
    """SQLite-compatible UUID type"""
    def __init__(self, value=None):
        self.value = value or uuid.uuid4()
    
    def __str__(self):
        return str(self.value)
    
    @classmethod
    def from_string(cls, value):
        return cls(uuid.UUID(value))


class Notebook(Base):
    """SQLAlchemy model for notebooks"""
    __tablename__ = "notebooks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False, default="Untitled Investigation")
    description = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = Column(JSON, default=list)
    
    # Relationships
    cells = relationship("Cell", back_populates="notebook", cascade="all, delete-orphan")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "metadata": {
                "title": self.title,
                "description": self.description if self.description is not None else "",
                "tags": self.tags if self.tags is not None else [],
                "created_by": self.created_by,
                "created_at": self.created_at.isoformat() if self.created_at is not None else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None
            },
            "cell_order": [cell.id for cell in sorted(self.cells, key=lambda c: c.position)],
            "dependency_graph": self._build_dependency_graph()
        }
    
    def _build_dependency_graph(self) -> Dict:
        """Build dependency graph from cells"""
        dependents = {}
        dependencies = {}
        
        for cell in self.cells:
            dependents[cell.id] = [dep.id for dep in cell.dependents]
            dependencies[cell.id] = [dep.id for dep in cell.dependencies]
        
        return {
            "dependents": dependents,
            "dependencies": dependencies
        }


class Cell(Base):
    """SQLAlchemy model for cells"""
    __tablename__ = "cells"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)  # SQL, Python, Markdown, etc.
    content = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="idle")  # idle, running, success, error, stale
    connection_id = Column(String(36), ForeignKey("connections.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cell_metadata = Column(JSON, default=dict)
    settings = Column(JSON, default=dict)
    
    # Result data
    result_content = Column(JSON, nullable=True)
    result_error = Column(Text, nullable=True)
    result_execution_time = Column(Float, nullable=True)
    result_timestamp = Column(DateTime, nullable=True)
    
    # Tool call specific fields
    tool_call_id = Column(String(36), nullable=False)
    tool_name = Column(String(255), nullable=True)
    tool_arguments = Column(JSON, nullable=True)
    tool_output = Column(JSON, nullable=True)
    
    # Relationships
    notebook = relationship("Notebook", back_populates="cells")
    dependencies = relationship(
        "Cell",
        secondary="cell_dependencies",
        primaryjoin="Cell.id==cell_dependencies.c.dependent_id",
        secondaryjoin="Cell.id==cell_dependencies.c.dependency_id",
        backref="dependents"
    )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        result = None
        if self.result_content is not None:
            result = {
                "content": self.result_content,
                "error": self.result_error,
                "execution_time": self.result_execution_time,
                "timestamp": self.result_timestamp.isoformat() if self.result_timestamp is not None else None
            }
        
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "result": result,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,
            "connection_id": self.connection_id,
            "dependencies": [dep.id for dep in self.dependencies],
            "dependents": [dep.id for dep in self.dependents],
            "metadata": self.cell_metadata if self.cell_metadata is not None else {},
            "settings": self.settings if self.settings is not None else {},
            "tool_call_id": str(self.tool_call_id),
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments
        }


class CellDependency(Base):
    """Association table for cell dependencies"""
    __tablename__ = "cell_dependencies"
    
    dependent_id = Column(String(36), ForeignKey("cells.id", ondelete="CASCADE"), primary_key=True)
    dependency_id = Column(String(36), ForeignKey("cells.id", ondelete="CASCADE"), primary_key=True)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String, nullable=False, index=True)
    notebook_id = Column(UUID(as_uuid=True), nullable=True, index=True) # Can be linked to a notebook
    
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False, unique=True) # Path on the server
    file_type = Column(String, nullable=True) # MIME type
    size = Column(Integer, nullable=True) # Size in bytes
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    metadata_ = Column("metadata", JSON, nullable=True) # Additional metadata

    __table_args__ = (
        Index("ix_uploaded_files_session_id", "session_id"),
        Index("ix_uploaded_files_notebook_id", "notebook_id"),
    )

    def __repr__(self):
        return f"<UploadedFile(id={self.id}, filename='{self.filename}', session_id='{self.session_id}')>" 
