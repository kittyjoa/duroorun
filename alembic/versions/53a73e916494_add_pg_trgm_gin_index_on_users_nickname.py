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

    CONCURRENTLY로 만드는 이유(2026-09-11 리뷰 지적): 일반 CREATE INDEX는 빌드하는 동안
    테이블에 쓰기 락을 걸어 그 시간만큼 회원가입/로그인 등 users 쓰기가 전부 대기한다.
    지금 유저 규모에선 순식간이라 체감이 안 되지만, 유저가 많아진 뒤 배포할 상황을
    대비해 미리 안전한 방식으로 맞춰둔다. CONCURRENTLY는 트랜잭션 안에서 못 돌아가므로
    autocommit_block()으로 감싼다.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_nickname_trgm "
            "ON users USING gin (nickname gin_trgm_ops)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_nickname_trgm")
    # pg_trgm 확장은 다른 곳에서도 쓰일 수 있어 여기서 DROP EXTENSION은 하지 않는다
