"""AI 요약 저장과 리뷰 수정 사이의 코스 행 락 테스트.

_attempt_update_summary가 저장 직전 코스 행을 잠그고, update_review/delete_review도
요약을 무효화하기 전 동일한 순서로 그 락을 잡는다. 이 락이 없으면, 저장 직전 재검증을
통과한 직후~커밋 전 사이에 리뷰가 수정되고 요약이 무효화돼도 알아채지 못한 채 낡은
내용으로 만든 요약을 그대로 저장해버릴 수 있었다 - 이 테스트는 그 구간 동안 리뷰 수정이
실제로 막혀 있다가, 요약 쪽이 커밋해야 비로소 진행되는지를 확인한다.
"""

import asyncio
import time

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.course.models import Course
from app.domain.review.models import Review
from app.domain.review.schemas import ReviewUpdateRequest
from app.domain.review.service import update_review
from tests.conftest import FakeBackgroundTasks, add_completed_reviews


async def test_course_lock_blocks_concurrent_review_update(db_session, review_test_course):
    """요약 쓰기 작업이 코스 행 락을 쥐고 있는 동안, 같은 코스의 리뷰 수정은 그 락이
    풀릴 때까지 완료되지 못해야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=1)
    course_id = review_test_course.course_id
    user_id = review_test_course.user_ids[0]
    review = await db_session.scalar(select(Review).where(Review.course_id == course_id))
    review_id = review.review_id

    lock_acquired = asyncio.Event()
    timeline: dict[str, float] = {}

    async def hold_course_lock():
        async with AsyncSessionLocal() as session:
            await session.execute(
                select(Course.course_id).where(Course.course_id == course_id).with_for_update()
            )
            lock_acquired.set()
            await asyncio.sleep(1)
            await session.commit()
        timeline["lock_released"] = time.monotonic()

    async def run_update_review():
        await lock_acquired.wait()
        async with AsyncSessionLocal() as session:
            await update_review(
                session=session,
                user_id=user_id,
                review_id=review_id,
                body=ReviewUpdateRequest(content="동시 수정된 내용", difficulty=None),
                background_tasks=FakeBackgroundTasks(),
            )
        timeline["update_finished"] = time.monotonic()

    await asyncio.gather(hold_course_lock(), run_update_review())

    assert timeline["update_finished"] >= timeline["lock_released"], (
        "리뷰 수정이 코스 락 해제 전에 끝났다 - 락이 요약 쓰기와 리뷰 수정 사이의 "
        "경쟁 상태를 막지 못하고 있다"
    )
