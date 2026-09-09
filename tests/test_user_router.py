"""유저 라우터 - 공개 프로필 조회 HTTP 레벨 테스트.

서비스 함수(get_public_profile)는 test_user.py에서 이미 검증했으니, 여기서는
서비스 함수 직접 호출로는 확인할 수 없는 것들만 다룬다: 라우터가 실제로 인증 없이
응답하는지, 404가 그대로 전파되는지, IP 기준 rate limit이 실제로 걸리는지.
"""

import uuid

import pytest_asyncio

from app.domain.user.models import User
from app.domain.user.router import _PUBLIC_PROFILE_RATE_LIMIT_MAX_REQUESTS


@pytest_asyncio.fixture
async def active_user(db_session):
    user = User(nickname=f"pytest-userrouter-{uuid.uuid4().hex[:12]}", location="강원 속초시")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


async def test_get_public_profile_returns_200_without_auth(async_client, active_user):
    res = await async_client.get(f"/api/v1/users/{active_user.user_id}")

    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == active_user.user_id
    assert body["nickname"] == active_user.nickname


async def test_get_public_profile_returns_404_for_missing_user(async_client):
    res = await async_client.get("/api/v1/users/999999999")

    assert res.status_code == 404


async def test_get_public_profile_rate_limited_by_ip(async_client, active_user, redis_client):
    # 다른 테스트가 같은 테스트클라이언트 IP로 이미 카운트를 쌓아뒀을 수 있으니 먼저 비운다
    async for key in redis_client.scan_iter("ratelimit:public_profile:*"):
        await redis_client.delete(key)

    try:
        for _ in range(_PUBLIC_PROFILE_RATE_LIMIT_MAX_REQUESTS):
            res = await async_client.get(f"/api/v1/users/{active_user.user_id}")
            assert res.status_code == 200

        res = await async_client.get(f"/api/v1/users/{active_user.user_id}")
        assert res.status_code == 429
    finally:
        async for key in redis_client.scan_iter("ratelimit:public_profile:*"):
            await redis_client.delete(key)
