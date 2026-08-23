"""add course_sync_logs table

Revision ID: 7d76100bab00
Revises: 623ea27bc0b3
Create Date: 2026-08-24 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d76100bab00'
down_revision: Union[str, Sequence[str], None] = '623ea27bc0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'course_sync_logs',
        sa.Column('sync_log_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('status', sa.Enum('SUCCESS', 'FAILURE', name='syncstatus'), nullable=False),
        sa.Column('fetched_count', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('sync_log_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('course_sync_logs')
    sa.Enum(name='syncstatus').drop(op.get_bind(), checkfirst=True)
