"""러닝 기록 - 비즈니스 로직."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.record.models import Record
from app.domain.record.schemas import RecordEndRequest, RecordResponse, RecordStartRequest


async def start_record(
        session: AsyncSession,
        user_id: int,
        body: RecordStartRequest,
) -> RecordResponse:
    """러닝시작 - 기록생성"""
    record = Record(
        user_id=user_id,
        course_id=body.course_id,
        started_at=datetime.now(UTC),
        user_start_lat=body.user_start_lat,
        user_start_lng=body.user_start_lng,
    )
    session.add(record) # DB에 추가대기
    await session.commit() # 실제 DB에 저장
    await session.refresh(record) # DB 자동 생성값 갱신(러닝기록값 생성)
    return RecordResponse.model_validate(record) # 응답형식으로 변환

async def end_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
        body: RecordEndRequest,
) -> RecordResponse:
    """러닝종료 - 기록 업데이트 및 완주인증"""
    pass


async def pause_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝 일시정지"""
    pass


async def resume_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝 재시작"""
    pass


async def delete_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> None:
    """러닝기록 삭제"""
    pass


async def get_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝기록 단건 조회(기록 1개 상세)"""
    pass


async def get_records(
        session: AsyncSession,
        user_id: int,
        page: int,
        size: int,
) -> list[RecordResponse]:
    """내 러닝기록 조회(내 기록 전체리스트)"""
    pass

