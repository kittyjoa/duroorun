"""러닝 기록 - 비즈니스 로직."""

from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.course.models import Course
from app.domain.record.models import Record
from app.domain.record.schemas import (
    MyRecordListResponse,
    MyRecordResponse,
    RecordEndRequest,
    RecordResponse,
    RecordStartRequest,
)

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 지표면 거리(m) - Haversine 공식"""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


def _check_completion(
    user_start_lat: float,
    user_start_lng: float,
    user_end_lat: float,
    user_end_lng: float,
    course_start_lat: float | None,
    course_start_lng: float | None,
    course_end_lat: float | None,
    course_end_lng: float | None,
) -> bool:
    """유저의 시작/종료 GPS가 코스 시작/종료 지점 허용 오차 내인지 확인.

    정방향(유저 시작≈코스 시작, 유저 종료≈코스 종료) 또는 역방향(유저 시작≈코스 종료,
    유저 종료≈코스 시작) 중 하나라도 만족하면 완주로 인정한다 (해안 트레일 양방향 주행 흔함).
    코스 좌표가 없으면(시드 누락 등) 검증 불가로 보고 미완주 처리한다.
    """
    if None in (course_start_lat, course_start_lng, course_end_lat, course_end_lng):
        return False

    forward_start = _haversine_distance_m(
        user_start_lat, user_start_lng, course_start_lat, course_start_lng
    )
    forward_end = _haversine_distance_m(user_end_lat, user_end_lng, course_end_lat, course_end_lng)
    if (
        forward_start <= settings.COMPLETION_RADIUS_M
        and forward_end <= settings.COMPLETION_RADIUS_M
    ):
        return True

    reverse_start = _haversine_distance_m(
        user_start_lat, user_start_lng, course_end_lat, course_end_lng
    )
    reverse_end = _haversine_distance_m(
        user_end_lat, user_end_lng, course_start_lat, course_start_lng
    )
    return (
        reverse_start <= settings.COMPLETION_RADIUS_M
        and reverse_end <= settings.COMPLETION_RADIUS_M
    )


async def start_record(
    session: AsyncSession,
    user_id: int,
    body: RecordStartRequest,
) -> RecordResponse:
    """러닝시작 - 기록생성"""
    course = await session.get(Course, body.course_id)
    if course is None or not course.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )

    active = await session.execute(
        select(Record).where(Record.user_id == user_id, Record.ended_at.is_(None))
    )
    if active.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 진행 중인 기록이 있습니다."
        )

    record = Record(
        user_id=user_id,
        course_id=body.course_id,
        started_at=datetime.now(UTC),
        user_start_lat=body.user_start_lat,
        user_start_lng=body.user_start_lng,
    )
    try:
        session.add(record)
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 진행 중인 기록이 있습니다."
        ) from err
    await session.refresh(record)
    return RecordResponse.model_validate(record)


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다."
        )
    if record.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다."
        )
    # 러닝 종료되었는지 확인
    if record.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다."
        )
    # 종료시점 설정 및 기록시간 계산
    record.ended_at = datetime.now(UTC)
    if record.paused_at is not None:  # 일시정지 중 종료
        record.total_paused_seconds += int((record.ended_at - record.paused_at).total_seconds())
        record.paused_at = None
    record.duration_seconds = (
        int((record.ended_at - record.started_at).total_seconds()) - record.total_paused_seconds
    )
    # 시간검증
    if record.duration_seconds < 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="러닝시간이 너무 짧아 기록되지 않았습니다.",
        )
    if record.duration_seconds > 86400:  # 24시간 초과 시
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="비정상적인 기록으로 저장되지 않았습니다.",
        )
    # GPS 저장
    record.user_end_lat = body.user_end_lat
    record.user_end_lng = body.user_end_lng

    course = await session.get(Course, record.course_id)
    record.pace = (
        record.duration_seconds / course.distance
        if course is not None and course.distance
        else None
    )
    # 러닝 도중 코스가 비활성화됐다면 완주 인증 기준점으로 신뢰하지 않는다
    # (기록 자체는 정상 저장, 완주 인증만 보류 — 좌표 None 케이스와 동일한 처리)
    course_active = course is not None and course.is_active
    course_has_coords = course is not None and course.has_verification_coords
    course_verifiable = course_active and course_has_coords
    record.is_completed = _check_completion(
        user_start_lat=record.user_start_lat,
        user_start_lng=record.user_start_lng,
        user_end_lat=record.user_end_lat,
        user_end_lng=record.user_end_lng,
        course_start_lat=course.start_lat if course_verifiable else None,
        course_start_lng=course.start_lng if course_verifiable else None,
        course_end_lat=course.end_lat if course_verifiable else None,
        course_end_lng=course.end_lng if course_verifiable else None,
    )
    # 완주 인증이 안 된 이유가 유저 잘못이 아니라 코스 쪽 문제(비활성화/좌표 없음)일 때만
    # 안내 문구를 채운다. Record 모델의 실제 컬럼이 아니라 이 응답 한정으로만 붙이는 값 -
    # DB에는 저장되지 않는다.
    if not course_active:
        record.verification_message = (
            "러닝 도중 코스가 비활성화되어 완주 인증이 처리되지 않았어요. "
            "다만 러닝 기록은 기록할 수 있어요."
        )
    elif not course_has_coords:
        record.verification_message = (
            "이 코스는 완주 인증을 지원하지 않아요. 다만 러닝 기록은 기록할 수 있어요."
        )
    else:
        record.verification_message = None
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다."
        )
    if record.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다."
        )
    if record.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다."
        )
    if record.paused_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="이미 일시정지 되어있습니다."
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다."
        )
    if record.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 수정할 수 있습니다."
        )
    if record.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="이미 종료된 기록입니다."
        )
    if record.paused_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="일시정지 상태가 아닙니다."
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다."
        )
    if record.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 삭제할 수 있습니다."
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="기록을 찾을 수 없습니다."
        )
    if record.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 기록만 조회할 수 있습니다."
        )
    return RecordResponse.model_validate(record)


async def get_records(
    session: AsyncSession,
    user_id: int,
    page: int,
    size: int,
) -> MyRecordListResponse:
    """내 러닝기록 조회(내 기록 전체리스트, 코스명 포함)"""
    offset = (page - 1) * size
    total_result = await session.execute(
        select(func.count()).select_from(Record).where(Record.user_id == user_id)
    )
    total = total_result.scalar_one()
    result = await session.execute(
        select(Record, Course.course_name, Course.course_type)
        .join(Course, Course.course_id == Record.course_id)
        .where(Record.user_id == user_id)
        # created_at만으로 정렬하면 같은 시각에 생성된 행끼리는 순서가 DB 실행마다
        # 달라질 수 있어(정렬 안정성 보장 안 됨), 페이지 경계에서 항목이 중복되거나
        # 누락될 수 있다 - PK를 보조 정렬 기준으로 추가해 항상 동일한 순서를 보장한다.
        .order_by(Record.created_at.desc(), Record.record_id.desc())
        .offset(offset)
        .limit(size)
    )
    items = []
    for record, course_name, course_type in result.all():
        # Record 모델의 실제 컬럼이 아니라 이 응답 한정으로만 붙이는 값 - DB에는 저장되지 않는다.
        record.course_name = course_name
        record.course_type = course_type
        items.append(MyRecordResponse.model_validate(record))
    return MyRecordListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )
