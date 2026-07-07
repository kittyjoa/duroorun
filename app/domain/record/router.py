"""러닝 기록 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.domain.record import service as record_service
from app.domain.record.schemas import RecordEndRequest, RecordResponse, RecordStartRequest
from app.domain.user.models import User

router = APIRouter(prefix="/records", tags=["records"])


@router.post("/start", response_model=RecordResponse)
async def start_record(
    body: RecordStartRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝시작"""
    return await record_service.start_record(
        session=session, user_id=current_user.user_id, body=body
    )


@router.patch("/{record_id}/end", response_model=RecordResponse)
async def end_record(
    record_id: int,
    body: RecordEndRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝종료"""
    return await record_service.end_record(
        session=session, user_id=current_user.user_id, record_id=record_id, body=body
    )


@router.get("/{record_id}", response_model=RecordResponse)
async def get_record(
    record_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝기록 단건 조회(기록 1개 상세)"""
    return await record_service.get_record(
        session=session, user_id=current_user.user_id, record_id=record_id
    )


@router.get("/", response_model=list[RecordResponse])
async def get_records(
    page: int = 1,
    size: int = 20,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내 러닝기록 조회(내 기록 전체리스트)"""
    return await record_service.get_records(
        session=session, user_id=current_user.user_id, page=page, size=size
    )


@router.patch("/{record_id}/pause", response_model=RecordResponse)
async def pause_record(
    record_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝 일시정지"""
    return await record_service.pause_record(
        session=session, user_id=current_user.user_id, record_id=record_id
    )


@router.patch("/{record_id}/resume", response_model=RecordResponse)
async def resume_record(
    record_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝 재시작"""
    return await record_service.resume_record(
        session=session, user_id=current_user.user_id, record_id=record_id
    )


@router.delete("/{record_id}", status_code=204)
async def delete_record(
    record_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """러닝기록 삭제"""
    await record_service.delete_record(
        session=session, user_id=current_user.user_id, record_id=record_id
    )
