"""Update tool_call_id to non-nullable UUID

Revision ID: d3b0a9c8e1f7
Revises: 877f13b32445
Create Date: YYYY-MM-DD HH:MM:SS.mmmmmm

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import String, UUID, select, text


# revision identifiers, used by Alembic.
revision: str = 'd3b0a9c8e1f7'
down_revision: Union[str, None] = '877f13b32445'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    
    bind = op.get_bind()
    
    # Step 1: Alter column to UUID type, keep nullable temporarily
    # Use batch mode for SQLite compatibility with ALTER COLUMN
    with op.batch_alter_table('cells', schema=None) as batch_op:
        batch_op.alter_column('tool_call_id',
               existing_type=sa.String(length=255),
               type_=sa.UUID(as_uuid=True),
               nullable=True) # Keep nullable for the update step

    # Step 2: Update existing NULL values with generated UUIDs for SQLite
    cells_table = table('cells',
        column('id', String),
        column('tool_call_id', UUID)
    )
    
    # Select rows where tool_call_id is NULL
    select_stmt = select(cells_table.c.id).where(cells_table.c.tool_call_id == None)
    results = bind.execute(select_stmt).fetchall()
    
    print(f"Found {len(results)} cells with NULL tool_call_id to update.")

    # Update each row individually
    for row in results:
        cell_id = row[0]
        new_uuid = uuid.uuid4()
        update_stmt = cells_table.update().where(cells_table.c.id == cell_id).values(tool_call_id=new_uuid)
        bind.execute(update_stmt)
        
    print(f"Finished updating NULL tool_call_id values.")

    # Step 3: Alter column to be non-nullable
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('cells', schema=None) as batch_op:
        batch_op.alter_column('tool_call_id',
               existing_type=sa.UUID(as_uuid=True),
               nullable=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    
    # Revert to String, allow nulls again
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('cells', schema=None) as batch_op:
        batch_op.alter_column('tool_call_id',
               existing_type=sa.UUID(as_uuid=True),
               type_=sa.String(length=255),
               nullable=True) # Make nullable again

    # Note: We cannot reliably downgrade the UUID values back to their original strings (if any)

    # ### end Alembic commands ### 