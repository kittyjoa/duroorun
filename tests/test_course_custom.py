"""커스텀 코스 관련
ㅡ 코스명 공백 검증 / 강원도 좌표 경계 / 소유자 권한 / 생성 응답 직렬화 테스트."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete

from app.domain.course.models import Course, CourseType, CourseWaypoint
from app.domain.course.schemas import CourseCreateRequest, CourseUpdateRequest, CourseWaypointCreate
from app.domain.course.service import create_course, delete_course, update_course
from app.domain.user.models import User


def _valid_waypoints():
    return [
        {"latitude": 37.75, "longitude": 128.9},
        {"latitude": 37.76, "longitude": 128.91},
    ]


def test_course_create_rejects_blank_course_name():
    """공백만 있는 코스명("   ")은 생성 요청 검증에서 거부."""
    with pytest.raises(ValidationError):
        CourseCreateRequest(
            course_name="   ",
            distance=1.0,
            difficulty="NORMAL",
            estimated_time=10,
            waypoints=_valid_waypoints(),
        )


def test_course_create_strips_course_name_whitespace():
    """코스명 앞뒤 공백은 저장 전에 잘려나감."""
    request = CourseCreateRequest(
        course_name="  강릉 바다길  ",
        distance=1.0,
        difficulty="NORMAL",
        estimated_time=10,
        waypoints=_valid_waypoints(),
    )
    assert request.course_name == "강릉 바다길"


# _validate_gangwon_bounds가 참조하는 실제 강원도 경계(폴리곤) 안쪽 좌표
@pytest.mark.parametrize(
    "lat,lng",
    [
        (37.7519, 128.8761),  # 강릉시청
        (38.2070, 128.5918),  # 속초해변
        (37.3422, 127.9202),  # 원주시청
        (38.1462, 127.3097),  # 철원 - 실제 경계엔 자연히 포함됨
    ],
)
def test_waypoint_accepts_gangwon_coords(lat, lng):
    """강원도 실제 경계(폴리곤) 안쪽 좌표는 경유지로 허용."""
    waypoint = CourseWaypointCreate(latitude=lat, longitude=lng)
    assert waypoint.latitude == lat
    assert waypoint.longitude == lng


@pytest.mark.parametrize(
    "lat,lng",
    [
        (37.5, 127.5),  # 코드리뷰 반례 - 예전 사각형 박스는 통과시켰지만 실제 강원도는 아님
        (37.5, 129.3),  # 동해 바다 한가운데 - 예전 박스 안이지만 육지가 아님
        (37.7, 127.45),  # 경기 가평 인근 - 예전 박스 안이지만 강원도 아님
        (37.0, 129.2),  # 경북 울진 인근 - 예전 박스 안이지만 강원도 아님
    ],
)
def test_waypoint_rejects_non_gangwon_coords(lat, lng):
    """예전 사각형 박스 안에는 들었지만 실제 강원도 경계 밖인 좌표는 경유지로 거부."""
    with pytest.raises(ValidationError):
        CourseWaypointCreate(latitude=lat, longitude=lng)


@pytest.fixture
async def custom_course_owner(db_session):
    """CUSTOM 코스 하나 + 작성자 유저를 만들고, 종료 후 정리."""
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
    """작성자가 아닌 유저가 수정을 시도하면 403을 반환하고 코스는 그대로 유지."""
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
    """작성자 본인이 수정을 요청하면 정상적으로 반영."""
    course, owner = custom_course_owner

    result = await update_course(
        session=db_session,
        user_id=owner.user_id,
        course_id=course.course_id,
        body=CourseUpdateRequest(course_name="본인이 바꾼 이름"),
    )

    assert result.course_name == "본인이 바꾼 이름"


async def test_create_course_serializes_creator_nickname(db_session):
    """생성 직후 응답 직렬화까지 확인 - course.creator가 eager load 안 돼있으면
    creator_nickname 대입 시 lazy load 에러가 남."""
    owner = User(nickname=f"pytest-creator-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.commit()

    result = None
    try:
        result = await create_course(
            session=db_session,
            user_id=owner.user_id,
            body=CourseCreateRequest(
                course_name="pytest 생성 테스트 코스",
                distance=1.0,
                difficulty="NORMAL",
                estimated_time=10,
                waypoints=_valid_waypoints(),
            ),
        )
        assert result.creator_nickname == owner.nickname
        assert result.created_by == owner.user_id
    finally:
        if result is not None:
            await db_session.execute(
                delete(CourseWaypoint).where(CourseWaypoint.course_id == result.course_id)
            )
            await db_session.execute(delete(Course).where(Course.course_id == result.course_id))
        await db_session.execute(delete(User).where(User.user_id == owner.user_id))
        await db_session.commit()


async def test_update_course_replaces_waypoints_and_start_end_coords(
    db_session, custom_course_owner
):
    """waypoints를 새로 보내면 경유지가 통째로 교체되고 start/end 좌표도 갱신."""
    course, owner = custom_course_owner
    new_waypoints = [
        {"latitude": 38.2070, "longitude": 128.5918},  # 속초해변
        {"latitude": 37.3422, "longitude": 127.9202},  # 원주시청
        {"latitude": 37.7519, "longitude": 128.8761},  # 강릉시청
    ]

    try:
        result = await update_course(
            session=db_session,
            user_id=owner.user_id,
            course_id=course.course_id,
            body=CourseUpdateRequest(waypoints=new_waypoints),
        )

        assert [(w.latitude, w.longitude) for w in result.waypoints] == [
            (38.2070, 128.5918),
            (37.3422, 127.9202),
            (37.7519, 128.8761),
        ]
        assert (result.start_lat, result.start_lng) == (38.2070, 128.5918)
        assert (result.end_lat, result.end_lng) == (37.7519, 128.8761)
    finally:
        # 도커 테스트 돌리다 뒷정리 단계에서 FK 제약 위반이 나서 여기서 먼저 정리
        # ㅡ finally로 course_waypoints를 먼저 지우도록 고침
        await db_session.execute(
            delete(CourseWaypoint).where(CourseWaypoint.course_id == course.course_id)
        )
        await db_session.commit()


def test_update_course_rejects_waypoint_outside_gangwon():
    """수정 요청 waypoints에 강원도 밖 좌표가 섞이면 요청 검증 단계에서 거부."""
    with pytest.raises(ValidationError):
        CourseUpdateRequest(
            waypoints=[
                {"latitude": 37.75, "longitude": 128.9},  # 강원 (정상)
                {"latitude": 37.5, "longitude": 127.5},  # 강원 밖
            ]
        )


async def test_delete_course_by_non_owner_raises_403(db_session, custom_course_owner):
    """작성자가 아닌 유저가 삭제를 시도하면 403을 반환."""
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
