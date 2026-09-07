"""app/core/security.py 공용 인증 헬퍼 테스트."""

import uuid
from unittest.mock import patch

from app.core.security import get_active_user
from app.domain.user.models import User


async def test_get_active_user_for_update_locks_row(db_session):
    """for_update=True면 실제로 FOR UPDATE 절이 붙은 쿼리가 나간다.

    강제 탈퇴 처리 중 본인 탈퇴가 끼어드는 경쟁 상태를 막으려면 이 잠금이 실제로
    걸려야 하므로, 옵션 하나 잘못 빠뜨리는 걸 방지하기 위한 최소한의 안전장치.
    """
    user = User(nickname=f"pytest-sec-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.commit()

    original_execute = db_session.execute
    captured: dict[str, str] = {}

    async def spy_execute(stmt, *args, **kwargs):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False})).upper()
        return await original_execute(stmt, *args, **kwargs)

    try:
        with patch.object(db_session, "execute", side_effect=spy_execute):
            await get_active_user(user.user_id, db_session, for_update=True)
        assert "FOR UPDATE" in captured["sql"]

        with patch.object(db_session, "execute", side_effect=spy_execute):
            await get_active_user(user.user_id, db_session, for_update=False)
        assert "FOR UPDATE" not in captured["sql"]
    finally:
        await db_session.delete(user)
        await db_session.commit()
