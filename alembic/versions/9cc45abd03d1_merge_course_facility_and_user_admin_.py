"""merge course_facility and user_admin heads

Revision ID: 9cc45abd03d1
Revises: 7299b94313dd, a1c9f4e2b7d3
Create Date: 2026-09-11 19:49:29.810396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9cc45abd03d1'
down_revision: Union[str, Sequence[str], None] = ('7299b94313dd', 'a1c9f4e2b7d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
