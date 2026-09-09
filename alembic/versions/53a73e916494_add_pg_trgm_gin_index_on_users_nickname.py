"""add pg_trgm gin index on users nickname

Revision ID: 53a73e916494
Revises: d19a2922343c
Create Date: 2026-09-09 15:03:16.187132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53a73e916494'
down_revision: Union[str, Sequence[str], None] = 'd19a2922343c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    유저 검색(admin search_users)이 ILIKE '%...%'로 앞뒤 와일드카드 검색을 하는데,
    일반 B-tree 인덱스는 이런 패턴을 못 타 유저가 많아지면 전체 스캔이 된다.
    pg_trgm 확장 + GIN 인덱스를 추가하면 이 패턴도 인덱스를 탈 수 있다.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_users_nickname_trgm ON users USING gin (nickname gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_users_nickname_trgm")
    # pg_trgm 확장은 다른 곳에서도 쓰일 수 있어 여기서 DROP EXTENSION은 하지 않는다
