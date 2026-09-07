"""리뷰 체감 난이도 평균 계산 및 리뷰 변경 후 갱신 테스트.

get_average_difficulty는 저장된 값을 캐시하지 않고 매번 리뷰 테이블에서 다시 계산하므로,
리뷰가 추가/삭제되면 다음 조회 시 바로 최신 값이 반영되어야 한다.
"""

from sqlalchemy import delete, select

from app.domain.review.models import Review
from app.domain.review.service import get_average_difficulty
from tests.conftest import add_completed_reviews


async def test_average_difficulty_rounds_to_nearest_grade(db_session, review_test_course):
    """EASY 2개 + HARD 1개 평균(1.67)은 반올림해서 NORMAL이 되어야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=3)
    reviews = (
        await db_session.execute(
            select(Review).where(Review.course_id == review_test_course.course_id)
        )
    ).scalars().all()
    reviews[0].difficulty = "EASY"
    reviews[1].difficulty = "EASY"
    reviews[2].difficulty = "HARD"
    await db_session.commit()

    result = await get_average_difficulty(db_session, review_test_course.course_id)
    assert result == "NORMAL"


async def test_average_difficulty_updates_after_review_change(db_session, review_test_course):
    """리뷰 하나를 지우면(평균이 바뀌면) 다음 조회에서 바로 반영되어야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=2)
    reviews = (
        await db_session.execute(
            select(Review).where(Review.course_id == review_test_course.course_id)
        )
    ).scalars().all()
    reviews[0].difficulty = "EASY"
    reviews[1].difficulty = "HARD"
    await db_session.commit()

    # (1+3)/2 = 2.0 -> NORMAL
    assert await get_average_difficulty(db_session, review_test_course.course_id) == "NORMAL"

    # HARD 리뷰를 지우면 EASY 하나만 남는다
    await db_session.execute(delete(Review).where(Review.review_id == reviews[1].review_id))
    await db_session.commit()

    assert await get_average_difficulty(db_session, review_test_course.course_id) == "EASY"
