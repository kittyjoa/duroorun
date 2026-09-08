"""기상청 위경도 -> 격자좌표(nx, ny) 변환 공식 검증."""

from app.clients.kma import latlng_to_grid


def test_seoul_city_hall_grid():
    # 기상청 단기예보 조회서비스 공식 예시로 널리 쓰이는 기준값(서울시청)
    assert latlng_to_grid(37.5665, 126.9780) == (60, 127)
