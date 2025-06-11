from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, UUID4
import sqlalchemy as sa

from backend.db.database import get_db_session
from backend.db.models import UploadedFile

if TYPE_CHECKING:
    from backend.services.notebook_manager import NotebookManager

"""Notebook context retrieval tools to expose to Pydantic-AI agents.

These helpers create two retrieval-style function tools that agents can call to
inspect the user's notebook while they are reasoning.  The tools *do not*
create new cells – they simply return JSON data so the agent can decide what to
do next.

Tools
-----
1. list_cells – returns a lightweight listing of recent cells with optional
                filters.
2. get_cell   – returns the full, raw cell record for a supplied cell_id.

Both tools are generated via `create_notebook_context_tools` so that the
notebook_id and a `NotebookManager` instance can be captured in a closure.  If
a `NotebookManager` is not available the helper returns an empty list which is
safe to pass to the Agent constructor.
"""

logger = logging.getLogger(__name__)


class CellSortByOption(str, Enum):
    """Defines the sorting options for listing cells."""
    RECENCY = "recency"
    POSITION_ASC = "position_asc"
    POSITION_DESC = "position_desc"


class ListCellsParams(BaseModel):
    """Schema for the `list_cells` tool."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of cells to return after sorting and filtering.",
    )
    cell_type: Optional[List[str]] = Field(
        default=None,
        description="Optional filter for cell types, e.g. ['python', 'markdown'].",
    )
    status: Optional[List[str]] = Field(
        default=None,
        description="Optional filter for cell status values, e.g. ['success', 'running'].",
    )
    contains: Optional[str] = Field(
        default=None,
        description="Case-insensitive substring that must appear in cell content.",
    )
    sort_by: Optional[CellSortByOption] = Field(
        default=CellSortByOption.RECENCY,
        description="Defines the primary sorting of cells. "
                    "'recency': most recently updated/created first (default). "
                    "'position_asc': sort by cell position, oldest/lowest index first. "
                    "'position_desc': sort by cell position, newest/highest index first.",
    )


# New Pydantic schemas for uploaded-files tools
class ListUploadedFilesParams(BaseModel):
    """Parameters for listing uploaded files for a chat session."""
    session_id: str = Field(..., description="Chat session ID whose uploaded files should be listed.")


class GetUploadedFilePathParams(BaseModel):
    """Parameters for retrieving a single uploaded-file path by file ID."""
    file_id: UUID4 = Field(..., description="UploadedFile.id to fetch its server-side path")


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------

def create_notebook_context_tools(
    notebook_id: str,
    notebook_manager: Optional['NotebookManager'],
):
    """Return `[list_cells, get_cell]` tool callables for *notebook_id*.

    If *notebook_manager* is missing (e.g. unit tests), an empty list is
    returned so callers can safely pass the result to the Agent constructor.
    """

    if not notebook_manager:
        logger.warning(
            "NotebookManager unavailable – notebook context tools will not be registered."
        )
        return []

    # ---------------------------------------------------------------------
    # list_cells implementation
    # ---------------------------------------------------------------------

    async def list_cells(
        params: ListCellsParams,
    ) -> List[Dict[str, Any]]:
        """Return a lightweight list of notebook cells based on specified criteria.

        Each element contains: id, type, status, updated_at, content_preview, and position.
        Sorting can be done by recency or by cell position.
        """

        async with get_db_session() as db:
            try:
                nb = await notebook_manager.get_notebook(db, UUID(notebook_id))
            except Exception as exc:  # noqa: BLE001 (broad but logged)
                logger.error("list_cells: failed to load notebook %s – %s", notebook_id, exc, exc_info=True)
                raise

            from typing import Any as _Any  # local import to avoid global import cycles
            
            all_notebook_cells: List[_Any] = list(nb.cells.values())

            ordered_cells: List[_Any]
            sort_option = params.sort_by if params.sort_by is not None else CellSortByOption.RECENCY

            if sort_option == CellSortByOption.POSITION_ASC:
                # Sort by position ascending, handling potential None or missing attribute gracefully
                ordered_cells = sorted(all_notebook_cells, key=lambda c: getattr(c, 'position', float('inf')))
            elif sort_option == CellSortByOption.POSITION_DESC:
                # Sort by position descending, handling potential None or missing attribute gracefully
                ordered_cells = sorted(all_notebook_cells, key=lambda c: getattr(c, 'position', float('-inf')), reverse=True)
            elif sort_option == CellSortByOption.RECENCY:
                # Default: Sort by recency (updated_at or created_at, newest first)
                ordered_cells = sorted(all_notebook_cells, key=lambda c: c.updated_at or c.created_at, reverse=True)
            else: # Should not happen with Enum validation, but as a fallback
                logger.warning(
                    "list_cells: Invalid sort_by value '%s'. Defaulting to 'recency'.", params.sort_by
                )
                ordered_cells = sorted(all_notebook_cells, key=lambda c: c.updated_at or c.created_at, reverse=True)
            
            results: List[Dict[str, Any]] = []
            for cell in ordered_cells:
                if params.cell_type and cell.type.value not in params.cell_type:
                    continue
                if params.status and cell.status.value not in params.status:
                    continue
                if params.contains and params.contains.lower() not in (cell.content or "").lower():
                    continue

                results.append(
                    {
                        "id": str(cell.id),
                        "type": cell.type.value,
                        "status": cell.status.value,
                        "updated_at": (cell.updated_at or cell.created_at).isoformat()
                        if (cell.updated_at or cell.created_at)
                        else None,
                        "content_preview": (cell.content or "")[:120],
                        "position": getattr(cell, 'position', None) # Also include position in the output
                    }
                )

                if len(results) >= params.limit:
                    break

            return results

    # ---------------------------------------------------------------------
    # list_uploaded_files implementation
    # ---------------------------------------------------------------------

    async def list_uploaded_files(params: ListUploadedFilesParams) -> List[Dict[str, Any]]:
        """Return minimal metadata for all files uploaded in *session_id* (most recent first)."""
        async with get_db_session() as db:
            rows = (
                await db.execute(
                    sa.select(UploadedFile)  # type: ignore[name-defined]
                    .where(UploadedFile.session_id == params.session_id)
                    .order_by(UploadedFile.created_at.desc())
                )
            ).scalars().all()

            result_list = []
            for row in rows:
                created_at_val = row.created_at
                result_list.append({
                    "id": str(row.id),
                    "filename": row.filename,
                    "filepath": row.filepath,
                    "size": row.size,
                    "created_at": created_at_val.isoformat() if created_at_val is not None else None,
                })
            return result_list

    # ---------------------------------------------------------------------
    # get_uploaded_file_path implementation
    # ---------------------------------------------------------------------

    async def get_uploaded_file_path(params: GetUploadedFilePathParams) -> str:
        """Return the server-side relative filepath for *file_id*.

        Raises ValueError if not found so the LLM sees an explicit error message.
        """
        async with get_db_session() as db:
            row = await db.get(UploadedFile, params.file_id)  # type: ignore[arg-type]
            if not row:
                raise ValueError(f"Uploaded file {params.file_id} not found")
            return str(row.filepath)

    # ---------------------------------------------------------------------
    # get_cell implementation
    # ---------------------------------------------------------------------

    async def get_cell(cell_id: UUID4) -> Dict[str, Any]:
        """Return the full raw cell record as stored in the DB."""

        async with get_db_session() as db:
            try:
                cell = await notebook_manager.get_cell(db, UUID(notebook_id), UUID(str(cell_id)))
            except Exception as exc:  # noqa: BLE001
                logger.error("get_cell: failed to fetch cell %s – %s", cell_id, exc, exc_info=True)
                raise

            return cell.model_dump(mode="json")  # type: ignore[arg-type]

    # Name the functions for nicer tool labels
    list_cells.__name__ = "list_cells"
    get_cell.__name__ = "get_cell"
    list_uploaded_files.__name__ = "list_uploaded_files"
    get_uploaded_file_path.__name__ = "get_uploaded_file_path"

    # Always return raw functions – the Agent constructor will wrap them
    # automatically, and this avoids generic type mismatches with different
    # deps_type parameters across agents.

    return [list_cells, get_cell, list_uploaded_files, get_uploaded_file_path] 