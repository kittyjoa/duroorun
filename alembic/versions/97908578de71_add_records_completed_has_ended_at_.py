"""add records completed-has-ended-at check constraint

Revision ID: 97908578de71
Revises: 524d965dcb01
Create Date: 2026-09-03 17:28:33.071685

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97908578de71'
down_revision: Union[str, Sequence[str], None] = '524d965dcb01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 자동 생성이 CHECK 제약을 감지하지 못해 수동으로 작성함
    op.create_check_constraint(
        "ck_records_completed_has_ended_at", "records", "NOT is_completed OR ended_at IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_records_completed_has_ended_at", "records", type_="check")
