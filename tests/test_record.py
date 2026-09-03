"""러닝 기록 - DB 제약 검증."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.domain.course.models import Course
from app.domain.record.models import Record


async def test_completed_record_requires_ended_at(db_session):
    """is_completed=true인데 ended_at이 없으면 DB가 거부한다 (관리자 통계 불일치 방지)."""
    course = Course(course_name=f"pytest-course-{uuid.uuid4().hex[:8]}", course_type="CUSTOM")
    db_session.add(course)
    await db_session.flush()

    db_session.add(
        Record(
            course_id=course.course_id,
            started_at=datetime.now(UTC),
            ended_at=None,
            is_completed=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
    await db_session.commit()
