"""예보 데이터 -> 아이콘용 condition 순수 함수 테스트."""

from datetime import UTC, datetime
from unittest.mock import patch

from app.domain.course.weather_service import _get_current_condition


def _patched_now(fake_now: datetime):
    return patch("app.domain.course.weather_service.datetime", **{"now.return_value": fake_now})


def _item(fcst_time: str, category: str, value: str, fcst_date: str = "20260908") -> dict:
    return {"fcstDate": fcst_date, "fcstTime": fcst_time, "category": category, "fcstValue": value}


def test_prefers_precipitation_over_sky_at_same_slot():
    """같은 시각 슬롯에 SKY(맑음)와 PTY(비)가 같이 있으면 PTY가 우선"""
    items = [_item("1400", "SKY", "1"), _item("1400", "PTY", "1")]  # 맑음, 비
    fake_now = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    with _patched_now(fake_now):
        assert _get_current_condition(items) == "비"


def test_falls_back_to_sky_when_no_precipitation():
    items = [_item("1400", "SKY", "3"), _item("1400", "PTY", "0")]  # 구름많음, 강수없음
    fake_now = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    with _patched_now(fake_now):
        assert _get_current_condition(items) == "구름많음"


def test_picks_nearest_time_slot_not_first_or_last():
    """여러 시각 슬롯 중 지금과 가장 가까운 것만 골라야 한다(하루 전체 평균 X)."""
    items = [
        _item("0600", "SKY", "1"),  # 맑음 (멀음)
        _item("1400", "SKY", "4"),  # 흐림 (가장 가까움)
        _item("2300", "SKY", "3"),  # 구름많음 (멀음)
    ]
    fake_now = datetime(2026, 9, 8, 13, 50, tzinfo=UTC)  # 13:50 -> 1400이 가장 가까움
    with _patched_now(fake_now):
        assert _get_current_condition(items) == "흐림"


def test_empty_items_returns_none():
    assert _get_current_condition([]) is None


def test_forecast_belongs_to_next_day_picks_earliest_slot_not_nearest_clock_time():
    """ㅡ 23시 발표 예보는 다음날 00시부터 시작.
    예보 날짜가 오늘과 다르면(=슬롯이 전부 미래) 가장 가까운 슬롯 그대로 고르기."""
    items = [
        _item("0000", "SKY", "4", fcst_date="20260909"),  # 흐림 (진짜 가까움)
        _item("2300", "SKY", "1", fcst_date="20260909"),  # 맑음 (진짜 멀음)
    ]
    fake_now = datetime(2026, 9, 8, 23, 34, tzinfo=UTC)  # 아직 9/8인데 예보는 9/9치
    with _patched_now(fake_now):
        assert _get_current_condition(items) == "흐림"
