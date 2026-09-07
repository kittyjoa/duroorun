"""커스텀 코스 관련
ㅡ 코스명 공백 검증 / 강원도 좌표 경계 / 소유자 권한 / 생성 응답 직렬화 테스트."""

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import delete

from app.config import settings
from app.domain.course.models import Course, CourseImage, CourseType, CourseWaypoint
from app.domain.course.schemas import CourseCreateRequest, CourseUpdateRequest, CourseWaypointCreate
from app.domain.course.service import (
    create_course,
    delete_course,
    delete_course_image,
    get_custom_courses,
    update_course,
    upload_course_image,
)
from app.domain.user.models import User

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


async def test_upload_course_image_rejects_invalid_magic_bytes(db_session, custom_course_owner):
    """파일 시그니처가 이미지 형식이 아니면 400이고, R2 업로드는 아예 시도 X."""
    course, owner = custom_course_owner
    file = UploadFile(file=io.BytesIO(b"not a real image"), filename="fake.png")

    with patch(
        "app.domain.course.service.upload_file", new_callable=AsyncMock
    ) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await upload_course_image(
                session=db_session, user_id=owner.user_id, course_id=course.course_id, file=file
            )
        assert exc_info.value.status_code == 400
    mock_upload.assert_not_called()


async def test_upload_course_image_rejects_oversized_file(db_session, custom_course_owner):
    """설정된 최대 용량을 넘는 파일은 400이고, R2 업로드는 아예 시도 X."""
    course, owner = custom_course_owner
    oversized = _PNG_SIGNATURE + b"0" * (settings.COURSE_IMAGE_MAX_SIZE_MB * 1024 * 1024)
    file = UploadFile(file=io.BytesIO(oversized), filename="big.png")

    with patch(
        "app.domain.course.service.upload_file", new_callable=AsyncMock
    ) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await upload_course_image(
                session=db_session, user_id=owner.user_id, course_id=course.course_id, file=file
            )
        assert exc_info.value.status_code == 400
    mock_upload.assert_not_called()


async def test_upload_course_image_rejects_when_already_at_max_count(
    db_session, custom_course_owner
):
    """업로드 전 개수 체크에서 이미 최대치면 400이고, R2 업로드는 시도 X."""
    course, owner = custom_course_owner
    for _ in range(settings.COURSE_IMAGE_MAX_COUNT):
        db_session.add(
            CourseImage(course_id=course.course_id, image_url=f"https://r2.example.com/{uuid.uuid4()}.png")
        )
    await db_session.commit()

    file = UploadFile(file=io.BytesIO(_PNG_SIGNATURE), filename="c.png")
    try:
        with patch(
            "app.domain.course.service.upload_file", new_callable=AsyncMock
        ) as mock_upload:
            with pytest.raises(HTTPException) as exc_info:
                await upload_course_image(
                    session=db_session,
                    user_id=owner.user_id,
                    course_id=course.course_id,
                    file=file,
                )
            assert exc_info.value.status_code == 400
        mock_upload.assert_not_called()
    finally:
        await db_session.execute(
            delete(CourseImage).where(CourseImage.course_id == course.course_id)
        )
        await db_session.commit()


async def test_upload_course_image_compensates_r2_when_recheck_finds_max_count(
    db_session, custom_course_owner
):
    """업로드 전 개수 체크는 통과했지만, 락을 잡은 뒤 재확인에서 동시 업로드로 꽉 찼다면
    이미 R2에 올라간 파일을 지우고 400을 반환 (동시 업로드 방어)."""
    course, owner = custom_course_owner
    fake_url = "https://r2.example.com/course-images/race.png"
    file = UploadFile(file=io.BytesIO(_PNG_SIGNATURE), filename="race.png")

    counts = iter([0, settings.COURSE_IMAGE_MAX_COUNT])

    async def fake_count(*args, **kwargs):
        return next(counts)

    with (
        patch(
            "app.domain.course.service.upload_file",
            new_callable=AsyncMock,
            return_value=fake_url,
        ),
        patch("app.domain.course.service.delete_file", new_callable=AsyncMock) as mock_delete,
        patch("app.domain.course.service._count_course_images", side_effect=fake_count),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload_course_image(
                session=db_session, user_id=owner.user_id, course_id=course.course_id, file=file
            )
        assert exc_info.value.status_code == 400

    mock_delete.assert_called_once_with(fake_url)
    # 뒷정리 실행하기 전에 course.course_id 읽을때 에러 안 생기도록 refresh()로 미리 다시 읽음
    await db_session.refresh(course)
    await db_session.refresh(owner)


async def test_upload_course_image_compensates_r2_when_db_commit_fails(
    db_session, custom_course_owner
):
    """R2 업로드 성공했지만 DB commit 실패하면, 방금 올린 R2 파일을 보상 삭제."""
    course, owner = custom_course_owner
    fake_url = "https://r2.example.com/course-images/commit-fail.png"
    file = UploadFile(file=io.BytesIO(_PNG_SIGNATURE), filename="commit-fail.png")

    with (
        patch(
            "app.domain.course.service.upload_file",
            new_callable=AsyncMock,
            return_value=fake_url,
        ),
        patch("app.domain.course.service.delete_file", new_callable=AsyncMock) as mock_delete,
        patch.object(
            db_session, "commit", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ),
    ):
        with pytest.raises(RuntimeError):
            await upload_course_image(
                session=db_session, user_id=owner.user_id, course_id=course.course_id, file=file
            )

    mock_delete.assert_called_once_with(fake_url)
    # 뒷정리 실행하기 전에 속성 접근 에러 안 생기도록 refresh()로 미리 다시 읽음
    await db_session.refresh(course)
    await db_session.refresh(owner)


async def test_upload_course_image_compensates_r2_when_course_deleted_mid_upload(
    db_session, custom_course_owner
):
    """R2 업로드가 진행되는 동안 같은 코스가 삭제(is_active=False)되면,
    락 재확인에서 404 나더라도 이미 올라간 R2 파일 보상 삭제."""
    course, owner = custom_course_owner
    fake_url = "https://r2.example.com/course-images/deleted-mid-upload.png"
    file = UploadFile(file=io.BytesIO(_PNG_SIGNATURE), filename="deleted-mid-upload.png")

    async def fake_upload_file(*args, **kwargs):
        # R2 업로드가 진행되는 사이 다른 요청이 같은 코스를 삭제했다고 가정 (경쟁 상태)
        course.is_active = False
        db_session.add(course)
        await db_session.commit()
        return fake_url

    with (
        patch(
            "app.domain.course.service.upload_file",
            new_callable=AsyncMock,
            side_effect=fake_upload_file,
        ),
        patch("app.domain.course.service.delete_file", new_callable=AsyncMock) as mock_delete,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload_course_image(
                session=db_session, user_id=owner.user_id, course_id=course.course_id, file=file
            )
        assert exc_info.value.status_code == 404

    mock_delete.assert_called_once_with(fake_url)
    # 뒷정리 실행하기 전에 속성 접근 에러 안 생기도록 refresh()로 미리 다시 읽음
    await db_session.refresh(course)
    await db_session.refresh(owner)


async def test_delete_course_image_by_non_owner_raises_403(db_session, custom_course_owner):
    """작성자가 아닌 유저가 이미지 삭제를 시도하면 403 반환하고 이미지는 그대로 유지."""
    course, owner = custom_course_owner
    other_user = User(nickname=f"pytest-other-{uuid.uuid4().hex[:12]}")
    db_session.add(other_user)
    image = CourseImage(course_id=course.course_id, image_url="https://r2.example.com/x.png")
    db_session.add(image)
    await db_session.commit()
    await db_session.refresh(image)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await delete_course_image(
                session=db_session,
                user_id=other_user.user_id,
                course_id=course.course_id,
                image_id=image.image_id,
            )
        assert exc_info.value.status_code == 403
    finally:
        await db_session.execute(
            delete(CourseImage).where(CourseImage.course_id == course.course_id)
        )
        await db_session.execute(delete(User).where(User.user_id == other_user.user_id))
        await db_session.commit()


async def test_get_custom_courses_rejects_distance_min_greater_than_max(db_session):
    """distance_min이 distance_max보다 크면 422."""
    with pytest.raises(HTTPException) as exc_info:
        await get_custom_courses(
            session=db_session, page=1, size=10, distance_min=10.0, distance_max=5.0
        )
    assert exc_info.value.status_code == 422


async def test_get_custom_courses_filters_by_distance_range(db_session, custom_course_owner):
    """distance_min/max 범위 안에 든 코스만 목록에 포함 (fixture 코스의 distance=5.0)."""
    course, owner = custom_course_owner

    included = await get_custom_courses(
        session=db_session, page=1, size=50, distance_min=4.0, distance_max=6.0
    )
    assert any(item.course_id == course.course_id for item in included.items)

    excluded = await get_custom_courses(
        session=db_session, page=1, size=50, distance_min=10.0, distance_max=20.0
    )
    assert all(item.course_id != course.course_id for item in excluded.items)
