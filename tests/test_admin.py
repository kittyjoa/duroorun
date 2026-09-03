"""관리자 - 강제 탈퇴/밴 관리, 대시보드 통계 테스트."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.security import get_current_admin
from app.domain.admin import service as admin_service
from app.domain.admin.service import KST, _period_boundaries
from app.domain.course.models import Course, CourseType
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.user.models import BannedAccount, ProviderType, SocialAccount, User, UserRole
from app.domain.user.service import _check_not_banned, force_withdraw_user


@dataclass
class AdminTestContext:
    """테스트 중 생성한 row들을 모아뒀다가 종료 시 정리한다."""

    user_ids: list[int] = field(default_factory=list)
    course_ids: list[int] = field(default_factory=list)
    banned_ids: list[int] = field(default_factory=list)


@pytest_asyncio.fixture
async def ctx(db_session):
    context = AdminTestContext()
    yield context

    if context.course_ids:
        await db_session.execute(delete(Record).where(Record.course_id.in_(context.course_ids)))
        await db_session.execute(delete(Review).where(Review.course_id.in_(context.course_ids)))
    if context.user_ids:
        await db_session.execute(
            delete(SocialAccount).where(SocialAccount.user_id.in_(context.user_ids))
        )
        await db_session.execute(delete(Record).where(Record.user_id.in_(context.user_ids)))
        await db_session.execute(delete(Review).where(Review.user_id.in_(context.user_ids)))
        await db_session.execute(delete(User).where(User.user_id.in_(context.user_ids)))
    if context.course_ids:
        await db_session.execute(delete(Course).where(Course.course_id.in_(context.course_ids)))
    if context.banned_ids:
        await db_session.execute(
            delete(BannedAccount).where(BannedAccount.id.in_(context.banned_ids))
        )
    await db_session.commit()


async def _make_user_with_social(
    db_session, ctx: AdminTestContext, provider_type: ProviderType = ProviderType.KAKAO
) -> tuple[User, str]:
    """소셜 계정이 연동된 유저 하나를 만들고 (user, provider_uid)를 반환한다."""
    provider_uid = uuid.uuid4().hex
    user = User(nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.flush()
    ctx.user_ids.append(user.user_id)

    db_session.add(
        SocialAccount(user_id=user.user_id, provider_type=provider_type, provider_uid=provider_uid)
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user, provider_uid


class _FakeRedis:
    """force_withdraw_user의 refresh token 삭제 호출을 흡수하는 더미 (실제 Redis 불필요)."""

    async def delete(self, *args, **kwargs):
        return 0


# 1. 일반 사용자는 /admin/* 접근 불가
async def test_general_user_cannot_access_admin():
    normal_user = User(user_id=1, user_role=UserRole.USER)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin(normal_user)

    assert exc_info.value.status_code == 403


# 2. 강제 탈퇴 시 유저 익명화와 밴 정보가 함께 저장됨
async def test_force_withdraw_anonymizes_user_and_records_ban(db_session, ctx):
    user, provider_uid = await _make_user_with_social(db_session, ctx)

    await force_withdraw_user(user, "욕설", db_session, _FakeRedis())

    refreshed = (
        await db_session.execute(select(User).where(User.user_id == user.user_id))
    ).scalar_one()
    assert refreshed.deleted_at is not None
    assert refreshed.nickname is None

    banned = (
        await db_session.execute(
            select(BannedAccount).where(BannedAccount.provider_uid == provider_uid)
        )
    ).scalar_one()
    ctx.banned_ids.append(banned.id)
    assert banned.provider_type == ProviderType.KAKAO
    assert banned.reason == "욕설"


# 3. 강제 탈퇴 중 오류 발생 시 둘 다 롤백됨
async def test_force_withdraw_rolls_back_on_error(db_session, ctx):
    user, provider_uid = await _make_user_with_social(db_session, ctx)
    user_id = user.user_id  # rollback 후 만료된 속성에 접근하지 않도록 미리 저장

    # 같은 provider_type+provider_uid로 밴을 미리 만들어둬서, force_withdraw_user가
    # 새 BannedAccount를 insert할 때 UniqueConstraint 위반이 나도록 유도
    pre_existing = BannedAccount(
        provider_type=ProviderType.KAKAO, provider_uid=provider_uid, reason="pre-existing"
    )
    db_session.add(pre_existing)
    await db_session.commit()
    ctx.banned_ids.append(pre_existing.id)

    with pytest.raises(IntegrityError):
        await force_withdraw_user(user, "욕설", db_session, _FakeRedis())
    await db_session.rollback()

    refreshed = (
        await db_session.execute(select(User).where(User.user_id == user_id))
    ).scalar_one()
    assert refreshed.deleted_at is None
    assert refreshed.nickname is not None


# 4. 밴 계정은 카카오·네이버·구글 신규 가입 불가
@pytest.mark.parametrize("provider_type", list(ProviderType))
async def test_banned_account_cannot_signup(db_session, ctx, provider_type):
    provider_uid = uuid.uuid4().hex
    banned = BannedAccount(provider_type=provider_type, provider_uid=provider_uid, reason="테스트")
    db_session.add(banned)
    await db_session.commit()
    ctx.banned_ids.append(banned.id)

    with pytest.raises(HTTPException) as exc_info:
        await _check_not_banned(provider_type, provider_uid, db_session)

    assert exc_info.value.status_code == 403


# 5. 밴 해제 후 재가입 가능
async def test_unban_allows_signup_again(db_session, ctx):
    provider_uid = uuid.uuid4().hex
    banned = BannedAccount(
        provider_type=ProviderType.NAVER, provider_uid=provider_uid, reason="테스트"
    )
    db_session.add(banned)
    await db_session.commit()

    await admin_service.unban_account(banned.id, db_session)

    # 예외 없이 통과해야 함 (더 이상 밴 상태가 아님)
    await _check_not_banned(ProviderType.NAVER, provider_uid, db_session)


# 6. 이미 탈퇴한 유저 강제 탈퇴 시 404
async def test_force_withdraw_already_withdrawn_user_returns_404(db_session, ctx):
    user, _ = await _make_user_with_social(db_session, ctx)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await admin_service.force_withdraw_user(user.user_id, "욕설", db_session, _FakeRedis())

    assert exc_info.value.status_code == 404


# 7. 없는 밴 ID 해제 시 404
async def test_unban_nonexistent_id_returns_404(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await admin_service.unban_account(999_999_999, db_session)

    assert exc_info.value.status_code == 404


# 8. 완료하지 않은 기록은 완주 통계에서 제외
async def test_incomplete_records_excluded_from_completion_stats(db_session, ctx):
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        distance=10.0,
    )
    db_session.add(course)
    await db_session.flush()
    ctx.course_ids.append(course.course_id)

    user = User(nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.flush()
    ctx.user_ids.append(user.user_id)

    db_session.add_all([
        Record(
            user_id=user.user_id,
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            is_completed=True,
        ),
        Record(
            user_id=user.user_id,
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=None,
            is_completed=False,
        ),
    ])
    await db_session.commit()

    stats = await admin_service.get_record_stats(db_session)

    # 이 코스는 커스텀 코스라 완주 1건분 거리(10.0)만 총 거리에 반영돼야 함
    assert stats.total_distance_km >= 10.0
    completed_records_for_course = (
        await db_session.execute(
            select(Record).where(
                Record.course_id == course.course_id, Record.is_completed.is_(True)
            )
        )
    ).scalars().all()
    assert len(completed_records_for_course) == 1


# 9. 일·주·월·연도 경계 시각 집계 (KST 기준)
def test_period_boundaries_uses_kst():
    # 2026-09-01 23:00 UTC == 2026-09-02 08:00 KST (수요일)
    now_utc = datetime(2026, 9, 1, 23, 0, tzinfo=UTC)

    today_start, week_start, month_start, year_start = _period_boundaries(now_utc)

    assert today_start == datetime(2026, 9, 2, 0, 0, tzinfo=KST)
    assert week_start == datetime(2026, 8, 31, 0, 0, tzinfo=KST)  # 이번주 월요일
    assert month_start == datetime(2026, 9, 1, 0, 0, tzinfo=KST)
    assert year_start == datetime(2026, 1, 1, 0, 0, tzinfo=KST)


# 10. 인기 코스 동률 시 리뷰 개수 많은 순으로 2차 정렬
async def test_popular_courses_tiebreak_by_review_count(db_session, ctx):
    course_more_reviews = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        distance=5.0,
    )
    course_fewer_reviews = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        distance=5.0,
    )
    db_session.add_all([course_more_reviews, course_fewer_reviews])
    await db_session.flush()
    ctx.course_ids.extend([course_more_reviews.course_id, course_fewer_reviews.course_id])

    # 두 코스 다 완주 1건씩 만들어 완주횟수를 동률로 맞춤
    for course in (course_more_reviews, course_fewer_reviews):
        runner = User(nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}")
        db_session.add(runner)
        await db_session.flush()
        ctx.user_ids.append(runner.user_id)
        db_session.add(
            Record(
                user_id=runner.user_id,
                course_id=course.course_id,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                is_completed=True,
            )
        )
    await db_session.commit()

    # course_more_reviews에만 리뷰 2개 추가 (완주횟수는 그대로 동률 유지)
    for _ in range(2):
        reviewer = User(nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}")
        db_session.add(reviewer)
        await db_session.flush()
        ctx.user_ids.append(reviewer.user_id)
        db_session.add(
            Review(
                user_id=reviewer.user_id,
                course_id=course_more_reviews.course_id,
                content="좋아요",
                difficulty="NORMAL",
            )
        )
    await db_session.commit()

    results = await admin_service._get_popular_courses(db_session, CourseType.CUSTOM, 50)
    result_course_ids = [item.course_id for item in results]

    assert result_course_ids.index(course_more_reviews.course_id) < result_course_ids.index(
        course_fewer_reviews.course_id
    )


# 11. 미래 시각으로 저장된 데이터는 기간 통계에 포함되지 않음
async def test_period_counts_excludes_future_timestamps(db_session, ctx):
    baseline = await admin_service._get_period_counts(db_session, User.created_at)

    future_user = User(
        nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}",
        created_at=datetime.now(UTC) + timedelta(days=365),
    )
    db_session.add(future_user)
    await db_session.commit()
    ctx.user_ids.append(future_user.user_id)

    after = await admin_service._get_period_counts(db_session, User.created_at)

    assert after.this_year == baseline.this_year
    assert after.this_month == baseline.this_month


# 12. 최근 로그인했더라도 탈퇴한 유저는 활성 유저 수에서 제외
async def test_active_users_30d_excludes_withdrawn_users(db_session, ctx):
    baseline = (await admin_service.get_user_stats(db_session)).active_users_30d

    user = User(
        nickname=f"pytest-admin-{uuid.uuid4().hex[:12]}",
        last_login_at=datetime.now(UTC),
        deleted_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    ctx.user_ids.append(user.user_id)

    after = (await admin_service.get_user_stats(db_session)).active_users_30d

    assert after == baseline
