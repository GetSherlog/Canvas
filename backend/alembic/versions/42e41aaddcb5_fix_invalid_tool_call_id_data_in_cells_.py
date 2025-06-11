"""Fix invalid tool_call_id data in cells table

Revision ID: 42e41aaddcb5
Revises: 23e0b8b30c1e
Create Date: 2025-05-02 08:50:50.679458

"""
from typing import Sequence, Union

from alembic import op
import uuid
from sqlalchemy.sql import table, column
from sqlalchemy import String, select, update


# revision identifiers, used by Alembic.
revision: str = '42e41aaddcb5'
down_revision: Union[str, None] = '23e0b8b30c1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix invalid tool_call_id data."""
    # Define minimal table structure for query/update
    cells_table = table('cells',
        column('id', String),
        column('tool_call_id', String)
    )
    
    # Bind the connection for executing statements
    conn = op.get_bind()
    
    # Find cells with invalid tool_call_id (e.g., '0' or others if needed)
    # Focusing on '0' based on the specific error seen.
    # Use LENGTH check for more general invalid string UUIDs if necessary, 
    # but be careful not to update already valid ones.
    select_stmt = select(cells_table.c.id).where(cells_table.c.tool_call_id == '0')
    
    results = conn.execute(select_stmt).fetchall()
    
    print(f"Found {len(results)} cells with invalid tool_call_id='0'")
    
    for cell_row in results:
        cell_id = cell_row[0]
        new_uuid = str(uuid.uuid4())
        print(f"Updating cell {cell_id} with new tool_call_id: {new_uuid}")
        
        update_stmt = update(cells_table).where(cells_table.c.id == cell_id).values(tool_call_id=new_uuid)
        conn.execute(update_stmt)


def downgrade() -> None:
    """Downgrade - No data reversal implemented."""
    # Downgrading data fixes is often complex and not required.
    # If necessary, manual steps or a specific reversal script would be needed.
    pass
