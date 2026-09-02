"""커스텀 코스 - 강원도 좌표 경계 검증 / 소유자 권한 테스트."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete

from app.domain.course.models import Course, CourseType
from app.domain.course.schemas import CourseUpdateRequest, CourseWaypointCreate
from app.domain.course.service import delete_course, update_course
from app.domain.user.models import User


# CourseWaypointCreate._validate_gangwon_bounds가 참조하는 두 박스(강원 본토 / 철원군) 경계값
@pytest.mark.parametrize(
    "lat,lng",
    [
        (37.75, 128.9),  # 강원 본토 박스 내부(강릉 인근)
        (36.9, 127.4),  # 강원 본토 박스 최소 경계
        (38.7, 129.5),  # 강원 본토 박스 최대 경계
        (38.2, 127.2),  # 철원군 박스 내부
    ],
)
def test_waypoint_accepts_gangwon_coords(lat, lng):
    waypoint = CourseWaypointCreate(latitude=lat, longitude=lng)
    assert waypoint.latitude == lat
    assert waypoint.longitude == lng


@pytest.mark.parametrize(
    "lat,lng",
    [
        (37.5, 130.0),  # 강원 본토 박스 바로 동쪽 바깥(동해 바다)
        (36.5, 128.0),  # 강원 본토 박스 바로 남쪽 바깥(경북)
        (37.5, 126.9),  # 강원 본토 박스 바로 서쪽 바깥(경기)
        (37.5, 129.6),  # 강원 본토 박스 최대 경계 바로 바깥
    ],
)
def test_waypoint_rejects_non_gangwon_coords(lat, lng):
    with pytest.raises(ValidationError):
        CourseWaypointCreate(latitude=lat, longitude=lng)


@pytest.fixture
async def custom_course_owner(db_session):
    """CUSTOM 코스 하나 + 작성자 유저를 만들고, 종료 후 정리한다."""
    owner = User(nickname=f"pytest-owner-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()

    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        created_by=owner.user_id,
        distance=5.0,
        difficulty="NORMAL",
        estimated_time=60,
        start_lat=37.75,
        start_lng=128.9,
        end_lat=37.76,
        end_lng=128.91,
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    yield course, owner

    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.execute(delete(User).where(User.user_id == owner.user_id))
    await db_session.commit()


async def test_update_course_by_non_owner_raises_403(db_session, custom_course_owner):
    course, owner = custom_course_owner
    other_user = User(nickname=f"pytest-other-{uuid.uuid4().hex[:12]}")
    db_session.add(other_user)
    await db_session.commit()

    try:
        with pytest.raises(HTTPException) as exc_info:
            await update_course(
                session=db_session,
                user_id=other_user.user_id,
                course_id=course.course_id,
                body=CourseUpdateRequest(course_name="다른 사람이 바꾼 이름"),
            )
        assert exc_info.value.status_code == 403
    finally:
        await db_session.execute(delete(User).where(User.user_id == other_user.user_id))
        await db_session.commit()


async def test_update_course_by_owner_succeeds(db_session, custom_course_owner):
    course, owner = custom_course_owner

    result = await update_course(
        session=db_session,
        user_id=owner.user_id,
        course_id=course.course_id,
        body=CourseUpdateRequest(course_name="본인이 바꾼 이름"),
    )

    assert result.course_name == "본인이 바꾼 이름"


async def test_delete_course_by_non_owner_raises_403(db_session, custom_course_owner):
    course, owner = custom_course_owner
    other_user = User(nickname=f"pytest-other-{uuid.uuid4().hex[:12]}")
    db_session.add(other_user)
    await db_session.commit()

    try:
        with pytest.raises(HTTPException) as exc_info:
            await delete_course(
                session=db_session, user_id=other_user.user_id, course_id=course.course_id
            )
        assert exc_info.value.status_code == 403
    finally:
        await db_session.execute(delete(User).where(User.user_id == other_user.user_id))
        await db_session.commit()
