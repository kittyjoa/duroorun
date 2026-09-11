"""관리자 라우터 - HTTP 레벨 권한 검증.

기존 test_admin.py는 서비스 함수를 직접 호출해서 비즈니스 로직을 검증하는데,
그 방식으로는 라우터에 걸린 Depends(get_current_admin) 자체가 실수로 빠지는 걸
잡아내지 못한다. 여기서는 실제 요청처럼 라우팅부터 의존성 주입까지 전체 흐름을
태워서, 일반 유저/비로그인 요청이 관리자 API에서 거부되는지 그 자체를 검증한다.
"""

import uuid

import pytest_asyncio

from app.core.security import create_access_token
from app.domain.user.models import User, UserRole


@pytest_asyncio.fixture
async def regular_user(db_session):
    user = User(nickname=f"pytest-router-{uuid.uuid4().hex[:12]}", user_role=UserRole.USER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


async def test_search_users_rejects_unauthenticated(async_client):
    res = await async_client.get("/api/v1/admin/users/search", params={"nickname": "test"})
    assert res.status_code == 401


async def test_search_users_rejects_regular_user(async_client, regular_user):
    token = create_access_token(regular_user.user_id)
    res = await async_client.get(
        "/api/v1/admin/users/search",
        params={"nickname": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


async def test_get_banned_accounts_rejects_unauthenticated(async_client):
    res = await async_client.get("/api/v1/admin/banned-accounts")
    assert res.status_code == 401


async def test_get_banned_accounts_rejects_regular_user(async_client, regular_user):
    token = create_access_token(regular_user.user_id)
    res = await async_client.get(
        "/api/v1/admin/banned-accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403


async def test_unban_account_rejects_unauthenticated(async_client):
    res = await async_client.delete("/api/v1/admin/banned-accounts/1")
    assert res.status_code == 401


async def test_unban_account_rejects_regular_user(async_client, regular_user):
    token = create_access_token(regular_user.user_id)
    res = await async_client.delete(
        "/api/v1/admin/banned-accounts/1", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403


async def test_force_withdraw_rejects_unauthenticated(async_client):
    res = await async_client.request(
        "DELETE", "/api/v1/admin/users/1", json={"reason": "test"}
    )
    assert res.status_code == 401


async def test_force_withdraw_rejects_regular_user(async_client, regular_user):
    token = create_access_token(regular_user.user_id)
    res = await async_client.request(
        "DELETE",
        "/api/v1/admin/users/1",
        json={"reason": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
