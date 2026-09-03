"""러닝 진행 중 pause/resume/end에 대한 동시 요청(중복 클릭) 테스트.

pause_record/resume_record/end_record는 모두 시작 시 Record 행을 with_for_update()로
잠근다 - 동시에 같은 동작을 두 번 요청해도(예: 종료 버튼 연타) 두 번째 요청은 첫 번째가
커밋할 때까지 대기했다가 이미 바뀐 상태를 보고 정상적으로 거절되어야 한다.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.database import AsyncSessionLocal
from app.domain.record.models import Record
from app.domain.record.schemas import RecordEndRequest
from app.domain.record.service import end_record, pause_record
from app.domain.user.models import User


async def _make_active_record(db_session, course_id: int, *, started_seconds_ago: int) -> int:
    user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.flush()

    record = Record(
        user_id=user.user_id,
        course_id=course_id,
        started_at=datetime.now(UTC) - timedelta(seconds=started_seconds_ago),
        user_start_lat=1.0,
        user_start_lng=1.0,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return user.user_id, record.record_id


async def test_concurrent_end_requests_only_one_succeeds(db_session, review_test_course):
    """종료 버튼을 연타해도(동시 종료 요청) 정확히 하나만 성공하고 나머지는 거절된다."""
    user_id, record_id = await _make_active_record(
        db_session, review_test_course.course_id, started_seconds_ago=120
    )
    review_test_course.user_ids.append(user_id)
    body = RecordEndRequest(user_end_lat=2.0, user_end_lng=2.0)

    async def attempt():
        async with AsyncSessionLocal() as session:
            try:
                await end_record(session=session, user_id=user_id, record_id=record_id, body=body)
                return "ok"
            except HTTPException as err:
                return err.status_code

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("ok") == 1 and results.count(400) == 1, (
        f"동시 종료 요청 중 정확히 하나만 성공해야 하는데: {results}"
    )


async def test_concurrent_pause_requests_only_one_succeeds(db_session, review_test_course):
    """일시정지 요청을 동시에 두 번 보내도 정확히 하나만 성공해야 한다."""
    user_id, record_id = await _make_active_record(
        db_session, review_test_course.course_id, started_seconds_ago=30
    )
    review_test_course.user_ids.append(user_id)

    async def attempt():
        async with AsyncSessionLocal() as session:
            try:
                await pause_record(session=session, user_id=user_id, record_id=record_id)
                return "ok"
            except HTTPException as err:
                return err.status_code

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("ok") == 1 and results.count(400) == 1, (
        f"동시 일시정지 요청 중 정확히 하나만 성공해야 하는데: {results}"
    )
