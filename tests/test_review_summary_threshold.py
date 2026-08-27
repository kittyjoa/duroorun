"""AI 리뷰 요약 생성 임계값 테스트.

FEATURES.md 규칙: 리뷰가 3개에 도달하면 첫 요약 생성, 3개 미만이면 요약 없음.
"""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.domain.review.models import ReviewSummary
from app.domain.review.service import _maybe_update_summary
from tests.conftest import add_completed_reviews


async def test_summary_not_created_below_threshold(db_session, review_test_course):
    """리뷰가 2개뿐이면 AI 요약이 생성되지 않는다 (Gemini 호출조차 되지 않아야 함)."""
    await add_completed_reviews(db_session, review_test_course, count=2)

    with patch(
        "app.domain.review.service.summarize_reviews", new_callable=AsyncMock
    ) as mock_summarize:
        await _maybe_update_summary(review_test_course.course_id)

    mock_summarize.assert_not_called()

    result = await db_session.execute(
        select(ReviewSummary).where(ReviewSummary.course_id == review_test_course.course_id)
    )
    assert result.scalar_one_or_none() is None


async def test_summary_created_at_threshold(db_session, review_test_course):
    """리뷰가 3개가 되면 최초 AI 요약이 생성되고, review_count가 3으로 저장된다."""
    await add_completed_reviews(db_session, review_test_course, count=3)

    with patch(
        "app.domain.review.service.summarize_reviews", new_callable=AsyncMock
    ) as mock_summarize:
        mock_summarize.return_value = "테스트용 요약 결과"
        await _maybe_update_summary(review_test_course.course_id)

    mock_summarize.assert_called_once()

    result = await db_session.execute(
        select(ReviewSummary).where(ReviewSummary.course_id == review_test_course.course_id)
    )
    summary = result.scalar_one_or_none()
    assert summary is not None
    assert summary.review_count == 3
    assert summary.summary == "테스트용 요약 결과"
