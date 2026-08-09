"""편의시설 - 비즈니스 로직."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.course.models import Course
from app.domain.facility.models import CourseFacility, Facility, FacilityType
from app.domain.facility.schemas import (
    FacilityCreateRequest,
    FacilityListResponse,
    FacilityResponse,
    FacilityUpdateRequest,
)

# Facility 컬럼이 nullable=False라 부분 수정 시에도 null 허용 X
_REQUIRED_FIELDS = ("facility_type", "facility_name", "latitude", "longitude", "is_active")

_UNIQUE_VIOLATION_SQLSTATE = "23505"
_DUPLICATE_FACILITY_CONSTRAINT = "uq_facility_kakao_place_type"


def _is_duplicate_facility_conflict(err: IntegrityError) -> bool:
    """IntegrityError가 (kakao_place_id, facility_type) unique 위반인지 확인.

    ㅡ DB 관련 위반까지 "이미 등록된 장소" 409로 뭉개지 않도록,
      sqlstate와 constraint 이름 확인해서 이 케이스만 정확히 골라냄.
    """
    orig = err.orig
    if getattr(orig, "sqlstate", None) != _UNIQUE_VIOLATION_SQLSTATE:
        return False
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _DUPLICATE_FACILITY_CONSTRAINT


async def _validate_course_ids(session: AsyncSession, course_ids: list[int]) -> None:
    """연결하려는 course_id가 모두 존재하는지 확인."""
    if not course_ids:
        return
    result = await session.execute(
        select(Course.course_id).where(
            Course.course_id.in_(course_ids), Course.is_active.is_(True)
        )
    )
    found_ids = set(result.scalars().all())
    missing_ids = set(course_ids) - found_ids
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"존재하지 않는 코스입니다: {sorted(missing_ids)}",
        )


async def _get_facility_for_update(session: AsyncSession, facility_id: int) -> Facility:
    """편의시설을 course_facilities까지 로드하고 행 잠금을 건 상태로 조회. 없으면 404.

    ㅡ selectinload: course_facilities 연결테이블 처음부터 같이 로드해두기
    with_for_update: 동시 수정하는 상황에서, A가 끝내고 커밋할때까지 행 잠금.
    """
    query = (
        select(Facility)
        .where(Facility.facility_id == facility_id)
        .options(selectinload(Facility.course_facilities))
        .with_for_update()
    )
    result = await session.execute(query)
    facility = result.scalar_one_or_none()
    if facility is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="편의시설을 찾을 수 없습니다."
        )
    return facility


async def _find_inactive_facility(
    session: AsyncSession, kakao_place_id: str | None, facility_type: FacilityType
) -> Facility | None:
    """같은 (kakao_place_id, facility_type) 조합의 비활성 시설을 찾음 (재활성화용).

    ㅡ kakao_place_id가 None이면 unique 제약 대상 밖이라 검색하지 않음.
    ㅡ with_for_update: 동시에 같은 조합을 재등록하는 요청이 겹쳐도 하나씩 순서대로
      처리되게 락을 걸어, 두 요청이 같은 row를 동시에 재활성화하다 매핑이 유실되는 것 방지.
    """
    if kakao_place_id is None:
        return None
    result = await session.execute(
        select(Facility)
        .where(
            Facility.kakao_place_id == kakao_place_id,
            Facility.facility_type == facility_type,
            Facility.is_active.is_(False),
        )
        .options(selectinload(Facility.course_facilities))
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def create_facility(session: AsyncSession, body: FacilityCreateRequest) -> FacilityResponse:
    """편의시설을 등록.

    ㅡ 같은 (kakao_place_id, facility_type) 조합의 비활성 시설이 있으면 새로 만들지 않고
      그 시설을 재활성화 + 최신 정보로 갱신 (비활성 row가 재등록마다 계속 쌓이는 것 방지).
    """
    # course_ids 중복 제거 → 존재 검증 → 'Facility 생성 + CourseFacility 매핑' 저장
    course_ids = list(dict.fromkeys(body.course_ids))
    await _validate_course_ids(session, course_ids)

    facility = await _find_inactive_facility(session, body.kakao_place_id, body.facility_type)
    if facility is not None:
        facility.is_active = True
        facility.facility_name = body.facility_name
        facility.facility_address = body.facility_address
        facility.latitude = body.latitude
        facility.longitude = body.longitude
        facility.course_facilities.clear()
        await session.flush()
    else:
        facility = Facility(
            facility_type=body.facility_type,
            facility_name=body.facility_name,
            facility_address=body.facility_address,
            latitude=body.latitude,
            longitude=body.longitude,
            kakao_place_id=body.kakao_place_id,
        )
        session.add(facility)

    facility.course_facilities = [CourseFacility(course_id=course_id) for course_id in course_ids]

    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        if not _is_duplicate_facility_conflict(err):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 등록된 장소+시설타입 조합입니다.",
        ) from err
    await session.refresh(facility)
    return FacilityResponse.model_validate(facility)


async def get_facility(session: AsyncSession, facility_id: int) -> FacilityResponse:
    """편의시설 상세 정보를 조회(단건 조회)."""
    facility = await session.get(Facility, facility_id)
    # 비활성화(soft delete)된 시설은 목록 조회와 동일하게 노출 X
    if facility is None or not facility.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="편의시설을 찾을 수 없습니다."
        )
    return FacilityResponse.model_validate(facility)


async def get_facilities(
    session: AsyncSession,
    page: int,
    size: int,
    course_id: int | None = None,
) -> FacilityListResponse:
    """편의시설 목록을 조회.

    ㅡ course_id 전달 시 해당 코스에 연결된 시설만 조회 (코스 상세 지도용).
    비활성화된 시설은 매핑이 남아있어도 노출 X
    """
    # base_query 하나로 필터를 통일하고 count는 서브쿼리로 계산
    base_query = select(Facility).where(Facility.is_active.is_(True))
    if course_id is not None:
        base_query = base_query.join(CourseFacility).where(CourseFacility.course_id == course_id)

    total = (
        await session.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar_one()

    list_query = base_query.order_by(Facility.facility_id).offset((page - 1) * size).limit(size)
    facilities = (await session.execute(list_query)).scalars().all()

    return FacilityListResponse(
        items=[FacilityResponse.model_validate(f) for f in facilities],
        total=total,
        page=page,
        size=size,
    )


async def update_facility(
    session: AsyncSession,
    facility_id: int,
    body: FacilityUpdateRequest,
) -> FacilityResponse:
    """편의시설을 수정."""
    facility = await _get_facility_for_update(session, facility_id)

    # exclude_unset=True: 프론트가 그 필드를 요청에 넣었는지 안 넣었는지만 체크
    update_data = body.model_dump(exclude_unset=True, exclude={"course_ids"})
    for required_field in _REQUIRED_FIELDS:
        if required_field in update_data and update_data[required_field] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{required_field}는 null로 변경할 수 없습니다.",
            )
    for field, value in update_data.items():
        setattr(facility, field, value)

    # course_ids는 exclude_unset로 처리하면 안되어서 직접 처리
    # 프론트가 course_ids 필드 아예 안 넣으면: None ㅡ 코스연결 건들지마라
    # 프론트가 "course_ids": [] 보내면 body도 [] ㅡ 이 시설 코스연결 전부 해제
    # 프론트가 "course_ids": [1, 2] 보내면 ㅡ 코스 1,2로 연결 다시 세팅
    if body.course_ids is not None:
        course_ids = list(dict.fromkeys(body.course_ids))
        await _validate_course_ids(session, course_ids)
        facility.course_facilities.clear()
        await session.flush()
        facility.course_facilities.extend(
            CourseFacility(course_id=course_id) for course_id in course_ids
        )

    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        if not _is_duplicate_facility_conflict(err):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 등록된 장소+시설타입 조합입니다.",
        ) from err
    await session.refresh(facility)
    return FacilityResponse.model_validate(facility)


async def delete_facility(session: AsyncSession, facility_id: int) -> None:
    """편의시설을 비활성화 (Soft Delete: is_active=False)."""
    facility = await _get_facility_for_update(session, facility_id)
    facility.is_active = False
    await session.commit()
