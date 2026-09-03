"""회원/인증 - 소셜 로그인, 토큰 재발급/로그아웃, 탈퇴, 프로필 수정 테스트."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select

from app.core.security import (
    add_to_blacklist,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    is_blacklisted,
    save_refresh_jti,
)
from app.domain.course.models import Course, CourseType
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.user.models import ProviderType, SocialAccount, User
from app.domain.user.service import (
    _touch_last_login,
    kakao_login,
    logout,
    refresh_tokens,
    update_profile,
    withdraw_user,
)


@dataclass
class UserTestContext:
    """테스트 중 생성한 row들을 모아뒀다가 종료 시 정리한다."""

    user_ids: list[int] = field(default_factory=list)
    course_ids: list[int] = field(default_factory=list)


@pytest_asyncio.fixture
async def ctx(db_session):
    context = UserTestContext()
    yield context

    if context.user_ids:
        await db_session.execute(
            delete(SocialAccount).where(SocialAccount.user_id.in_(context.user_ids))
        )
        await db_session.execute(delete(Record).where(Record.user_id.in_(context.user_ids)))
        await db_session.execute(delete(Review).where(Review.user_id.in_(context.user_ids)))
        await db_session.execute(delete(User).where(User.user_id.in_(context.user_ids)))
    if context.course_ids:
        # withdraw_user는 레코드를 지우지 않고 user_id만 NULL 처리하므로,
        # course_id 기준으로도 한번 더 정리해야 FK 위반 없이 Course를 지울 수 있음
        await db_session.execute(delete(Record).where(Record.course_id.in_(context.course_ids)))
        await db_session.execute(delete(Review).where(Review.course_id.in_(context.course_ids)))
        await db_session.execute(delete(Course).where(Course.course_id.in_(context.course_ids)))
    await db_session.commit()


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


async def _make_user(db_session, ctx: UserTestContext) -> User:
    user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    ctx.user_ids.append(user.user_id)
    return user


# 1. 카카오 로그인 신규가입 시 User+SocialAccount 생성
async def test_kakao_login_creates_new_user(db_session, ctx, redis_client):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        access_token, refresh_token = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    user_id = int(decode_token(access_token)["sub"])
    ctx.user_ids.append(user_id)

    social = (
        await db_session.execute(
            select(SocialAccount).where(SocialAccount.provider_uid == provider_uid)
        )
    ).scalar_one()
    assert social.user_id == user_id
    assert social.provider_type == ProviderType.KAKAO

    new_user = (await db_session.execute(select(User).where(User.user_id == user_id))).scalar_one()
    assert new_user.last_login_at is not None


# 2. 같은 소셜 계정으로 재로그인 시 새 유저 안 만들고 기존 유저로 로그인
async def test_kakao_login_existing_account_reuses_user(db_session, ctx, redis_client):
    provider_uid = uuid.uuid4().hex
    existing_user = await _make_user(db_session, ctx)
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

    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        access_token, _ = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    assert int(decode_token(access_token)["sub"]) == existing_user.user_id
    social_count = (
        await db_session.execute(
            select(SocialAccount).where(SocialAccount.provider_uid == provider_uid)
        )
    ).scalars().all()
    assert len(social_count) == 1


# 3. 토큰 재발급 정상 흐름 - 올바른 jti면 새 토큰 발급 + Redis 값 교체
async def test_refresh_tokens_rotates_on_valid_jti(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    refresh_token, jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, jti, redis_client)

    _, new_refresh_token = await refresh_tokens(refresh_token, db_session, redis_client)
    new_jti = decode_token(new_refresh_token)["jti"]

    stored = await redis_client.get(f"refresh:{user.user_id}")
    assert stored == new_jti
    assert stored != jti

    refreshed_user = (
        await db_session.execute(select(User).where(User.user_id == user.user_id))
    ).scalar_one()
    assert refreshed_user.last_login_at is not None


# 4. 토큰 재발급 시 jti 불일치(탈취 의심) → 401
async def test_refresh_tokens_rejects_stale_jti(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    _, current_jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, current_jti, redis_client)

    # 저장된 것과 다른(옛) refresh token으로 재발급 시도
    stale_refresh_token, _ = create_refresh_token(user.user_id)

    with pytest.raises(HTTPException) as exc_info:
        await refresh_tokens(stale_refresh_token, db_session, redis_client)

    assert exc_info.value.status_code == 401


# 5. 로그아웃 시 access token 블랙리스트 등록 + refresh token 삭제
async def test_logout_blacklists_access_and_deletes_refresh(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    access_token = create_access_token(user.user_id)
    access_jti = decode_token(access_token)["jti"]
    _, refresh_jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, refresh_jti, redis_client)

    await logout(access_token, redis_client)

    assert await is_blacklisted(access_jti, redis_client) is True
    assert await redis_client.get(f"refresh:{user.user_id}") is None


# 6. 블랙리스트된 토큰으로 get_current_user 호출 시 401
async def test_get_current_user_rejects_blacklisted_token(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    access_token = create_access_token(user.user_id)
    jti = decode_token(access_token)["jti"]
    await add_to_blacklist(jti, redis_client)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials, db_session, redis_client)

    assert exc_info.value.status_code == 401


# 7. 탈퇴한 유저(deleted_at 있음)로 get_current_user 호출 시 401
async def test_get_current_user_rejects_withdrawn_user(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()
    access_token = create_access_token(user.user_id)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials, db_session, redis_client)

    assert exc_info.value.status_code == 401


# 8. 본인 탈퇴 시 익명화 + social_accounts 하드삭제 + records/reviews/courses user_id NULL 처리
async def test_withdraw_user_anonymizes_and_nullifies_related_data(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    db_session.add(
        SocialAccount(
            user_id=user.user_id, provider_type=ProviderType.KAKAO, provider_uid=uuid.uuid4().hex
        )
    )
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=user.user_id,
    )
    db_session.add(course)
    await db_session.flush()
    ctx.course_ids.append(course.course_id)

    db_session.add(
        Record(
            user_id=user.user_id,
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            is_completed=True,
        )
    )
    db_session.add(
        Review(
            user_id=user.user_id,
            course_id=course.course_id,
            content="내용",
            difficulty="NORMAL",
        )
    )
    await db_session.commit()

    access_token = create_access_token(user.user_id)
    await withdraw_user(user, access_token, db_session, redis_client)

    refreshed_user = (
        await db_session.execute(select(User).where(User.user_id == user.user_id))
    ).scalar_one()
    assert refreshed_user.deleted_at is not None
    assert refreshed_user.nickname is None

    remaining_social = (
        await db_session.execute(
            select(SocialAccount).where(SocialAccount.user_id == user.user_id)
        )
    ).scalars().all()
    assert remaining_social == []

    record = (
        await db_session.execute(select(Record).where(Record.course_id == course.course_id))
    ).scalar_one()
    assert record.user_id is None

    review = (
        await db_session.execute(select(Review).where(Review.course_id == course.course_id))
    ).scalar_one()
    assert review.user_id is None

    refreshed_course = (
        await db_session.execute(select(Course).where(Course.course_id == course.course_id))
    ).scalar_one()
    assert refreshed_course.created_by is None


# 9. 닉네임 형식 위반(특수문자) → 400
async def test_update_profile_rejects_invalid_nickname(db_session, ctx):
    user = await _make_user(db_session, ctx)

    with pytest.raises(HTTPException) as exc_info:
        await update_profile(user, nickname="닉!네임", location=None, db=db_session)

    assert exc_info.value.status_code == 400


# 10. 중복 닉네임으로 수정 시도 → 409
async def test_update_profile_rejects_duplicate_nickname(db_session, ctx):
    taken_nickname = uuid.uuid4().hex[:8]  # NICKNAME_MAX_LENGTH(10) 이내로
    user_a = await _make_user(db_session, ctx)
    user_a.nickname = taken_nickname
    await db_session.commit()

    user_b = await _make_user(db_session, ctx)

    with pytest.raises(HTTPException) as exc_info:
        await update_profile(user_b, nickname=taken_nickname, location=None, db=db_session)

    assert exc_info.value.status_code == 409


# 11. 짧은 시간 내 반복 호출 시 last_login_at 갱신을 생략함 (불필요한 DB write 방지)
async def test_touch_last_login_skips_recent_update(db_session, ctx):
    user = await _make_user(db_session, ctx)

    await _touch_last_login(user.user_id, db_session)
    first = (
        await db_session.execute(select(User.last_login_at).where(User.user_id == user.user_id))
    ).scalar_one()

    await _touch_last_login(user.user_id, db_session)
    second = (
        await db_session.execute(select(User.last_login_at).where(User.user_id == user.user_id))
    ).scalar_one()

    assert first == second
