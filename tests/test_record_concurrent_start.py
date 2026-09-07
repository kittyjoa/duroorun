"""동시 러닝 시작 요청에 대한 중복 생성 방지 테스트.

start_record는 INSERT 전에 "진행 중인 기록이 있는지" 애플리케이션 레벨에서 먼저
조회하지만, 이 사전 조회만으로는 동시 요청을 막지 못한다 - 두 요청의 조회가 모두
"없음"을 확인한 뒤에야 각자 INSERT를 시도할 수 있기 때문이다. 실제 방어는 DB의
partial unique index(uq_records_active_user, WHERE ended_at IS NULL)가 하고,
그 위반을 IntegrityError -> 409로 변환하는 처리가 있어야 한다. 이 테스트는 두 시작
요청을 실제로 동시에(각자 별도 세션으로) 실행해서, 정확히 하나만 성공하고 나머지는
409로 거절되며, DB에 진행 중인 기록이 하나만 남는지 확인한다.
"""

import asyncio
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.record.models import Record
from app.domain.record.schemas import RecordStartRequest
from app.domain.record.service import start_record
from app.domain.user.models import User


async def test_concurrent_start_requests_create_only_one_active_record(
    db_session, review_test_course
):
    """같은 유저가 동시에 두 번 "시작"을 눌러도 진행 중인 기록은 하나만 만들어져야 한다."""
    user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    review_test_course.user_ids.append(user.user_id)

    body = RecordStartRequest(
        course_id=review_test_course.course_id, user_start_lat=1.0, user_start_lng=1.0
    )

    async def attempt():
        async with AsyncSessionLocal() as session:
            try:
                await start_record(session=session, user_id=user.user_id, body=body)
                return "ok"
            except HTTPException as err:
                return err.status_code

    results = await asyncio.gather(attempt(), attempt())

    assert results.count("ok") == 1 and results.count(409) == 1, (
        f"동시 시작 요청 중 정확히 하나만 성공하고 나머지는 409여야 하는데: {results}"
    )

    active_records = await db_session.execute(
        select(Record).where(Record.user_id == user.user_id, Record.ended_at.is_(None))
    )
    assert len(active_records.scalars().all()) == 1, (
        "DB에 진행 중인 기록이 정확히 하나만 있어야 한다 - 중복 생성됐다면 DB 제약이 안 걸린 것"
    )
