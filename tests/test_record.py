"""러닝 기록 - DB 제약 검증 및 서비스 로직(삭제 권한) 검증."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.domain.course.models import Course
from app.domain.record.models import Record
from app.domain.record.service import delete_record
from app.domain.user.models import User
from app.main import app


async def _make_course(db_session) -> Course:
    course = Course(course_name=f"pytest-course-{uuid.uuid4().hex[:8]}", course_type="CUSTOM")
    db_session.add(course)
    await db_session.flush()
    return course


async def test_completed_record_requires_ended_at(db_session):
    """is_completed=true인데 ended_at이 없으면 completed_has_ended_at 제약 위반으로 거부된다."""
    course = await _make_course(db_session)

    db_session.add(
        Record(
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=None,
            is_completed=True,
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    # 다른 제약(FK 등) 위반과 혼동하지 않도록 실제로 이 제약이 원인인지 확인
    assert "ck_records_completed_has_ended_at" in str(exc_info.value)
    await db_session.rollback()

    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.commit()


async def test_completed_record_with_ended_at_saves_normally(db_session):
    """정상적으로 완주 처리된 기록(ended_at 있음)은 제약에 안 걸리고 저장된다."""
    course = await _make_course(db_session)

    record = Record(
        course_id=course.course_id,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        is_completed=True,
    )
    db_session.add(record)
    await db_session.commit()  # 예외 없이 통과해야 함

    await db_session.execute(delete(Record).where(Record.record_id == record.record_id))
    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.commit()


async def test_delete_record_by_non_owner_raises_403(db_session):
    """작성자가 아닌 유저가 삭제를 시도하면 403을 반환."""
    course = await _make_course(db_session)
    owner = User(nickname=f"pytest-owner-{uuid.uuid4().hex[:12]}")
    other_user = User(nickname=f"pytest-other-{uuid.uuid4().hex[:12]}")
    db_session.add_all([owner, other_user])
    await db_session.flush()

    record = Record(
        user_id=owner.user_id,
        course_id=course.course_id,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        is_completed=True,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await delete_record(
                session=db_session, user_id=other_user.user_id, record_id=record.record_id
            )
        assert exc_info.value.status_code == 403
    finally:
        await db_session.execute(delete(Record).where(Record.record_id == record.record_id))
        await db_session.execute(
            delete(User).where(User.user_id.in_([owner.user_id, other_user.user_id]))
        )
        await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
        await db_session.commit()


async def test_delete_record_by_owner_succeeds(db_session):
    """본인 기록은 삭제가 성공하고 DB에서 실제로 사라진다."""
    course = await _make_course(db_session)
    owner = User(nickname=f"pytest-owner-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()

    record = Record(
        user_id=owner.user_id,
        course_id=course.course_id,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        is_completed=True,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    record_id = record.record_id

    await delete_record(session=db_session, user_id=owner.user_id, record_id=record_id)

    remaining = await db_session.scalar(select(Record).where(Record.record_id == record_id))
    assert remaining is None

    await db_session.execute(delete(User).where(User.user_id == owner.user_id))
    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.commit()


async def test_delete_in_progress_record_raises_409(db_session):
    """진행 중(ended_at 없음)인 기록은 다른 세션이 사용 중일 수 있으므로 삭제가 거부된다."""
    course = await _make_course(db_session)
    owner = User(nickname=f"pytest-owner-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()

    record = Record(
        user_id=owner.user_id,
        course_id=course.course_id,
        started_at=datetime.now(UTC),
        ended_at=None,
        is_completed=False,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await delete_record(
                session=db_session, user_id=owner.user_id, record_id=record.record_id
            )
        assert exc_info.value.status_code == 409
    finally:
        await db_session.execute(delete(Record).where(Record.record_id == record.record_id))
        await db_session.execute(delete(User).where(User.user_id == owner.user_id))
        await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
        await db_session.commit()


async def test_delete_record_rejects_unauthenticated():
    """라우터에 인증 의존성이 실수로 빠지는 걸 잡기 위한 HTTP 레벨 테스트 - 서비스 함수만
    직접 호출하는 위 테스트들과 달리, 실제 ASGI 앱에 Authorization 헤더 없이 요청을 보내
    라우터가 인증을 요구하는지 확인한다(test_review_public_access.py와 동일한 패턴).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.delete("/api/v1/records/1")

    assert res.status_code == 401


async def test_in_progress_record_without_ended_at_saves_normally(db_session):
    """아직 진행 중인 기록(is_completed=false, ended_at=None)은 제약에 안 걸리고 저장된다."""
    course = await _make_course(db_session)

    record = Record(
        course_id=course.course_id,
        started_at=datetime.now(UTC),
        ended_at=None,
        is_completed=False,
    )
    db_session.add(record)
    await db_session.commit()  # 예외 없이 통과해야 함

    await db_session.execute(delete(Record).where(Record.record_id == record.record_id))
    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.commit()
