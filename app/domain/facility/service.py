"""편의시설 - 비즈니스 로직."""

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.course.models import Course
from app.domain.facility.models import CourseFacility, Facility
from app.domain.facility.schemas import (
    FacilityCreateRequest,
    FacilityListResponse,
    FacilityResponse,
    FacilityUpdateRequest,
)

_KAKAO_PLACE_URL_TEMPLATE = "https://place.map.kakao.com/{}"

# Facility 컬럼이 nullable=False라 부분 수정 시에도 명시적 null을 허용하면 안 되는 필드
_REQUIRED_FIELDS = ("latitude", "longitude", "is_active")


def _build_place_url(kakao_place_id: str | None) -> str | None:
    """kakao_place_id로 카카오맵 장소 상세 URL을 조립합니다.

    카카오 Local API에는 id 기반 상세조회 엔드포인트가 없고, 장소 페이지 URL은
    고정 패턴이라 API 호출 없이 문자열로 바로 조립합니다.
    """
    return _KAKAO_PLACE_URL_TEMPLATE.format(kakao_place_id) if kakao_place_id else None


async def _validate_course_ids(session: AsyncSession, course_ids: list[int]) -> None:
    """연결하려는 course_id가 모두 존재하는지 확인합니다."""
    if not course_ids:
        return
    result = await session.execute(
        select(Course.course_id).where(Course.course_id.in_(course_ids))
    )
    found_ids = set(result.scalars().all())
    missing_ids = set(course_ids) - found_ids
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"존재하지 않는 코스입니다: {sorted(missing_ids)}",
        )


async def create_facility(session: AsyncSession, body: FacilityCreateRequest) -> FacilityResponse:
    """편의시설을 등록합니다."""
    # 프론트에서 같은 코스를 중복 전달해도 복합 PK(course_id, facility_id) 충돌이 나지 않도록 dedupe
    course_ids = list(dict.fromkeys(body.course_ids))
    await _validate_course_ids(session, course_ids)

    facility = Facility(
        facility_type=body.facility_type,
        facility_name=body.facility_name,
        facility_address=body.facility_address,
        latitude=body.latitude,
        longitude=body.longitude,
        kakao_place_id=body.kakao_place_id,
        place_url=_build_place_url(body.kakao_place_id),
    )
    facility.course_facilities = [CourseFacility(course_id=course_id) for course_id in course_ids]

    session.add(facility)
    await session.commit()
    await session.refresh(facility)
    return FacilityResponse.model_validate(facility)


async def get_facility(session: AsyncSession, facility_id: int) -> FacilityResponse:
    """편의시설 상세 정보를 조회합니다."""
    facility = await session.get(Facility, facility_id)
    # 비활성화(soft delete)된 시설은 목록 조회와 동일하게 노출하지 않음
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
    """편의시설 목록을 조회합니다.

    course_id 전달 시 해당 코스에 연결된(course_facility 매핑) 시설만 조회 (코스 상세 지도용).
    비활성화된 시설은 매핑이 남아있어도 노출하지 않음.
    """
    # count/list가 같은 필터를 따로 들고 있으면 나중에 필터가 하나만 수정돼 total과
    # items 개수가 어긋날 수 있어, base_query 하나로 필터를 통일하고 count는 서브쿼리로 계산
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
    """편의시설을 수정합니다."""
    facility = await session.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="편의시설을 찾을 수 없습니다."
        )

    update_data = body.model_dump(exclude_unset=True, exclude={"course_ids"})
    for required_field in _REQUIRED_FIELDS:
        if required_field in update_data and update_data[required_field] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{required_field}는 null로 변경할 수 없습니다.",
            )
    for field, value in update_data.items():
        setattr(facility, field, value)
    if "kakao_place_id" in update_data:
        facility.place_url = _build_place_url(facility.kakao_place_id)

    # course_ids는 exclude_unset이 아니라 None(변경 없음) vs []( 전체 해제)로 직접 분기
    if body.course_ids is not None:
        course_ids = list(dict.fromkeys(body.course_ids))
        await _validate_course_ids(session, course_ids)
        await session.execute(
            delete(CourseFacility).where(CourseFacility.facility_id == facility_id)
        )
        facility.course_facilities = [
            CourseFacility(course_id=course_id) for course_id in course_ids
        ]

    await session.commit()
    await session.refresh(facility)
    return FacilityResponse.model_validate(facility)


async def delete_facility(session: AsyncSession, facility_id: int) -> None:
    """편의시설을 비활성화합니다 (Soft Delete)."""
    facility = await session.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="편의시설을 찾을 수 없습니다."
        )
    facility.is_active = False
    await session.commit()
