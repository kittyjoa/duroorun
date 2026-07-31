"""편의시설 - 비즈니스 로직."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.course.models import Course
from app.domain.facility.models import CourseFacility, Facility
from app.domain.facility.schemas import (
    FacilityCreateRequest,
    FacilityListResponse,
    FacilityResponse,
    FacilityUpdateRequest,
)

_KAKAO_PLACE_URL_TEMPLATE = "https://place.map.kakao.com/{}"

# Facility 컬럼이 nullable=False라 부분 수정 시에도 null 허용 X
_REQUIRED_FIELDS = ("facility_type", "facility_name", "latitude", "longitude", "is_active")


def _build_place_url(kakao_place_id: str | None) -> str | None:
    """kakao_place_id로 카카오맵 장소 상세 URL을 조립.

    ㅡ 카카오 Local API에는 id 기반 상세조회 엔드포인트가 없고,
    장소 페이지 URL은 고정 패턴이라 API 호출 없이 문자열만 조립.
    """
    return _KAKAO_PLACE_URL_TEMPLATE.format(kakao_place_id) if kakao_place_id else None


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


async def create_facility(session: AsyncSession, body: FacilityCreateRequest) -> FacilityResponse:
    """편의시설을 등록."""
    # course_ids 중복 제거 → 존재 검증 → 'Facility 생성 + CourseFacility 매핑' 저장
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
    if "kakao_place_id" in update_data:
        facility.place_url = _build_place_url(facility.kakao_place_id)

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

    await session.commit()
    await session.refresh(facility)
    return FacilityResponse.model_validate(facility)


async def delete_facility(session: AsyncSession, facility_id: int) -> None:
    """편의시설을 비활성화 (Soft Delete: is_active=False)."""
    facility = await session.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="편의시설을 찾을 수 없습니다."
        )
    facility.is_active = False
    await session.commit()
