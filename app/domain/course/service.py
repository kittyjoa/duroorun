"""코스 (DRNB + 커스텀) - 비즈니스 로직."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.course.models import Course, CourseType, CourseWaypoint
from app.domain.course.schemas import (
    CourseCreateRequest,
    CourseUpdateRequest,
    CourseWaypointCreate,
    CustomCourseDetailResponse,
    CustomCourseListResponse,
    CustomCourseSummary,
)

# TODO DRNB 목록/조회 함수 작성 시: 쿼리에 WHERE course_type == CourseType.DRNB 필터 반드시 포함할 것.


def _build_waypoints(waypoints: list[CourseWaypointCreate]) -> list[CourseWaypoint]:
    """요청 좌표 리스트를 sequence가 매겨진 CourseWaypoint 목록으로 변환합니다."""
    return [
        CourseWaypoint(sequence=i, latitude=w.latitude, longitude=w.longitude)
        for i, w in enumerate(waypoints)
    ]


async def _get_custom_course(session: AsyncSession, course_id: int) -> Course:
    """CUSTOM 코스를 경유지/이미지까지 eager load해서 조회합니다. 없으면 404."""
    result = await session.execute(
        select(Course)
        .where(Course.course_id == course_id, Course.course_type == CourseType.CUSTOM)
        .options(selectinload(Course.waypoints), selectinload(Course.images))
    )
    course = result.scalar_one_or_none()
    if course is None or not course.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다.")
    return course


async def create_course(
    session: AsyncSession, user_id: int, body: CourseCreateRequest
) -> CustomCourseDetailResponse:
    """커스텀 코스를 등록합니다. 시작/종료 좌표는 첫/마지막 경유지로 자동 설정."""
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=body.course_name,
        created_by=user_id,
        distance=body.distance,
        difficulty=body.difficulty,
        estimated_time=body.estimated_time,
        course_description=body.course_description,
        start_lat=body.waypoints[0].latitude,
        start_lng=body.waypoints[0].longitude,
        end_lat=body.waypoints[-1].latitude,
        end_lng=body.waypoints[-1].longitude,
    )
    course.waypoints = _build_waypoints(body.waypoints)

    session.add(course)
    await session.commit()
    course = await _get_custom_course(session, course.course_id)
    return CustomCourseDetailResponse.model_validate(course)


async def get_custom_course(session: AsyncSession, course_id: int) -> CustomCourseDetailResponse:
    """커스텀 코스 상세를 조회합니다 (경유지/이미지 포함)."""
    course = await _get_custom_course(session, course_id)
    return CustomCourseDetailResponse.model_validate(course)


async def get_custom_courses(
    session: AsyncSession,
    page: int,
    size: int,
    created_by: int | None = None,
) -> CustomCourseListResponse:
    """커스텀 코스 목록을 조회합니다. 기본은 전체 공개, created_by 지정 시 해당 작성자 코스만."""
    base_query = select(Course).where(
        Course.course_type == CourseType.CUSTOM, Course.is_active.is_(True)
    )
    if created_by is not None:
        base_query = base_query.where(Course.created_by == created_by)

    total = (
        await session.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar_one()

    list_query = (
        base_query.order_by(Course.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    courses = (await session.execute(list_query)).scalars().all()

    return CustomCourseListResponse(
        items=[CustomCourseSummary.model_validate(c) for c in courses],
        total=total,
        page=page,
        size=size,
    )


async def update_course(
    session: AsyncSession,
    user_id: int,
    course_id: int,
    body: CourseUpdateRequest,
) -> CustomCourseDetailResponse:
    """커스텀 코스를 수정합니다 (작성자 본인 전용, 부분 수정)."""
    course = await _get_custom_course(session, course_id)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 코스만 수정할 수 있습니다."
        )

    # 요청 JSON에 실제 포함된 필드만 딕셔너리로 뽑음. 생략 필드는 안 건드리고 명시적 null만 반영.
    update_data = body.model_dump(exclude_unset=True, exclude={"waypoints"})
    for field, value in update_data.items():
        setattr(course, field, value)

    if body.waypoints is not None:
        # 기존 행 삭제(cascade="all, delete-orphan")와 새 행 삽입이 한 flush에서 같이 나가면
        # sequence 값이 겹칠 때 INSERT가 DELETE보다 먼저 실행되어 uq_waypoint_course_sequence
        # 유니크 제약 위반이 남 (실제로 테스트하다 발견) — 빈 리스트로 먼저 flush해 삭제부터 확정시킴
        course.waypoints = []
        await session.flush()
        course.waypoints = _build_waypoints(body.waypoints)
        course.start_lat = body.waypoints[0].latitude
        course.start_lng = body.waypoints[0].longitude
        course.end_lat = body.waypoints[-1].latitude
        course.end_lng = body.waypoints[-1].longitude

    await session.commit()
    course = await _get_custom_course(session, course_id)
    return CustomCourseDetailResponse.model_validate(course)


async def delete_course(session: AsyncSession, user_id: int, course_id: int) -> None:
    """커스텀 코스를 비활성화합니다 (Soft Delete, 작성자 본인 전용)."""
    course = await _get_custom_course(session, course_id)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 코스만 삭제할 수 있습니다."
        )
    course.is_active = False
    await session.commit()
