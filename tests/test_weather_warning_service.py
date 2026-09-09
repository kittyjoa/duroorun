"""기상특보(경보) 관련 동작 테스트
ㅡ 조회 실패 안내, 전역 캐싱, 지역별 코멘트 분리, 동시성 락.

날씨 특보 조회 실패를 "특보 없음"으로 잘못 안내하던 문제와,
캐싱 재설계(예보/특보 분리, 특보-지역 관련성 코멘트를 시군 단위로 캐싱,
thundering herd 방지 락)를 검증한다.
"""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import app.redis as app_redis
from app.clients import kma
from app.clients.kma import KmaAPIError
from app.domain.course import weather_service


async def test_warning_fetch_failure_is_not_reported_as_no_warning(
    db_session, redis_client, review_test_course
):
    """특보 API 조회 자체가 실패하면 "특보 없음"이 아니라 "확인 못함"으로 안내.

    이전에는 실패해도 warning_raw_text=None으로만 남아 정상적인 "특보 없음"과 구분 X,
    ㅡ 실패 시 성공 여부(warning_ok)가 응답 문구까지 유지되는지 확인.
    """
    app_redis._redis = None
    course_id = review_test_course.course_id
    nx, ny = kma.latlng_to_grid(1.5, 1.5)
    forecast_cache_key = f"weather_forecast_briefing:{nx}:{ny}"

    await redis_client.delete(forecast_cache_key)
    await redis_client.delete(weather_service._WARNING_RAW_CACHE_KEY)

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
                "app.domain.course.weather_service.generate_forecast_summary",
                new_callable=AsyncMock,
            ) as mock_forecast_summary,
        ):
            mock_forecast.return_value = [
                {"fcstDate": "20260908", "fcstTime": "1400", "category": "TMP", "fcstValue": "20"}
            ]
            mock_warning.side_effect = KmaAPIError("기상특보 API 장애 시뮬레이션")
            mock_forecast_summary.return_value = "테스트 예보 요약"

            response = await weather_service.get_weather_briefing(
                session=db_session, course_id=course_id, client_ip="127.0.0.1"
            )

        assert response.warning_raw_text is None
        assert "특보 정보를 확인하지 못했습니다" in response.briefing
        assert "현재 발효 중인 특보는 없습니다" not in response.briefing

        cached = json.loads(await redis_client.get(weather_service._WARNING_RAW_CACHE_KEY))
        assert cached == {"ok": False, "text": None}
    finally:
        await redis_client.delete(forecast_cache_key)
        await redis_client.delete(weather_service._WARNING_RAW_CACHE_KEY)
        await redis_client.delete("ratelimit:weather_briefing_fetch:127.0.0.1")
        app_redis._redis = None


async def test_warning_comment_differs_by_course_region(redis_client):
    """같은 특보 원문이어도 코스 지역(시군)이 다르면
    캐시 엔트리와 코멘트가 독립적으로 계산돼야 한다.

    격자가 겹치는 다른 시군 코스가 같은 브리핑 문구를 공유하던 문제 방지
    ㅡ 지금 구조에서는 캐시 키에 시군이 들어가는 이 함수가 그 역할을 한다.
    """
    warning_text = "테스트용 특보 원문 - 강릉시 일대 호우주의보"
    warning_hash = hashlib.sha256(warning_text.encode()).hexdigest()[:16]
    key_gangneung = f"weather_warning_comment:강원 강릉시:{warning_hash}"
    key_sokcho = f"weather_warning_comment:강원 속초시:{warning_hash}"
    lock_gangneung = f"{key_gangneung}:lock"
    lock_sokcho = f"{key_sokcho}:lock"

    await redis_client.delete(key_gangneung, key_sokcho, lock_gangneung, lock_sokcho)

    try:
        with patch(
            "app.domain.course.weather_service.generate_warning_relevance_comment",
            new_callable=AsyncMock,
        ) as mock_comment:
            mock_comment.side_effect = [
                "강릉시는 특보 지역과 관련 있어 보입니다.",
                "속초시는 특보 지역과 무관해 보입니다.",
            ]
            comment_gangneung = await weather_service._get_warning_comment(
                redis_client, "강원 강릉시", warning_text
            )
            comment_sokcho = await weather_service._get_warning_comment(
                redis_client, "강원 속초시", warning_text
            )

        assert mock_comment.await_count == 2
        assert comment_gangneung != comment_sokcho
        assert "강릉시" in comment_gangneung
        assert "속초시" in comment_sokcho
    finally:
        await redis_client.delete(key_gangneung, key_sokcho, lock_gangneung, lock_sokcho)


async def test_warning_comment_lock_prevents_duplicate_gemini_calls(redis_client):
    """새 특보 직후 여러 요청이 동시에 같은 (시군, 특보) 조합을 조회해도,
    Gemini 호출은 한번만 (thundering herd 방지 락)."""
    warning_text = "테스트용 동시성 특보 원문"
    location_hint = "강원 동시성테스트시"
    warning_hash = hashlib.sha256(warning_text.encode()).hexdigest()[:16]
    cache_key = f"weather_warning_comment:{location_hint}:{warning_hash}"
    lock_key = f"{cache_key}:lock"
    await redis_client.delete(cache_key, lock_key)

    call_count = 0

    async def slow_generate(_location_hint, _warning_raw_text):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.3)
        return "동시성 테스트 코멘트"

    try:
        with patch(
            "app.domain.course.weather_service.generate_warning_relevance_comment",
            side_effect=slow_generate,
        ):
            results = await asyncio.gather(
                *(
                    weather_service._get_warning_comment(redis_client, location_hint, warning_text)
                    for _ in range(5)
                )
            )

        assert call_count == 1, f"Gemini가 {call_count}번 호출됨 - 락이 동시 호출을 못 막고 있다"
        assert all(r == "동시성 테스트 코멘트" for r in results)
    finally:
        await redis_client.delete(cache_key, lock_key)
