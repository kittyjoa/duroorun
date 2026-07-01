"""러닝 기록 - 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.record.schemas import RecordEndRequest, RecordResponse, RecordStartRequest


async def start_record(
        session: AsyncSession,
        user_id: int,
        body: RecordStartRequest,
) -> RecordResponse:
    """러닝시작 - 기록생성"""
    pass


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

