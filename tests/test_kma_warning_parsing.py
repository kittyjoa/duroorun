"""기상특보현황(getPwnStatus) 응답 처리 + 강원 관련 줄 필터링 테스트.

ㅡ 기존: 목록/통보문 조회(getWthrWrnList/getWthrWrnMsg) 2개 결합
→ "같은 종류가 여러 지역에 발효 중인데 일부만 해제"되는 경우를 구분할 수 없었음.
ㅡ 변경: 특보현황조회(getPwnStatus)는 KMA가 지역별로 정리한 현재 상태 텍스트(t6) 줌,
그 텍스트에서 강원 관련 + 동해 관련만 골라내는 방식으로 교체.
"""

from unittest.mock import AsyncMock, patch

from app.clients.kma import get_weather_warning


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


def _status_response(t6: str, t7: str = "o 없음") -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {
                        "item": [
                            {
                                "other": "o 없음",
                                "t6": t6,
                                "t7": t7,
                                "tmEf": "202609110800",
                                "tmFc": 202609110600,
                                "tmSeq": 77,
                            }
                        ]
                    },
                    "totalCount": 1,
                },
            }
        },
    )


async def _call_with(t6: str, t7: str = "o 없음") -> str | None:
    with patch(
        "app.clients.kma.httpx.AsyncClient",
        return_value=_fake_client(_status_response(t6, t7)),
    ):
        return await get_weather_warning()


async def test_no_warning_returns_none():
    """실측된 형태 그대로("o 없 음" - 공백이 껴서 옴)를 특보 없음으로 인식."""
    assert await _call_with("o 없 음") is None
    assert await _call_with("o 없음") is None
    assert await _call_with("") is None


async def test_gangwon_sigun_line_is_returned():
    t6 = "o 호우주의보 : 강원도 강릉시, 속초시"
    result = await _call_with(t6)
    assert result == t6


async def test_non_gangwon_line_is_filtered_out():
    """강원과 무관한 지역만 언급된 줄은 전부 걸러져 결과가 None."""
    t6 = "o 폭염주의보 : 대구, 부산"
    assert await _call_with(t6) is None


async def test_only_gangwon_relevant_lines_are_kept_from_mixed_content():
    """여러 줄 중 강원 관련 줄만 남고 무관한 줄은 빠져야."""
    t6 = "o 폭염주의보 : 대구, 부산\no 대설주의보 : 강원도 태백시\no 황사주의보 : 제주도"
    result = await _call_with(t6)
    assert result == "o 대설주의보 : 강원도 태백시"


async def test_gangwon_sea_area_name_without_gangwon_word_is_matched():
    """"동해중부앞바다"처럼 강원 앞바다를 포괄하는 상위 해상 구역명은 "강원"이라는
    글자가 안 들어있어도 강원 관련으로 인식(동해남부는 경북/울산 관할이라 제외)."""
    t6 = "o 풍랑주의보 : 동해중부먼바다"
    assert await _call_with(t6) == t6

    unrelated = "o 풍랑주의보 : 동해남부먼바다, 남해동부먼바다"
    assert await _call_with(unrelated) is None


async def test_gangwon_named_sea_area_is_matched():
    t6 = "o 강풍주의보 : 강원북부앞바다, 강원중부앞바다"
    assert await _call_with(t6) == t6


async def test_preliminary_warning_in_t7_is_included_as_whole_block():
    """t7(예비특보 발효현황)은 "종류" 헤더 줄과 "지역" 줄이 분리돼 있음
    - 강원 키워드가 하나라도 있으면 통째로 포함."""
    t7 = "(1) 풍랑 예비특보\no 06월 07일 아침 : 동해중부앞바다, 동해남부앞바다"
    result = await _call_with("o 없 음", t7)
    assert result == t7
    assert "풍랑 예비특보" in result  # 종류 맥락이 안 사라졌는지 확인


async def test_preliminary_warning_without_gangwon_keyword_excluded():
    t7 = "(1) 풍랑 예비특보\no 06월 07일 아침 : 동해남부먼바다, 남해동부먼바다"
    assert await _call_with("o 없 음", t7) is None


async def test_both_t6_and_t7_relevant_content_are_combined():
    t6 = "o 호우주의보 : 강원도 강릉시"
    t7 = "(1) 대설 예비특보\no 강원도 정선군"
    result = await _call_with(t6, t7)
    assert result == f"{t6}\n{t7}"


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
