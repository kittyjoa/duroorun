"""소셜 로그인 콜백 라우터 - 신규/기존 유저 분기 HTTP 레벨 테스트.

서비스 함수(kakao_login 등)는 test_user.py에서 이미 검증했으니, 여기서는 라우터가
실제로 신규 유저는 온보딩(signup_token)으로, 기존 유저는 refresh_token 쿠키와 함께
홈으로 정확히 리다이렉트를 분기하는지 HTTP 레벨에서 확인한다.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import delete

from app.config import settings
from app.domain.user.models import ProviderType, SocialAccount, User


def _fake_kakao_client(provider_uid: str, name: str = "pytest유저"):
    """httpx.AsyncClient(...)의 자리를 대신할 가짜 클라이언트 (토큰발급/유저조회 응답 목킹)."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(
        return_value=MagicMock(status_code=200, json=lambda: {"access_token": "fake-kakao-token"})
    )
    client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {"id": provider_uid, "kakao_account": {"name": name}},
        )
    )
    return client


async def test_kakao_callback_redirects_new_user_to_onboarding_with_signup_token(
    async_client, redis_client
):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        res = await async_client.get(
            "/api/v1/auth/kakao/callback",
            params={"state": state, "code": "fake-code"},
            cookies={"oauth_state": state},
        )

    assert res.status_code in (302, 307)
    location = res.headers["location"]
    assert location.startswith(f"{settings.FRONTEND_URL}/onboarding?")
    assert "signup_token=" in location
    # 신규 유저는 계정이 아직 없으므로 로그인 쿠키가 발급되면 안 됨
    assert "refresh_token" not in res.cookies


async def test_kakao_callback_redirects_existing_user_with_refresh_cookie(
    db_session, async_client, redis_client
):
    provider_uid = uuid.uuid4().hex
    existing_user = User(nickname=f"pytest-router-{uuid.uuid4().hex[:12]}")
    db_session.add(existing_user)
    await db_session.flush()
    db_session.add(
        SocialAccount(
            user_id=existing_user.user_id,
            provider_type=ProviderType.KAKAO,
            provider_uid=provider_uid,
        )
    )
    await db_session.commit()

    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    try:
        with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
            res = await async_client.get(
                "/api/v1/auth/kakao/callback",
                params={"state": state, "code": "fake-code"},
                cookies={"oauth_state": state},
            )

        assert res.status_code in (302, 307)
        assert res.headers["location"] == f"{settings.FRONTEND_URL}/oauth/callback"
        assert "refresh_token" in res.cookies
    finally:
        await db_session.execute(
            delete(SocialAccount).where(SocialAccount.user_id == existing_user.user_id)
        )
        await db_session.execute(delete(User).where(User.user_id == existing_user.user_id))
        await db_session.commit()


async def test_kakao_callback_redirects_to_login_on_missing_code(async_client):
    res = await async_client.get("/api/v1/auth/kakao/callback", params={"state": uuid.uuid4().hex})

    assert res.status_code in (302, 307)
    assert res.headers["location"].startswith(f"{settings.FRONTEND_URL}/login?")
