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
from app.domain.record.service import delete_record, end_record, pause_record
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


async def test_concurrent_end_and_delete_never_deletes_in_progress_record(
    db_session, review_test_course
):
    """다른 탭에서 러닝 종료 중인데 이 탭에서 동시에 삭제를 시도해도 락 덕분에 안전하다.

    delete_record와 end_record 둘 다 같은 행을 with_for_update()로 잠그므로, 둘 중 하나가
    반드시 다른 하나가 끝날 때까지 대기한다 - 결과는 항상 다음 둘 중 하나여야 한다:
    (a) delete_record가 먼저 락을 잡으면 아직 ended_at이 None이라 409로 거절되고,
        end_record는 그 뒤에 정상적으로 완료된다.
    (b) end_record가 먼저 락을 잡아 커밋하면, delete_record는 그 뒤 ended_at이 채워진
        걸 보고 정상적으로 삭제된다.
    어느 쪽이든 "진행 중인 기록이 그대로 삭제되는" 데이터 손상은 일어나지 않는다.
    """
    user_id, record_id = await _make_active_record(
        db_session, review_test_course.course_id, started_seconds_ago=120
    )
    review_test_course.user_ids.append(user_id)
    end_body = RecordEndRequest(user_end_lat=2.0, user_end_lng=2.0)

    async def attempt_end():
        async with AsyncSessionLocal() as session:
            try:
                await end_record(
                    session=session, user_id=user_id, record_id=record_id, body=end_body
                )
                return ("end", "ok")
            except HTTPException as err:
                return ("end", err.status_code)

    async def attempt_delete():
        async with AsyncSessionLocal() as session:
            try:
                await delete_record(session=session, user_id=user_id, record_id=record_id)
                return ("delete", "ok")
            except HTTPException as err:
                return ("delete", err.status_code)

    results = dict(await asyncio.gather(attempt_end(), attempt_delete()))

    # end_record는 delete_record가 이겨서 409를 받든, 자신이 먼저 커밋하든 항상 성공해야 한다 -
    # delete_record가 진행 중인 기록을 실제로 지워버리는 경우는 없기 때문이다.
    assert results["end"] == "ok", f"end_record는 항상 성공해야 하는데: {results}"
    assert results["delete"] in ("ok", 409), f"delete_record 결과가 예상 밖: {results}"
