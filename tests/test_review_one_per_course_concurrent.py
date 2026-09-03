"""코스당 리뷰 1개 제한에 대한 동시 작성 요청 테스트.

create_review는 INSERT 전에 "이미 리뷰가 있는지" 애플리케이션 레벨에서 먼저 조회하지만,
이 사전 조회만으로는 두 요청이 동시에 들어와 둘 다 "없음"을 확인한 뒤 각자 INSERT를
시도하는 경우를 막지 못한다. 실제 방어는 (course_id, user_id) UNIQUE 제약이 하고,
그 위반을 IntegrityError -> 409로 변환하는 처리가 있어야 한다.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.review.schemas import ReviewCreateRequest
from app.domain.review.service import create_review
from app.domain.user.models import User
from tests.conftest import FakeBackgroundTasks


async def test_concurrent_create_review_requests_create_only_one(db_session, review_test_course):
    """같은 유저가 같은 코스에 리뷰 작성을 동시에 두 번 시도해도 하나만 만들어져야 한다."""
    course_id = review_test_course.course_id
    user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.flush()
    review_test_course.user_ids.append(user.user_id)

    # 완주 기록이 있어야 리뷰를 쓸 수 있다
    db_session.add(
        Record(
            user_id=user.user_id,
            course_id=course_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            user_start_lat=1.0,
            user_start_lng=1.0,
            user_end_lat=2.0,
            user_end_lng=2.0,
            duration_seconds=600,
            is_completed=True,
        )
    )
    await db_session.commit()

    body = ReviewCreateRequest(content="동시 작성 테스트", difficulty="NORMAL")

    async def attempt():
        async with AsyncSessionLocal() as session:
            try:
                await create_review(
                    session=session,
                    user_id=user.user_id,
                    course_id=course_id,
                    body=body,
                    background_tasks=FakeBackgroundTasks(),
                )
                return "ok"
            except HTTPException as err:
                return err.status_code

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("ok") == 1 and results.count(409) == 1, (
        f"동시 리뷰 작성 중 정확히 하나만 성공하고 나머지는 409여야 하는데: {results}"
    )

    count_result = await db_session.execute(
        select(Review).where(Review.course_id == course_id, Review.user_id == user.user_id)
    )
    assert len(count_result.scalars().all()) == 1
