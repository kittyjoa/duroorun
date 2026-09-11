"""_get_temp_stats / _get_weather_tip (특보 없을 때 통계칩+팁) 순수 함수 테스트."""

from app.domain.course.weather_service import _get_temp_stats, _get_weather_tip


def _tmp(value: str) -> dict:
    return {"category": "TMP", "fcstValue": value}


def test_get_temp_stats_picks_min_and_max():
    items = [_tmp("18"), _tmp("22"), _tmp("15"), _tmp("25")]
    assert _get_temp_stats(items) == (15.0, 25.0)


def test_get_temp_stats_ignores_non_tmp_categories():
    items = [_tmp("20"), {"category": "SKY", "fcstValue": "1"}]
    assert _get_temp_stats(items) == (20.0, 20.0)


def test_get_temp_stats_empty_returns_none():
    assert _get_temp_stats([]) == (None, None)


def test_tip_hot_day():
    assert _get_weather_tip(20.0, 30.0) == "더위 조심! 수분 보충하고 자외선 차단제도 챙기세요"


def test_tip_cold_day():
    assert _get_weather_tip(2.0, 8.0) == "쌀쌀해요, 겉옷 챙기세요"


def test_tip_big_temp_swing():
    assert _get_weather_tip(10.0, 21.0) == "일교차가 크니 얇은 겉옷 하나 챙기면 좋아요"


def test_tip_mild_day_default():
    assert _get_weather_tip(15.0, 20.0) == "쾌적한 날씨예요, 즐거운 러닝 되세요!"


def test_tip_none_when_no_temp_data():
    assert _get_weather_tip(None, None) is None


def test_hot_takes_priority_over_cold_and_swing():
    """최고기온이 더위 기준을 넘으면 일교차가 커도 더위 팁이 우선한다."""
    assert _get_weather_tip(3.0, 29.0) == "더위 조심! 수분 보충하고 자외선 차단제도 챙기세요"
