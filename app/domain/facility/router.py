"""편의시설 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_admin
from app.database import get_db
from app.domain.facility import service as facility_service
from app.domain.facility.schemas import (
    FacilityCreateRequest,
    FacilityListResponse,
    FacilityResponse,
    FacilityUpdateRequest,
)
from app.domain.user.models import User

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.post("", response_model=FacilityResponse, status_code=status.HTTP_201_CREATED)
async def create_facility(
    body: FacilityCreateRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """편의시설 등록 (관리자 전용)"""
    return await facility_service.create_facility(session=session, body=body)


@router.get("", response_model=FacilityListResponse)
async def get_facilities(
    page: int = 1,
    size: int = 20,
    course_id: int | None = None,
    session: AsyncSession = Depends(get_db),
):
    """편의시설 목록 조회 (course_id 전달 시 해당 코스 주변 시설만 조회)"""
    return await facility_service.get_facilities(
        session=session, page=page, size=size, course_id=course_id
    )


@router.get("/{facility_id}", response_model=FacilityResponse)
async def get_facility(facility_id: int, session: AsyncSession = Depends(get_db)):
    """편의시설 상세 조회"""
    return await facility_service.get_facility(session=session, facility_id=facility_id)


@router.patch("/{facility_id}", response_model=FacilityResponse)
async def update_facility(
    facility_id: int,
    body: FacilityUpdateRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """편의시설 수정 (관리자 전용)"""
    return await facility_service.update_facility(
        session=session, facility_id=facility_id, body=body
    )


@router.delete("/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_facility(
    facility_id: int,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """편의시설 삭제 (관리자 전용, Soft Delete)"""
    await facility_service.delete_facility(session=session, facility_id=facility_id)
