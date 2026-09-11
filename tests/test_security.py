"""app/core/security.py 공용 인증 헬퍼 테스트."""

import uuid
from unittest.mock import patch

from app.core.security import get_active_user, release_lock_if_owner
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


async def test_release_lock_if_owner_only_deletes_matching_token(redis_client):
    """내가 저장한 토큰이 아직 그대로일 때만 지우고, 남의 토큰으로 바뀌어있으면 안 지운다.

    signup_lock처럼 TTL 만료 후 다른 요청이 같은 키로 새 락을 잡았을 때, 뒤늦게 원래
    요청이 조건 없이 DEL하면 "남의" 락을 지워버리는 걸 fencing token으로 막는 로직 검증.
    """
    key = f"pytest-lock-{uuid.uuid4().hex[:12]}"

    # 소유자가 아닌 토큰으로 해제 시도 → 실패, 키는 그대로 남아있어야 함
    await redis_client.set(key, "owner-token", nx=True, ex=30)
    released = await release_lock_if_owner(key, "someone-elses-token", redis_client)
    assert released is False
    assert await redis_client.get(key) == "owner-token"

    # 실제 소유자 토큰으로 해제 시도 → 성공, 키가 지워져야 함
    released = await release_lock_if_owner(key, "owner-token", redis_client)
    assert released is True
    assert await redis_client.get(key) is None
