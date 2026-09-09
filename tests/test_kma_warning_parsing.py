"""기상특보 제목 파싱(종류별 최신 상태 추출) + API 응답 코드 처리 테스트.

ㅡ 실제 기상청 응답에서 "강풍주의보·풍랑주의보 해제·풍랑주의보 변경"처럼 여러 종류가
가운뎃점(·)으로 압축된 제목 관찰되어 방식 변경함
"""

from unittest.mock import AsyncMock, patch

from app.clients.kma import _ACTION_GROUP_PATTERN, _TYPE_PATTERN, get_weather_warning


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


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json_body = json_body

    def json(self):
        return self._json_body


def _fake_client(response: _FakeResponse):
    """httpx.AsyncClient(...) as client: await client.get(...) ㅡ 흉내 mock"""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_no_data_result_code_treated_as_no_warning_not_error():
    """공공데이터포털 공통 에러코드 "03"(NO_DATA): "조회했는데 결과없음."
    ㅡ 실제로 body 자체가 없는 응답이 관찰됐는데, 이걸 에러로 처리하면
    정상적으로 "특보 없음"인 상황도 API 실패로 오판."""
    no_data_response = _FakeResponse(
        200, {"response": {"header": {"resultCode": "03", "resultMsg": "NO_DATA"}}}
    )
    with patch("app.clients.kma.httpx.AsyncClient", return_value=_fake_client(no_data_response)):
        result = await get_weather_warning()
    assert result is None
