"""add unique index to prevent concurrent active records

Revision ID: 7da40cd26d46
Revises: 58e94abf10b9
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7da40cd26d46'
down_revision: Union[str, Sequence[str], None] = '58e94abf10b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_records_active_user',
        'records',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text('ended_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_records_active_user', table_name='records')
