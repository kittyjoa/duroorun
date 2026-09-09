"""관광지 API 일부 지점 실패 시 캐싱 정책 테스트.

시작/종료점 중 하나라도 관광지 API 호출이 실패하면, 짧은 TTL 써야함.
ㅡ 일시 장애가 복구된 뒤에도 관광지 섹션이 오랜 시간 숨겨지는것 방지.
"""

from unittest.mock import AsyncMock, patch

import app.redis as app_redis
from app.clients.tour import TourAPIError
from app.config import settings
from app.domain.course.attraction_service import get_nearby_attractions


async def test_partial_fetch_failure_uses_short_cache_ttl(
    db_session, redis_client, review_test_course
):
    """시작점은 성공, 종료점은 실패해도 짧은 TTL로 캐싱돼야 한다."""
    app_redis._redis = None
    course_id = review_test_course.course_id
    cache_key = f"nearby_attractions:{course_id}"

    await redis_client.delete(cache_key)

    try:
        with patch(
            "app.domain.course.attraction_service.fetch_nearby_attractions",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = [
                [
                    {
                        "contentid": "1",
                        "title": "테스트 관광지",
                        "mapx": "128.9",
                        "mapy": "37.5",
                        "dist": "100",
                    }
                ],
                TourAPIError("관광공사 API 일시 장애 시뮬레이션"),
            ]

            response = await get_nearby_attractions(
                session=db_session, course_id=course_id, client_ip="127.0.0.1"
            )

        assert len(response.items) == 1

        ttl = await redis_client.ttl(cache_key)
        assert 0 < ttl <= settings.NEARBY_ATTRACTIONS_PARTIAL_FAILURE_CACHE_TTL_SECONDS, (
            f"부분 실패 응답인데 짧은 TTL이 아니라 ttl={ttl}로 캐싱됐다"
        )
    finally:
        await redis_client.delete(cache_key)
        await redis_client.delete("ratelimit:nearby_attractions_fetch:127.0.0.1")
        app_redis._redis = None


async def test_full_fetch_failure_uses_short_cache_ttl(
    db_session, redis_client, review_test_course
):
    """시작/종료점 둘 다 실패해도 빈 결과가 하루짜리 TTL로 캐싱되면 X."""
    app_redis._redis = None
    course_id = review_test_course.course_id
    cache_key = f"nearby_attractions:{course_id}"

    await redis_client.delete(cache_key)

    try:
        with patch(
            "app.domain.course.attraction_service.fetch_nearby_attractions",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = TourAPIError("관광공사 API 전체 장애 시뮬레이션")

            response = await get_nearby_attractions(
                session=db_session, course_id=course_id, client_ip="127.0.0.1"
            )

        assert response.items == []

        ttl = await redis_client.ttl(cache_key)
        assert 0 < ttl <= settings.NEARBY_ATTRACTIONS_PARTIAL_FAILURE_CACHE_TTL_SECONDS, (
            f"전체 실패 응답인데 짧은 TTL이 아니라 ttl={ttl}로 캐싱됐다"
        )
    finally:
        await redis_client.delete(cache_key)
        await redis_client.delete("ratelimit:nearby_attractions_fetch:127.0.0.1")
        app_redis._redis = None
