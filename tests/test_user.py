"""회원/인증 - 소셜 로그인, 토큰 재발급/로그아웃, 탈퇴, 프로필 수정 테스트."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.security import (
    add_to_blacklist,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    is_blacklisted,
    save_refresh_jti,
)
from app.domain.course.models import Course, CourseImage, CourseType, CourseWaypoint
from app.domain.facility.models import CourseFacility, Facility, FacilityType
from app.domain.record.models import Record
from app.domain.review.models import Review, ReviewImage, ReviewSummary
from app.domain.user.models import ProviderType, SocialAccount, User
from app.domain.user.service import (
    _delete_orphaned_custom_courses,
    _touch_last_login,
    complete_signup,
    get_public_profile,
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


# 1. 카카오 로그인(신규) 시 계정을 바로 만들지 않고 signup_token만 내려줌 +
# 약관 동의(complete_signup) 완료 시에만 실제로 User+SocialAccount 생성
async def test_kakao_login_creates_new_user(db_session, ctx, redis_client):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    assert login_result.signup_token
    assert login_result.access_token is None
    no_social = (
        await db_session.execute(
            select(SocialAccount).where(SocialAccount.provider_uid == provider_uid)
        )
    ).scalar_one_or_none()
    assert no_social is None

    access_token, _ = await complete_signup(
        signup_token=login_result.signup_token,
        agree_terms=True,
        nickname=uuid.uuid4().hex[:8],
        location="강원 속초시",
        db=db_session,
        redis=redis_client,
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


# 1-1. 닉네임 중복으로 가입 실패해도 signup_token은 소비되지 않아, 같은 토큰으로 다른
# 닉네임을 넣어 재시도하면 성공한다 (2026-09-11 리뷰 지적 - 예전엔 실패해도 토큰이
# 이미 지워진 뒤라 소셜 로그인부터 다시 해야 했음)
async def test_complete_signup_allows_retry_after_duplicate_nickname(db_session, ctx, redis_client):
    taken_nickname = uuid.uuid4().hex[:8]
    existing = await _make_user(db_session, ctx)
    existing.nickname = taken_nickname
    await db_session.commit()

    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")
    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    with pytest.raises(HTTPException) as exc_info:
        await complete_signup(
            signup_token=login_result.signup_token,
            agree_terms=True,
            nickname=taken_nickname,
            location="강원 속초시",
            db=db_session,
            redis=redis_client,
        )
    assert exc_info.value.status_code == 409

    access_token, _ = await complete_signup(
        signup_token=login_result.signup_token,
        agree_terms=True,
        nickname=uuid.uuid4().hex[:8],
        location="강원 속초시",
        db=db_session,
        redis=redis_client,
    )
    ctx.user_ids.append(int(decode_token(access_token)["sub"]))


# 1-2. 약관 미동의(agree_terms=False)로 실패해도 signup_token은 그대로 남아 재시도 가능
async def test_complete_signup_rejects_missing_agreement_and_allows_retry(
    db_session, ctx, redis_client
):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")
    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    with pytest.raises(HTTPException) as exc_info:
        await complete_signup(
            signup_token=login_result.signup_token,
            agree_terms=False,
            nickname=uuid.uuid4().hex[:8],
            location="강원 속초시",
            db=db_session,
            redis=redis_client,
        )
    assert exc_info.value.status_code == 400

    access_token, _ = await complete_signup(
        signup_token=login_result.signup_token,
        agree_terms=True,
        nickname=uuid.uuid4().hex[:8],
        location="강원 속초시",
        db=db_session,
        redis=redis_client,
    )
    ctx.user_ids.append(int(decode_token(access_token)["sub"]))


# 1-3. 존재하지 않거나 만료된 signup_token은 400
async def test_complete_signup_rejects_unknown_token(db_session, redis_client):
    with pytest.raises(HTTPException) as exc_info:
        await complete_signup(
            signup_token=uuid.uuid4().hex,
            agree_terms=True,
            nickname=uuid.uuid4().hex[:8],
            location="강원 속초시",
            db=db_session,
            redis=redis_client,
        )
    assert exc_info.value.status_code == 400


# 1-4. 같은 signup_token으로 처리 중인 요청이 이미 있으면(락 선점) 즉시 409로 막힘 -
# get→delete가 원자적이지 않아 동시 요청이 같은 가입정보를 같이 읽는 경합을 막기 위한 락
async def test_complete_signup_rejects_concurrent_duplicate_request(db_session, redis_client):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")
    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    # 다른 요청이 이미 이 토큰을 처리 중인 상황을 흉내: 락을 미리 선점해둠
    lock_key = f"signup_lock:{login_result.signup_token}"
    await redis_client.set(lock_key, "1", nx=True, ex=30)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await complete_signup(
                signup_token=login_result.signup_token,
                agree_terms=True,
                nickname=uuid.uuid4().hex[:8],
                location="강원 속초시",
                db=db_session,
                redis=redis_client,
            )
        assert exc_info.value.status_code == 409
    finally:
        await redis_client.delete(lock_key)


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
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    assert int(decode_token(login_result.access_token)["sub"]) == existing_user.user_id
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


# 4-1. 탈퇴한 유저는 Redis에 옛 refresh token이 남아있어도 재발급 거부됨
async def test_refresh_tokens_rejects_withdrawn_user(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    refresh_token, jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, jti, redis_client)

    # Redis 정리가 실패한 상황을 흉내: DB만 탈퇴 처리하고 Redis의 refresh token은 그대로 둠
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await refresh_tokens(refresh_token, db_session, redis_client)

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
# 이 코스는 다른 유저(other_runner)의 기록/리뷰가 얽혀있어(엮여있음) 하드삭제 대상이
# 아니다 — created_by만 NULL 처리되고 코스 자체는 보존된다 (2026-09-10 팀 결정)
async def test_withdraw_user_anonymizes_and_nullifies_related_data(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    other_runner = await _make_user(db_session, ctx)
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
    # 다른 유저가 이 코스로 뛰고 리뷰를 남김 — 이게 있어야 "엮여있음"으로 판정되어
    # 코스가 보존된다
    db_session.add(
        Record(
            user_id=other_runner.user_id,
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            is_completed=True,
        )
    )
    db_session.add(
        Review(
            user_id=other_runner.user_id,
            course_id=course.course_id,
            content="다른 유저 리뷰",
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
        await db_session.execute(
            select(Record).where(Record.course_id == course.course_id, Record.user_id.is_(None))
        )
    ).scalar_one()
    assert record.user_id is None

    review = (
        await db_session.execute(
            select(Review).where(Review.course_id == course.course_id, Review.user_id.is_(None))
        )
    ).scalar_one()
    assert review.user_id is None

    # 다른 유저의 기록/리뷰는 그대로 보존됨
    other_record = (
        await db_session.execute(
            select(Record).where(
                Record.course_id == course.course_id, Record.user_id == other_runner.user_id
            )
        )
    ).scalar_one()
    assert other_record is not None

    refreshed_course = (
        await db_session.execute(select(Course).where(Course.course_id == course.course_id))
    ).scalar_one()
    assert refreshed_course.created_by is None


# 8-1. 탈퇴 유저의 커스텀 코스 중 본인 기록/리뷰만 있고 다른 유저와 안 엮인 코스는
# created_by만 NULL 처리하는 게 아니라 코스 row 자체를 하드삭제한다 (2026-09-10 팀 결정)
async def test_withdraw_user_hard_deletes_course_with_only_own_records(
    db_session, ctx, redis_client
):
    user = await _make_user(db_session, ctx)
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=user.user_id,
    )
    db_session.add(course)
    await db_session.flush()
    course_id = course.course_id
    ctx.course_ids.append(course_id)

    db_session.add(
        Record(
            user_id=user.user_id,
            course_id=course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            is_completed=True,
        )
    )
    db_session.add(
        Review(
            user_id=user.user_id,
            course_id=course_id,
            content="내 코스 내 리뷰",
            difficulty="NORMAL",
        )
    )
    await db_session.commit()

    access_token = create_access_token(user.user_id)
    await withdraw_user(user, access_token, db_session, redis_client)

    assert (
        await db_session.execute(select(Course).where(Course.course_id == course_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Record).where(Record.course_id == course_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Review).where(Review.course_id == course_id))
    ).scalar_one_or_none() is None


# 8-2. 아무도 안 쓴(기록/리뷰 자체가 없는) 코스도 마찬가지로 하드삭제된다
async def test_withdraw_user_hard_deletes_untouched_course(db_session, ctx, redis_client):
    user = await _make_user(db_session, ctx)
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=user.user_id,
    )
    db_session.add(course)
    await db_session.flush()
    course_id = course.course_id
    ctx.course_ids.append(course_id)
    await db_session.commit()

    access_token = create_access_token(user.user_id)
    await withdraw_user(user, access_token, db_session, redis_client)

    assert (
        await db_session.execute(select(Course).where(Course.course_id == course_id))
    ).scalar_one_or_none() is None


# 8-3. 이미 탈퇴해 user_id가 NULL인 다른 유저의 기록으로 얽힌 코스도 보존된다(하드삭제 안 됨)
async def test_withdraw_user_preserves_course_entangled_by_withdrawn_other_user(
    db_session, ctx, redis_client
):
    user = await _make_user(db_session, ctx)
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=user.user_id,
    )
    db_session.add(course)
    await db_session.flush()
    course_id = course.course_id
    ctx.course_ids.append(course_id)

    # user_id가 NULL인 기록 - 이미 탈퇴해 익명화된 "다른" 유저가 예전에 남긴 흔적을 흉내
    db_session.add(
        Record(
            user_id=None,
            course_id=course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            is_completed=True,
        )
    )
    await db_session.commit()

    access_token = create_access_token(user.user_id)
    await withdraw_user(user, access_token, db_session, redis_client)

    refreshed_course = (
        await db_session.execute(select(Course).where(Course.course_id == course_id))
    ).scalar_one()
    assert refreshed_course.created_by is None


# 8-4. 하드삭제 시 코스 이미지/경유지/편의시설 매핑/리뷰 요약까지 전부 지워지고,
# R2 정리용 반환값에 코스 이미지 + 리뷰 이미지 URL이 전부 포함된다
async def test_delete_orphaned_custom_courses_removes_all_related_rows_and_returns_image_urls(
    db_session, ctx
):
    user = await _make_user(db_session, ctx)
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=user.user_id,
    )
    db_session.add(course)
    await db_session.flush()
    course_id = course.course_id
    ctx.course_ids.append(course_id)

    course_image_url = f"https://example.com/course-{uuid.uuid4().hex[:8]}.jpg"
    db_session.add(CourseWaypoint(course_id=course_id, sequence=0, latitude=1.0, longitude=1.0))
    db_session.add(CourseImage(course_id=course_id, image_url=course_image_url))

    facility = Facility(
        facility_type=FacilityType.RESTROOM,
        facility_name=f"pytest-facility-{uuid.uuid4().hex[:8]}",
        latitude=1.0,
        longitude=1.0,
    )
    db_session.add(facility)
    await db_session.flush()
    db_session.add(CourseFacility(course_id=course_id, facility_id=facility.facility_id))

    review = Review(
        user_id=user.user_id, course_id=course_id, content="본인 리뷰", difficulty="NORMAL"
    )
    db_session.add(review)
    await db_session.flush()
    review_image_url = f"https://example.com/review-{uuid.uuid4().hex[:8]}.jpg"
    db_session.add(ReviewImage(review_id=review.review_id, image_url=review_image_url))
    db_session.add(ReviewSummary(course_id=course_id, summary="요약", review_count=1))
    await db_session.commit()

    urls = await _delete_orphaned_custom_courses(user.user_id, db_session)
    await db_session.commit()

    assert set(urls) == {course_image_url, review_image_url}
    assert (
        await db_session.execute(select(Course).where(Course.course_id == course_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(
            select(CourseWaypoint).where(CourseWaypoint.course_id == course_id)
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(CourseImage).where(CourseImage.course_id == course_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(
            select(CourseFacility).where(CourseFacility.course_id == course_id)
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == course_id)
        )
    ).scalar_one_or_none() is None

    # facility 자체는 다른 코스와도 연결될 수 있는 공용 자원이라 삭제 대상이 아님
    remaining_facility = (
        await db_session.execute(
            select(Facility).where(Facility.facility_id == facility.facility_id)
        )
    ).scalar_one()
    assert remaining_facility is not None
    await db_session.delete(remaining_facility)
    await db_session.commit()


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


# 12. 계정당 소셜 연동 1개 정책이 DB 유니크 제약으로 강제됨
async def test_social_account_user_id_is_unique(db_session, ctx):
    user = await _make_user(db_session, ctx)
    db_session.add(
        SocialAccount(
            user_id=user.user_id, provider_type=ProviderType.KAKAO, provider_uid=uuid.uuid4().hex
        )
    )
    await db_session.commit()

    db_session.add(
        SocialAccount(
            user_id=user.user_id, provider_type=ProviderType.NAVER, provider_uid=uuid.uuid4().hex
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# 13. last_login_at 갱신이 내부에서 실패해도 가입 완료 자체는 성공함
async def test_complete_signup_succeeds_even_if_last_login_update_fails(
    db_session, ctx, redis_client
):
    """_touch_last_login이 내부 rollback을 타도, 가입 완료 함수는 user_id를 정수로 미리
    꺼내둔 값만 쓰므로 만료된 user 객체를 다시 건드리다 MissingGreenlet로 깨지지 않는다.

    User/SocialAccount 생성 + last_login_at 갱신 커밋이 실제로 일어나는 지점이
    kakao_login()이 아니라 complete_signup()으로 옮겨졌으므로(약관 동의 절차 도입),
    이 테스트도 그에 맞춰 complete_signup()을 대상으로 한다.
    """
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    original_commit = db_session.commit
    call_count = {"n": 0}

    async def flaky_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:  # 유저+소셜계정 생성 커밋은 정상 통과
            return await original_commit()
        raise SQLAlchemyError("boom")  # _touch_last_login의 커밋만 실패시킴

    with patch.object(db_session, "commit", side_effect=flaky_commit):
        access_token, refresh_token = await complete_signup(
            signup_token=login_result.signup_token,
            agree_terms=True,
            nickname=uuid.uuid4().hex[:8],
            location="강원 속초시",
            db=db_session,
            redis=redis_client,
        )

    assert access_token
    assert refresh_token
    ctx.user_ids.append(int(decode_token(access_token)["sub"]))


# 14. 공개 프로필 조회 - 활성 유저는 정상 조회됨
async def test_get_public_profile_returns_active_user(db_session, ctx):
    user = await _make_user(db_session, ctx)
    user.location = "강원 속초시"
    await db_session.commit()

    profile = await get_public_profile(user.user_id, db_session)

    assert profile.user_id == user.user_id
    assert profile.location == "강원 속초시"


# 15. 공개 프로필 조회 - 탈퇴했거나 존재하지 않는 유저는 404
async def test_get_public_profile_rejects_withdrawn_or_missing_user(db_session, ctx):
    user = await _make_user(db_session, ctx)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await get_public_profile(user.user_id, db_session)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await get_public_profile(999_999_999, db_session)
    assert exc_info.value.status_code == 404


# 16. 신규가입 가입정보 임시저장(Redis setex) 실패 시 503
async def test_kakao_login_returns_503_on_redis_setex_failure(db_session, redis_client):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")

    with (
        patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)),
        patch.object(redis_client, "setex", side_effect=RedisError("boom")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await kakao_login(
                code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
            )

    assert exc_info.value.status_code == 503


# 17. complete_signup에서 가입정보 조회(Redis get) 실패 시 503
async def test_complete_signup_returns_503_on_redis_get_failure(db_session, redis_client):
    provider_uid = uuid.uuid4().hex
    state = uuid.uuid4().hex
    await redis_client.setex(f"oauth:state:kakao:{state}", 300, "1")
    with patch("httpx.AsyncClient", return_value=_fake_kakao_client(provider_uid)):
        login_result = await kakao_login(
            code="fake-code", state=state, cookie_state=state, db=db_session, redis=redis_client
        )

    try:
        with patch.object(redis_client, "get", side_effect=RedisError("boom")):
            with pytest.raises(HTTPException) as exc_info:
                await complete_signup(
                    signup_token=login_result.signup_token,
                    agree_terms=True,
                    nickname=uuid.uuid4().hex[:8],
                    location="강원 속초시",
                    db=db_session,
                    redis=redis_client,
                )
        assert exc_info.value.status_code == 503
    finally:
        # 락은 finally에서 정상적으로 풀렸어야 하지만, 혹시 남아있으면 다음 테스트에 안 새게 정리
        await redis_client.delete(f"signup_lock:{login_result.signup_token}")
