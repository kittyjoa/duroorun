"""관리자 대시보드 - 비즈니스 로직 (통계 집계 등)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.admin.schemas import (
    BannedAccountListResponse,
    BannedAccountResponse,
    CoursePopularityItem,
    CourseStatsResponse,
    DashboardStatsResponse,
    MonthlyYearlyCountResponse,
    PeriodCountResponse,
    RecordStatsResponse,
    UserStatsResponse,
)
from app.domain.course.models import Course, CourseType
from app.domain.facility.models import Facility, FacilityType
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.user.models import BannedAccount, User
from app.domain.user.service import force_withdraw_user as _force_withdraw_user

KST = ZoneInfo("Asia/Seoul")


async def force_withdraw_user(user_id: int, reason: str, db: AsyncSession, redis: Redis) -> None:
    """유저 강제 탈퇴 (관리자 전용)."""
    result = await db.execute(
        select(User).where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 탈퇴한 유저입니다",
        )

    await _force_withdraw_user(user, reason, db, redis)


async def get_banned_accounts(page: int, size: int, db: AsyncSession) -> BannedAccountListResponse:
    """밴(재가입 차단) 계정 목록 조회."""
    total = (await db.execute(select(func.count()).select_from(BannedAccount))).scalar_one()

    result = await db.execute(
        select(BannedAccount)
        .order_by(BannedAccount.banned_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = result.scalars().all()

    return BannedAccountListResponse(
        items=[BannedAccountResponse.model_validate(b) for b in items],
        total=total,
        page=page,
        size=size,
    )


async def unban_account(banned_id: int, db: AsyncSession) -> None:
    """밴 해제 - banned_accounts row 삭제."""
    result = await db.execute(delete(BannedAccount).where(BannedAccount.id == banned_id))
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 밴 계정입니다",
        )
    await db.commit()


def _period_boundaries(now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """오늘/이번주(월요일)/이번달/올해 시작 시각을 한국 시간(KST) 기준으로 반환합니다."""
    now_kst = now.astimezone(KST)
    today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    return today_start, week_start, month_start, year_start


async def _get_period_counts(
    db: AsyncSession, timestamp_column: ColumnElement[datetime | None]
) -> PeriodCountResponse:
    """주어진 시각 컬럼 기준으로 오늘/이번주/이번달/올해 카운트를 한 번의 쿼리로 집계합니다.

    잘못 저장된 미래 시각 데이터가 통계에 섞이지 않도록 현재 시각을 상한으로도 검사한다.
    """
    now = datetime.now(UTC)
    today_start, week_start, month_start, year_start = _period_boundaries(now)

    result = (
        await db.execute(
            select(
                func.count(case((timestamp_column.between(today_start, now), 1))),
                func.count(case((timestamp_column.between(week_start, now), 1))),
                func.count(case((timestamp_column.between(month_start, now), 1))),
                func.count(case((timestamp_column.between(year_start, now), 1))),
            )
        )
    ).one()

    return PeriodCountResponse(
        today=result[0], this_week=result[1], this_month=result[2], this_year=result[3]
    )


async def _get_monthly_yearly_counts(
    db: AsyncSession, timestamp_column: ColumnElement[datetime | None]
) -> MonthlyYearlyCountResponse:
    """주어진 시각 컬럼 기준으로 이번달/올해 카운트를 한 번의 쿼리로 집계합니다.

    잘못 저장된 미래 시각 데이터가 통계에 섞이지 않도록 현재 시각을 상한으로도 검사한다.
    """
    now = datetime.now(UTC)
    _, _, month_start, year_start = _period_boundaries(now)

    result = (
        await db.execute(
            select(
                func.count(case((timestamp_column.between(month_start, now), 1))),
                func.count(case((timestamp_column.between(year_start, now), 1))),
            )
        )
    ).one()

    return MonthlyYearlyCountResponse(this_month=result[0], this_year=result[1])


async def get_user_stats(db: AsyncSession) -> UserStatsResponse:
    """대시보드 - 유저 통계."""
    total_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
    ).scalar_one()

    active_users_30d = (
        await db.execute(
            select(func.count(func.distinct(Record.user_id))).where(
                Record.created_at >= datetime.now(UTC) - timedelta(days=30),
                Record.user_id.is_not(None),
            )
        )
    ).scalar_one()

    return UserStatsResponse(
        total_users=total_users,
        new_users=await _get_period_counts(db, User.created_at),
        active_users_30d=active_users_30d,
        withdrawn_users=await _get_period_counts(db, User.deleted_at),
    )


async def get_record_stats(db: AsyncSession) -> RecordStatsResponse:
    """대시보드 - 러닝 기록 통계."""
    total_distance_km, total_completions = (
        await db.execute(
            select(
                func.coalesce(func.sum(Course.distance), 0),
                func.count(Record.record_id),
            )
            .select_from(Record)
            .join(Course, Record.course_id == Course.course_id)
            .where(Record.is_completed.is_(True))
        )
    ).one()

    completions = await _get_period_counts(
        db, case((Record.is_completed.is_(True), Record.ended_at))
    )

    return RecordStatsResponse(
        total_distance_km=total_distance_km,
        total_completions=total_completions,
        completions=completions,
    )


async def _get_popular_courses(
    db: AsyncSession, course_type: CourseType | None, limit: int
) -> list[CoursePopularityItem]:
    """완주 횟수 기준 인기 코스 랭킹 (course_type=None이면 전체).

    완주 횟수가 같으면 리뷰 개수가 많은 순으로 2차 정렬해 순서를 안정적으로 고정한다.
    Review는 Record와 별도로 Course에 N:1 관계라, 그냥 join하면 조합이 곱해져
    완주 횟수 집계가 틀어지므로 상관 서브쿼리로 따로 계산한다.
    """
    review_count_subquery = (
        select(func.count(Review.review_id))
        .where(Review.course_id == Course.course_id)
        .correlate(Course)
        .scalar_subquery()
    )

    query = (
        select(
            Course.course_id,
            Course.course_name,
            func.count(Record.record_id).label("completion_count"),
        )
        .join(Record, Record.course_id == Course.course_id)
        .where(Record.is_completed.is_(True))
    )
    if course_type is not None:
        query = query.where(Course.course_type == course_type)
    query = (
        query.group_by(Course.course_id, Course.course_name)
        .order_by(func.count(Record.record_id).desc(), review_count_subquery.desc())
        .limit(limit)
    )

    rows = (await db.execute(query)).all()
    return [
        CoursePopularityItem(
            course_id=row.course_id,
            course_name=row.course_name,
            completion_count=row.completion_count,
        )
        for row in rows
    ]


async def get_course_stats(db: AsyncSession) -> CourseStatsResponse:
    """대시보드 - 코스 통계."""
    total_custom_courses = (
        await db.execute(
            select(func.count())
            .select_from(Course)
            .where(Course.course_type == CourseType.CUSTOM)
        )
    ).scalar_one()

    custom_course_registrations = await _get_monthly_yearly_counts(
        db, case((Course.course_type == CourseType.CUSTOM, Course.created_at))
    )

    return CourseStatsResponse(
        popular_overall=await _get_popular_courses(db, None, 5),
        popular_drnb=await _get_popular_courses(db, CourseType.DRNB, 3),
        popular_custom=await _get_popular_courses(db, CourseType.CUSTOM, 3),
        total_custom_courses=total_custom_courses,
        custom_course_registrations=custom_course_registrations,
    )


async def get_dashboard_stats(db: AsyncSession) -> DashboardStatsResponse:
    """관리자 대시보드 통계 전체 조회."""
    total_reviews = (await db.execute(select(func.count()).select_from(Review))).scalar_one()

    facility_rows = (
        await db.execute(
            select(Facility.facility_type, func.count())
            .where(Facility.is_active.is_(True))
            .group_by(Facility.facility_type)
        )
    ).all()
    facility_counts_by_type = {facility_type: 0 for facility_type in FacilityType}
    for facility_type, count in facility_rows:
        facility_counts_by_type[facility_type] = count

    return DashboardStatsResponse(
        users=await get_user_stats(db),
        records=await get_record_stats(db),
        courses=await get_course_stats(db),
        total_reviews=total_reviews,
        facility_counts_by_type=facility_counts_by_type,
    )
