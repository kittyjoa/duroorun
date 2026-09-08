"""캐시 스키마 불일치 시 500 대신 재계산으로 복구되는지 테스트.

WeatherBriefingResponse에 나중에 필드가 추가되는 등 스키마가 바뀌면,
이걸 그대로 500으로 보내지 않고 캐시 미스처럼 취급해 재계산하는지 확인.
"""

from unittest.mock import AsyncMock, patch

import app.redis as app_redis
from app.clients import kma
from app.domain.course import weather_service


async def test_incompatible_cached_json_falls_back_to_recompute(
    db_session, redis_client, review_test_course
):
    # 실제 우리 프로젝트 redis는 있던 이벤트루프를 계속 재사용.
    # pytest용으로는 새로운걸 써야 하므로 none으로 시작해서 새로 연결
    app_redis._redis = None

    course_id = review_test_course.course_id
    # review_test_course 좌표는 (1.0,1.0)~(2.0,2.0) - 대표 좌표(중간점)는 (1.5, 1.5)
    nx, ny = kma.latlng_to_grid(1.5, 1.5)
    cache_key = f"weather_briefing:{nx}:{ny}"

    # 과거(다른 스키마) 캐시 흉내 - 지금 스키마에 없는 필드만 있고 필수 필드가 빠져있음
    await redis_client.set(cache_key, '{"legacy_field_only": true}')

    try:
        with (
            patch(
                "app.domain.course.weather_service.kma.get_short_term_forecast",
                new_callable=AsyncMock,
            ) as mock_forecast,
            patch(
                "app.domain.course.weather_service.kma.get_weather_warning",
                new_callable=AsyncMock,
            ) as mock_warning,
            patch(
                "app.domain.course.weather_service.generate_weather_briefing",
                new_callable=AsyncMock,
            ) as mock_briefing,
        ):
            mock_forecast.return_value = [
                {"fcstDate": "20260908", "fcstTime": "1400", "category": "TMP", "fcstValue": "20"}
            ]
            mock_warning.return_value = None
            mock_briefing.return_value = "테스트용 브리핑"

            response = await weather_service.get_weather_briefing(
                session=db_session, course_id=course_id, client_ip="127.0.0.1"
            )

        # 깨진 캐시를 500 없이 캐시 미스처럼 취급해 실제로 재계산했는지 확인
        mock_forecast.assert_called_once()
        mock_briefing.assert_called_once()
        assert response.briefing == "테스트용 브리핑"

        # 재계산 결과가 새 스키마로 다시 캐싱됐는지도 확인
        recached = await redis_client.get(cache_key)
        assert recached is not None
        assert "legacy_field_only" not in recached
    finally:
        await redis_client.delete(cache_key)
        await redis_client.delete("ratelimit:weather_briefing_fetch:127.0.0.1")
        # 제대로 정리가 되어야 여기서 쓰던걸 redis가 안 들고가니까
        # 테스트 끝날때도 시작할때처럼 none 처리
        app_redis._redis = None
