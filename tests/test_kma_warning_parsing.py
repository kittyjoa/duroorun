"""기상특보 제목 파싱(종류별 최신 상태 추출) 테스트.

ㅡ 실제 기상청 응답에서 "강풍주의보·풍랑주의보 해제·풍랑주의보 변경"처럼 여러 종류가
가운뎃점(·)으로 압축된 제목 관찰되어 방식 변경함
"""

from app.clients.kma import _ACTION_GROUP_PATTERN, _TYPE_PATTERN


def _extract(title: str) -> dict[str, str]:
    """kma.get_weather_warning 안의 매칭 루프와 동일한 로직 - 타입 -> 최신 액션."""
    result: dict[str, str] = {}
    for types_blob, action in _ACTION_GROUP_PATTERN.findall(title):
        for wtype in _TYPE_PATTERN.findall(types_blob):
            result[wtype] = action
    return result


def test_simple_single_type_title():
    """기본 케이스 - 종류 하나, 공백으로만 구분된 제목."""
    assert _extract("풍랑주의보 해제") == {"풍랑": "해제"}
    assert _extract("폭염경보 발표") == {"폭염": "발표"}


def test_compound_title_with_middle_dot_separator():
    """여러 종류가 ·로 압축된 제목에서 앞쪽 종류가 누락되면 안 된다."""
    title = "강풍주의보·풍랑주의보 해제·풍랑주의보 변경"
    result = _extract(title)
    assert result["강풍"] == "해제"
    # 풍랑은 같은 제목 안에서 해제 -> 변경 순으로 다시 언급되므로 마지막 값(변경)이 남아야 함
    assert result["풍랑"] == "변경"


def test_three_types_compressed_together():
    title = "강풍주의보·풍랑주의보·호우주의보 발표"
    result = _extract(title)
    assert result == {"강풍": "발표", "풍랑": "발표", "호우": "발표"}
