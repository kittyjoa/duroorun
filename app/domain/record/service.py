"""러닝 기록 - 비즈니스 로직."""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.record.models import Record
from app.domain.record.schemas import (
    RecordEndRequest,
    RecordListResponse,
    RecordResponse,
    RecordStartRequest,
)

# from app.domain.course.models import Course # TODO: course 완성 후 주석해제 예정


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
    # 기록조회
    result = await session.execute(
        select(Record).where(Record.record_id == record_id).with_for_update()
    )
    record = result.scalar_one_or_none()
    # 권한검증
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다.")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다.")
    # 러닝 종료되었는지 확인
    if record.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다.")
    # 종료시점 설정 및 기록시간 계산
    record.ended_at = datetime.now(UTC)
    if record.paused_at is not None: # 일시정지 중 종료
        record.total_paused_seconds += int((record.ended_at - record.paused_at).total_seconds())
        record.paused_at = None
    record.duration_seconds = (
        int((record.ended_at - record.started_at).total_seconds()) - record.total_paused_seconds
    )
    # 시간검증
    if record.duration_seconds < 60:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="러닝시간이 너무 짧아 기록되지 않았습니다.")
    if record.duration_seconds > 86400: # 24시간 초과 시
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="비정상적인 기록으로 저장되지 않았습니다.")
    # GPS 저장
    record.user_end_lat = body.user_end_lat
    record.user_end_lng = body.user_end_lng

    # course = await session.get(Course, record.course_id)
    # record.pace = record.duration_seconds / course_distance
    # TODO: 코스 거리 조회 후 pace 계산진행
    # TODO: 코스 시작/종료 좌표 조회 필요함(course 테이블)
    # is_completed = _check_completion(
    #     user_start_lat=record.user_start_lat,
    #     user_start_lng=record.user_start_lng,
    #     user_end_lat=record.user_end_lat,
    #     user_end_lng=record.user_end_lng,
    #     course_start_lat= ,
    #     course_start_lng= ,
    #     course_end_lat= ,
    #     course_end_lng= ,
    # )
    record.is_completed = False # 임시: 코스 좌표 연동 후 수정 예정
    await session.commit()
    await session.refresh(record)
    return RecordResponse.model_validate(record)


async def pause_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝 일시정지"""
    result = await session.execute(
        select(Record).where(Record.record_id == record_id).with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다.")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다.")
    if record.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다.")
    if record.paused_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 일시정지 되어있습니다.")
    record.paused_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(record)
    return RecordResponse.model_validate(record)


async def resume_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝 재시작"""
    result = await session.execute(
        select(Record).where(Record.record_id == record_id).with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다.")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다.")
    if record.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다.")
    if record.paused_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="일시정지 상태가 아닙니다.")
    now = datetime.now(UTC)
    record.total_paused_seconds += int((now - record.paused_at).total_seconds())
    record.paused_at = None
    await session.commit()
    await session.refresh(record)
    return RecordResponse.model_validate(record)


async def delete_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> None:
    """러닝기록 삭제"""
    result = await session.execute(
        select(Record).where(Record.record_id == record_id).with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다.")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 삭제할 수 있습니다.")
    await session.delete(record)
    await session.commit()


async def get_record(
        session: AsyncSession,
        user_id: int,
        record_id: int,
) -> RecordResponse:
    """러닝기록 단건 조회(기록 1개 상세)"""
    record = await session.get(Record, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다.")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 조회할 수 있습니다.")
    return RecordResponse.model_validate(record)


async def get_records(
        session: AsyncSession,
        user_id: int,
        page: int,
        size: int,
) -> RecordListResponse:
    """내 러닝기록 조회(내 기록 전체리스트)"""
    offset = (page - 1) * size
    total_result = await session.execute(
        select(func.count()).select_from(Record).where(Record.user_id == user_id)
    )
    total = total_result.scalar_one()
    result = await session.execute(
        select(Record)
        .where(Record.user_id == user_id)
        .order_by(Record.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    records = result.scalars().all()
    return RecordListResponse(
        items=[RecordResponse.model_validate(r) for r in records],
        total=total,
        page=page,
        size=size,
    )

