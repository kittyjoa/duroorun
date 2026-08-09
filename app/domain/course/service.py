"""코스 (DRNB + 커스텀) - 비즈니스 로직."""

import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.r2 import delete_file, upload_file
from app.config import settings
from app.domain.course.models import Course, CourseImage, CourseType, CourseWaypoint, Difficulty
from app.domain.course.schemas import (
    CourseCreateRequest,
    CourseUpdateRequest,
    CourseWaypointCreate,
    CustomCourseDetailResponse,
    CustomCourseListResponse,
    CustomCourseSummary,
    DrnbCourseDetailResponse,
    DrnbCourseListResponse,
    DrnbCourseSummary,
)

logger = logging.getLogger(__name__)

# Course 컬럼은 nullable=True지만 생성시 필수값이라, 수정 시 null 허용하면 X
_REQUIRED_FIELDS = ("course_name", "distance", "difficulty", "estimated_time")

_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _detect_image_content_type(data: bytes) -> str | None:
    """파일 시그니처(매직바이트)로 실제 이미지 형식을 판별합니다."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _build_waypoints(waypoints: list[CourseWaypointCreate]) -> list[CourseWaypoint]:
    """요청 좌표 리스트를 sequence(순서 번호)가 매겨진 CourseWaypoint 목록으로 변환."""
    return [
        CourseWaypoint(sequence=i, latitude=w.latitude, longitude=w.longitude)
        for i, w in enumerate(waypoints)
    ]


async def get_drnb_courses(
    session: AsyncSession,
    page: int,
    size: int,
    brd_div: str | None = None,
    sigun: str | None = None,
    difficulty: Difficulty | None = None,
    estimated_time_min: int | None = None,
    estimated_time_max: int | None = None,
) -> DrnbCourseListResponse:
    """DRNB 코스 목록을 조회합니다. 시드 스크립트로 저장된 DB 정보만 사용 (배치 갱신).

    ㅡ brd_div/sigun/difficulty는 정확히 일치, estimated_time은 min/max 범위로 필터링
    ㅡ 현재 시드 스크립트가 강원 코스만 적재하므로 DB엔 강원 코스만 존재.
    추후 다른 지역까지 시드 대상이 넓어져도 이 필터로 그대로 좁혀볼 수 있음.
    """
    base_query = select(Course).where(
        Course.course_type == CourseType.DRNB,
        Course.is_active.is_(True),
        Course.dmb_id.is_not(None),  # 두루누비 응답엔 dmb_id 항상 존재한다는 약속 지킬수있음
    )
    if brd_div is not None:
        base_query = base_query.where(Course.brd_div == brd_div)
    if sigun is not None:
        base_query = base_query.where(Course.sigun == sigun)
    if difficulty is not None:
        base_query = base_query.where(Course.difficulty == difficulty)
    if estimated_time_min is not None:
        base_query = base_query.where(Course.estimated_time >= estimated_time_min)
    if estimated_time_max is not None:
        base_query = base_query.where(Course.estimated_time <= estimated_time_max)

    total = (
        await session.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar_one()

    list_query = base_query.order_by(Course.course_id).offset((page - 1) * size).limit(size)
    courses = (await session.execute(list_query)).scalars().all()

    return DrnbCourseListResponse(
        items=[DrnbCourseSummary.model_validate(c) for c in courses],
        total=total,
        page=page,
        size=size,
    )


async def get_drnb_course(session: AsyncSession, course_id: int) -> DrnbCourseDetailResponse:
    """DRNB 코스 상세를 조회합니다. 시드 스크립트로 저장된 DB 정보만 사용 (배치 갱신)."""
    result = await session.execute(
        select(Course)
        .where(
            Course.course_id == course_id,
            Course.course_type == CourseType.DRNB,
            Course.dmb_id.is_not(None),
        )
        .options(selectinload(Course.images))
    )
    course = result.scalar_one_or_none()
    if course is None or not course.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )
    return DrnbCourseDetailResponse.model_validate(course)


async def _get_custom_course(
    session: AsyncSession, course_id: int, *, for_update: bool = False
) -> Course:
    """CUSTOM 코스를 경유지/이미지까지 eager load해서 조회합니다. 없으면 404.

    ㅡ for_update=True면 courses 행에 락을 걸어, 동시 수정/삭제 요청 꼬이는거 방지
    """
    query = (
        select(Course)
        .where(Course.course_id == course_id, Course.course_type == CourseType.CUSTOM)
        .options(selectinload(Course.waypoints), selectinload(Course.images))
    )
    if for_update:
    # for_update 스위치로 수정/삭제할때만 True (같은 코스 건드리는 다른 요청 끼어들지 못하게)
        query = query.with_for_update()
        # with_for_update: 이 행을 읽으면서 동시에 잠그고, 내가 끝날때까지 기다리셈
    result = await session.execute(query)
    course = result.scalar_one_or_none()
    if course is None or not course.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )
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
    difficulty: Difficulty | None = None,
    distance_min: float | None = None,
    distance_max: float | None = None,
) -> CustomCourseListResponse:
    """커스텀 코스 목록을 조회합니다. 기본은 전체 공개, created_by 지정 시 해당 작성자 코스만.

    ㅡ difficulty는 정확히 일치, distance는 min/max 범위로 필터링
    """
    base_query = select(Course).where(
        Course.course_type == CourseType.CUSTOM, Course.is_active.is_(True)
    )
    if created_by is not None:
        base_query = base_query.where(Course.created_by == created_by)
    if difficulty is not None:
        base_query = base_query.where(Course.difficulty == difficulty)
    if distance_min is not None:
        base_query = base_query.where(Course.distance >= distance_min)
    if distance_max is not None:
        base_query = base_query.where(Course.distance <= distance_max)

    total = (
        await session.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar_one()

    list_query = (
        base_query.order_by(Course.created_at.desc(), Course.course_id.desc())
        .offset((page - 1) * size)
        .limit(size)
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
    course = await _get_custom_course(session, course_id, for_update=True)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 코스만 수정할 수 있습니다."
        )

    # 요청 JSON에 실제 포함된 필드만 딕셔너리로 뽑음. 생략 필드는 안 건드리고 명시적 null만 반영.
    update_data = body.model_dump(exclude_unset=True, exclude={"waypoints"})
    for required_field in _REQUIRED_FIELDS:
        if required_field in update_data and update_data[required_field] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{required_field}는 null로 변경할 수 없습니다.",
            )
    for field, value in update_data.items():
        setattr(course, field, value)

    # waypoints 필드가 요청에 아예 없으면 기존 경유지 유지, null이면 400
    if "waypoints" in body.model_fields_set:
        if body.waypoints is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="waypoints는 null일 수 없습니다.",
            )
        course.waypoints = []
        # flush 없이 바로 새 waypoints를 대입하면
        # 같은 flush 안에서 INSERT가 DELETE보다 먼저 실행돼
        # 유니크 제약이 일시적으로 충돌할 수 있음
        # ㅡ flush로 기존 행 삭제를 먼저 확정시킨 뒤 채워넣음
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
    course = await _get_custom_course(session, course_id, for_update=True)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 코스만 삭제할 수 있습니다."
        )
    course.is_active = False
    await session.commit()


async def upload_course_image(
    session: AsyncSession, user_id: int, course_id: int, file: UploadFile
) -> CustomCourseDetailResponse:
    """커스텀 코스 이미지 업로드 (작성자 본인 전용).

    ㅡ 같은 코스에 대해 요청이 다수 들어온 경우, 직렬 순서대로 하나씩 처리.
    한 요청이 락 잡고 커밋 될때까지 다른 요청들은 본인 순서 기다림.
    """
    course = await _get_custom_course(session, course_id, for_update=True)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 코스에만 이미지를 업로드할 수 있습니다.",
        )

    count_result = await session.execute(
        select(func.count()).select_from(CourseImage).where(CourseImage.course_id == course_id)
    )
    if count_result.scalar_one() >= settings.COURSE_IMAGE_MAX_COUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"코스 이미지는 최대 {settings.COURSE_IMAGE_MAX_COUNT}개까지 업로드할 수 있습니다.",
        )

    # 파일 크기 확인 (제한 초과 시 즉시 중단, 전체를 다 읽지 않음)
    max_bytes = settings.COURSE_IMAGE_MAX_SIZE_MB * 1024 * 1024
    chunks = []
    total_size = 0
    while chunk := await file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"이미지 크기는 {settings.COURSE_IMAGE_MAX_SIZE_MB}MB 이하여야 합니다.",
            )
        chunks.append(chunk)
    contents = b"".join(chunks)

    # 파일 형식 확인 (Content-Type 헤더는 클라이언트가 조작 가능하므로 실제 파일 시그니처로 검증)
    detected_content_type = _detect_image_content_type(contents)
    if detected_content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="jpg, png, webp, gif 형식만 업로드할 수 있습니다.",
        )

    # R2 업로드
    ext = _IMAGE_EXTENSIONS[detected_content_type]
    try:
        image_url = await upload_file("course-images", contents, ext, detected_content_type)
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="이미지 업로드에 실패했습니다.",
        ) from err

    # DB 저장
    image = CourseImage(course_id=course_id, image_url=image_url)
    session.add(image)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        try:
            await delete_file(image_url)
        # 보상 삭제: db 저장 실패했으니 방금 r2에 올린 파일도 도로 삭제(보상 트랜잭션)
        except (ClientError, BotoCoreError):
            logger.exception("DB commit 실패 후 R2 보상 삭제도 실패: image_url=%s", image_url)
        raise

    course = await _get_custom_course(session, course_id)
    return CustomCourseDetailResponse.model_validate(course)


async def delete_course_image(
    session: AsyncSession, user_id: int, course_id: int, image_id: int
) -> None:
    """커스텀 코스 이미지 삭제 (작성자 본인 전용)."""
    course = await _get_custom_course(session, course_id)
    if course.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 코스 이미지만 삭제할 수 있습니다."
        )

    image = await session.get(CourseImage, image_id)
    if image is None or image.course_id != course_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="이미지를 찾을 수 없습니다."
        )

    # DB 삭제 먼저 확정 → R2 정리
    image_url = image.image_url
    await session.delete(image)
    await session.commit()

    try:
        await delete_file(image_url)
    except (ClientError, BotoCoreError):
        logger.exception("DB 삭제 후 R2 파일 삭제 실패: image_url=%s", image_url)
