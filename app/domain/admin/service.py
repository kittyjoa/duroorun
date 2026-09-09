"""관리자 대시보드 - 비즈니스 로직 (통계 집계 등)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import Select, case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.security import get_active_user
from app.domain.admin.schemas import (
    BannedAccountListResponse,
    BannedAccountResponse,
    CoursePopularityItem,
    CourseStatsResponse,
    DashboardStatsResponse,
    MonthlyYearlyCountResponse,
    PeriodCountResponse,
    RecordStatsResponse,
    UserSearchListResponse,
    UserStatsResponse,
)
from app.domain.course.models import Course, CourseType
from app.domain.facility.models import Facility, FacilityType
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.user.models import BannedAccount, User, UserRole
from app.domain.user.schemas import PublicProfileResponse
from app.domain.user.service import force_withdraw_user as _force_withdraw_user

KST = ZoneInfo("Asia/Seoul")


async def _paginate(
    db: AsyncSession, select_stmt: Select[Any], count_stmt: Select[Any], page: int, size: int
) -> tuple[Sequence[Any], int]:
    """count 조회 + offset/limit 조회를 묶어서 (items, total)을 반환합니다.

    밴 목록/유저 검색처럼 정렬만 다르고 나머지는 동일한 offset 페이지네이션 골격을 공유한다.
    """
    total = (await db.execute(count_stmt)).scalar_one()
    items = (await db.execute(select_stmt.offset((page - 1) * size).limit(size))).scalars().all()
    return items, total


async def force_withdraw_user(
    admin_id: int, user_id: int, reason: str, db: AsyncSession, redis: Redis
) -> None:
    """유저 강제 탈퇴 (관리자 전용)."""
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="자기 자신은 강제 탈퇴시킬 수 없습니다",
        )

    # 잠금 없이 조회하면, 이 조회와 아래 소셜 계정 조회 사이에 본인 탈퇴가 끼어들어
    # 밴 등록 없이 강제 탈퇴가 "성공"해버릴 수 있음 — 행 잠금으로 그 틈을 없앤다
    user = await get_active_user(user_id, db, for_update=True)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 탈퇴한 유저입니다",
        )
    if user.user_role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 계정은 강제 탈퇴시킬 수 없습니다",
        )

    try:
        await _force_withdraw_user(user, admin_id, reason, db, redis)
    except IntegrityError:
        await db.rollback()
        # 동시에 들어온 중복 강제 탈퇴 요청 등으로 밴 등록이 충돌한 경우
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 처리된 요청입니다",
        ) from None


async def get_banned_accounts(page: int, size: int, db: AsyncSession) -> BannedAccountListResponse:
    """밴(재가입 차단) 계정 목록 조회."""
    items, total = await _paginate(
        db,
        select(BannedAccount).order_by(BannedAccount.banned_at.desc(), BannedAccount.id.desc()),
        select(func.count()).select_from(BannedAccount),
        page,
        size,
    )

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


async def search_users(
    nickname: str, page: int, size: int, db: AsyncSession
) -> UserSearchListResponse:
    """닉네임으로 유저를 검색합니다 (부분일치, 관리자 등급 제외).

    강제 탈퇴 대상을 다른 관리자에게 전달받았을 때 프로필을 찾아가기 위한 용도.
    탈퇴한 유저는 익명화로 nickname이 NULL이라 조건상 자동으로 제외된다.
    """
    nickname = nickname.strip()
    if not nickname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="검색할 닉네임을 입력해주세요",
        )

    # %, _는 LIKE 와일드카드로 해석되므로 이스케이프하지 않으면 "%"만 검색해도
    # 전체 유저가 조회되어, 검색어 없이는 조회 안 되게 한 프론트 가드가 무의미해짐
    escaped = nickname.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    where_clause = (User.user_role != UserRole.ADMIN) & User.nickname.ilike(
        f"%{escaped}%", escape="\\"
    )

    items, total = await _paginate(
        db,
        select(User).where(where_clause).order_by(User.nickname.asc(), User.user_id.asc()),
        select(func.count()).select_from(User).where(where_clause),
        page,
        size,
    )

    return UserSearchListResponse(
        items=[PublicProfileResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        size=size,
    )


def _period_boundaries(now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """오늘/이번주(월요일)/이번달/올해 시작 시각을 한국 시간(KST) 기준으로 반환합니다."""
    now_kst = now.astimezone(KST)
    today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    return today_start, week_start, month_start, year_start


async def _count_by_boundaries(
    db: AsyncSession,
    timestamp_column: ColumnElement[datetime | None],
    boundaries: tuple[datetime, ...],
    now: datetime,
    extra_where: ColumnElement[bool] | None = None,
) -> tuple[int, ...]:
    """주어진 시각 경계들(오늘/이번주/... 시작 시각) 각각을 하한으로, 현재 시각을 상한으로 하는
    카운트를 한 번의 쿼리로 집계합니다. 잘못 저장된 미래 시각 데이터가 섞이지 않도록 상한도 검사.

    extra_where로 넘긴 조건은 이 쿼리 자체를 필터링해 인덱스를 태울 수 있게 한다
    (timestamp_column을 CASE 안에서만 쓰면 조건이 있어도 인덱스를 못 탐).
    """
    query = select(
        *[func.count(case((timestamp_column.between(b, now), 1))) for b in boundaries]
    )
    if extra_where is not None:
        query = query.where(extra_where)
    return (await db.execute(query)).one()


async def _get_period_counts(
    db: AsyncSession,
    timestamp_column: ColumnElement[datetime | None],
    extra_where: ColumnElement[bool] | None = None,
) -> PeriodCountResponse:
    """주어진 시각 컬럼 기준으로 오늘/이번주/이번달/올해 카운트를 집계합니다."""
    now = datetime.now(UTC)
    boundaries = _period_boundaries(now)

    result = await _count_by_boundaries(db, timestamp_column, boundaries, now, extra_where)

    return PeriodCountResponse(
        today=result[0], this_week=result[1], this_month=result[2], this_year=result[3]
    )


async def _get_monthly_yearly_counts(
    db: AsyncSession, timestamp_column: ColumnElement[datetime | None]
) -> MonthlyYearlyCountResponse:
    """주어진 시각 컬럼 기준으로 이번달/올해 카운트를 집계합니다."""
    now = datetime.now(UTC)
    _, _, month_start, year_start = _period_boundaries(now)

    result = await _count_by_boundaries(db, timestamp_column, (month_start, year_start), now)

    return MonthlyYearlyCountResponse(this_month=result[0], this_year=result[1])


async def get_user_stats(db: AsyncSession) -> UserStatsResponse:
    """대시보드 - 유저 통계."""
    total_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
    ).scalar_one()

    now = datetime.now(UTC)
    active_users_30d = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.last_login_at.between(now - timedelta(days=30), now),
                User.deleted_at.is_(None),
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
    # 완주 시점에 스냅샷 저장된 distance_km을 합산 — Course.distance를 그때그때 합산하면
    # 나중에 코스 거리가 수정될 때 과거 완주 기록의 누적 거리까지 소급으로 바뀌어버림
    total_distance_km, total_completions = (
        await db.execute(
            select(
                func.coalesce(func.sum(Record.distance_km), 0),
                func.count(Record.record_id),
            )
            .select_from(Record)
            .where(Record.is_completed.is_(True))
        )
    ).one()

    # is_completed를 CASE 안이 아니라 WHERE로 먼저 걸러야 ix_records_is_completed를 탐
    completions = await _get_period_counts(
        db, Record.ended_at, extra_where=Record.is_completed.is_(True)
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
    완주 횟수·리뷰 개수까지 전부 같으면 course_id로 최종 고정한다.
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
            Course.course_type,
            func.count(Record.record_id).label("completion_count"),
        )
        .join(Record, Record.course_id == Course.course_id)
        .where(Record.is_completed.is_(True))
    )
    if course_type is not None:
        query = query.where(Course.course_type == course_type)
    query = (
        query.group_by(Course.course_id, Course.course_name, Course.course_type)
        .order_by(
            func.count(Record.record_id).desc(),
            review_count_subquery.desc(),
            Course.course_id.asc(),
        )
        .limit(limit)
    )

    rows = (await db.execute(query)).all()
    return [
        CoursePopularityItem(
            course_id=row.course_id,
            course_name=row.course_name,
            course_type=row.course_type,
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
