"""Gemini 호출 실패 시 짧은 쿨다운이 걸리는지 테스트.

Gemini 호출이 실패하면 summary.review_count가 갱신되지 않아 재생성 임계값을 넘긴
상태가 그대로 유지된다 - 쿨다운이 없으면 Gemini가 복구되기 전까지 들어오는 모든 리뷰
변경이 각자 실패할 호출을 또 시도하게 된다. 이 테스트는 실패 직후 Redis에 짧은
쿨다운이 실제로 걸리는지 확인한다.
"""

from unittest.mock import AsyncMock, patch

from app.domain.review.service import _maybe_update_summary
from app.redis import get_redis
from tests.conftest import add_completed_reviews


async def test_gemini_failure_sets_short_cooldown(db_session, review_test_course):
    """Gemini 호출이 실패하면, 성공 시보다 짧은 쿨다운이 Redis에 걸려야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=3)
    course_id = review_test_course.course_id
    cooldown_key = f"review_summary_cooldown:{course_id}"

    redis = await get_redis()
    await redis.delete(cooldown_key)

    with patch(
        "app.domain.review.service.summarize_reviews", new_callable=AsyncMock
    ) as mock_summarize:
        mock_summarize.side_effect = RuntimeError("Gemini API 장애 시뮬레이션")
        await _maybe_update_summary(course_id)

    mock_summarize.assert_called_once()

    ttl = await redis.ttl(cooldown_key)
    assert 0 < ttl <= 20, (
        f"Gemini 실패 후 짧은 쿨다운(<=20초)이 걸려있어야 하는데 ttl={ttl}"
    )

    await redis.delete(cooldown_key)
