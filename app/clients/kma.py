"""기상청(kma) API 연동
ㅡ 단기예보(좌표 기반) + 기상특보(전국 현재 상태 조회, 강원 관련 줄만 필터링)."""

import re
from datetime import datetime, timedelta
from math import cos, log, pi, sin, tan
from zoneinfo import ZoneInfo

import httpx

from app.config import settings

_TIMEOUT = 10.0
_SUCCESS_RESULT_CODE = "00"
# 공공데이터포털 공통 에러코드 중 "03": "조회했는데 해당 데이터 없음"이라는 정상 응답
_NO_DATA_RESULT_CODE = "03"

KST = ZoneInfo("Asia/Seoul")

# ===== 위경도 -> 기상청 격자좌표(nx, ny) 변환 =====
# 기상청 단기예보 조회서비스 공식 변환식 - 순수 계산 처리
_RE = 6371.00877  # 지구 반경(km)
_GRID = 5.0  # 격자 간격(km)
_SLAT1 = 30.0  # 투영 위도1(도)
_SLAT2 = 60.0  # 투영 위도2(도)
_OLON = 126.0  # 기준점 경도(도)
_OLAT = 38.0  # 기준점 위도(도)
_XO = 43  # 기준점 X좌표(GRID)
_YO = 136  # 기준점 Y좌표(GRID)
_DEGRAD = pi / 180.0


def latlng_to_grid(lat: float, lng: float) -> tuple[int, int]:
    """위경도를 기상청 단기예보 격자좌표(nx, ny)로 변환."""
    re_ = _RE / _GRID
    slat1 = _SLAT1 * _DEGRAD
    slat2 = _SLAT2 * _DEGRAD
    olon = _OLON * _DEGRAD
    olat = _OLAT * _DEGRAD

    sn = tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5)
    sn = log(cos(slat1) / cos(slat2)) / log(sn)
    sf = tan(pi * 0.25 + slat1 * 0.5)
    sf = pow(sf, sn) * cos(slat1) / sn
    ro = tan(pi * 0.25 + olat * 0.5)
    ro = re_ * sf / pow(ro, sn)

    ra = tan(pi * 0.25 + lat * _DEGRAD * 0.5)
    ra = re_ * sf / pow(ra, sn)
    theta = lng * _DEGRAD - olon
    if theta > pi:
        theta -= 2.0 * pi
    if theta < -pi:
        theta += 2.0 * pi
    theta *= sn

    x = ra * sin(theta) + _XO + 0.5
    y = ro - ra * cos(theta) + _YO + 0.5
    return int(x), int(y)


# ===== 단기예보 =====
_FORECAST_URL = f"{settings.KMA_BASE_URL}/VilageFcstInfoService_2.0/getVilageFcst"
_FORECAST_CATEGORIES = {"TMP", "POP", "PTY", "SKY"}
# 단기예보 발표시각 - 각 시각으로부터 약 10분 뒤에 API로 제공됨
_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)


class KmaAPIError(Exception):
    """기상청 API 호출/응답 처리 실패."""


def get_latest_base_datetime(now: datetime) -> tuple[str, str]:
    """KST 기준으로 현재 시각에 사용 가능한 가장 최근 단기예보 발표시각을 계산."""
    now_kst = now.astimezone(KST)
    # 발표 후 API 제공까지의 여유(약 10분) 고려
    adjusted = now_kst - timedelta(minutes=10)
    candidates = [
        adjusted.replace(hour=hour, minute=0, second=0, microsecond=0)
        for hour in _BASE_HOURS
        if adjusted.replace(hour=hour, minute=0, second=0, microsecond=0) <= adjusted
    ]
    if candidates:
        latest = max(candidates)
    else:
        # 오늘 첫 발표(02시)도 아직이면 전날 23시 발표 사용
        latest = (adjusted - timedelta(days=1)).replace(
            hour=23, minute=0, second=0, microsecond=0
        )
    return latest.strftime("%Y%m%d"), latest.strftime("%H%M")


async def get_short_term_forecast(nx: int, ny: int) -> list[dict]:
    """단기예보(기온/강수확률/강수형태/하늘상태)를 조회 - 가장 가까운 미래 하루치만 반환.

    ㅡ 원본 API: 발표시각 기준 최대 약 3일치를 1~3시간 간격으로 줌
    ㅡ 우리 서비스: 러너가 "지금부터 당분간" 코스 괜찮은지 확인 목적.
    응답에 실제로 담긴 가장 가까운 날짜 하루치만 걸러서 반환.
    23시 발표 예보는 다음날부터 시작해서 '오늘' 날짜로 고정하면 X."""
    now = datetime.now(KST)
    base_date, base_time = get_latest_base_datetime(now)
    params = {
        "serviceKey": settings.KMA_API_KEY,
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.get(_FORECAST_URL, params=params)
    except httpx.TimeoutException:
        raise KmaAPIError("기상청 단기예보 API 응답이 지연되고 있습니다.") from None
    except httpx.RequestError:
        raise KmaAPIError("기상청 단기예보 API에 연결할 수 없습니다.") from None

    if res.status_code != 200:
        raise KmaAPIError(f"기상청 단기예보 API가 {res.status_code}를 반환했습니다.")

    try:
        data = res.json()
        header = data["response"]["header"]
        if header["resultCode"] != _SUCCESS_RESULT_CODE:
            raise KmaAPIError(
                f"기상청 단기예보 API 에러 {header['resultCode']}: {header['resultMsg']}"
            )
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
    except ValueError as e:
        raise KmaAPIError(f"기상청 단기예보 API 응답이 JSON 형식이 아닙니다: {e}") from None
    except (KeyError, TypeError) as e:
        raise KmaAPIError(f"기상청 단기예보 API 응답 구조가 예상과 다릅니다: {e}") from None

    relevant = [item for item in items if item.get("category") in _FORECAST_CATEGORIES]
    if not relevant:
        return []
    earliest_date = min(item["fcstDate"] for item in relevant)
    return [item for item in relevant if item["fcstDate"] == earliest_date]


# ===== 기상특보 (전국 특보현황조회 getPwnStatus 기반) =====
# ㅡ 기존: 목록/통보문 조회(getWthrWrnList/getWthrWrnMsg) 2개 결합
# → "같은 종류가 여러 지역에 발효 중인데 일부만 해제"되는 경우를 구분할 수 없었음.
# ㅡ 변경: 특보현황조회(getPwnStatus)는 KMA가 지역별로 정리한 현재 상태 텍스트(t6) 줌,
# 그 텍스트에서 강원 관련 + 동해 관련만 골라내는 방식으로 교체.
_PWN_STATUS_URL = f"{settings.KMA_BASE_URL}/WthrWrnInfoService/getPwnStatus"

# t6 텍스트 안에 이 키워드 중 하나라도 있어야 강원 관련 줄로 판단.
# ㅡ 시군 18개(find_sigungu()가 반환하는 이름과 동일, course/schemas.py)
# ㅡ "강원" 자체: 강원도 육상 + 강원북/중/남부앞바다(해상)까지 전부 이 글자를 포함
# ㅡ "동해중부": 강원 앞바다를 포괄하는 상위 해상 구역명
_GANGWON_KEYWORDS = (
    "강원",
    "동해중부",
    "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시",
    "홍천군", "횡성군", "영월군", "평창군", "정선군", "철원군", "화천군",
    "양구군", "인제군", "고성군", "양양군",
)


async def _kma_get(url: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.get(url, params=params)
    except httpx.TimeoutException:
        raise KmaAPIError("기상청 특보 API 응답이 지연되고 있습니다.") from None
    except httpx.RequestError:
        raise KmaAPIError("기상청 특보 API에 연결할 수 없습니다.") from None

    if res.status_code != 200:
        raise KmaAPIError(f"기상청 특보 API가 {res.status_code}를 반환했습니다.")

    try:
        data = res.json()
        header = data["response"]["header"]
        result_code = header["resultCode"]
        if result_code == _NO_DATA_RESULT_CODE:
            # 이 경우 응답에 "body" 자체가 없는 경우가 많아 아래 body 접근 시도하지 않고
            # 여기서 바로 "정상, 결과 없음"으로 취급해 빈 값 돌려줌.
            return {"items": None}
        if result_code != _SUCCESS_RESULT_CODE:
            raise KmaAPIError(f"기상청 특보 API 에러 {result_code}: {header['resultMsg']}")
        return data["response"]["body"]
    except ValueError as e:
        raise KmaAPIError(f"기상청 특보 API 응답이 JSON 형식이 아닙니다: {e}") from None
    except (KeyError, TypeError) as e:
        raise KmaAPIError(f"기상청 특보 API 응답 구조가 예상과 다릅니다: {e}") from None


async def get_weather_warning() -> str | None:
    """전국 특보 현재 상태(getPwnStatus)를 조회해 강원 관련 줄만 골라 반환.

    KMA가 이미 "지금 시점 기준으로 뭐가 활성인지"를 정리해서 주는 값
    ㅡ 발표/해제 이벤트를 우리가 직접 추적해 활성 여부를 판단할 필요 X
    ㅡ 가이드 파일과 응답 예시 참고해서 코딩

    t6(특보발효현황 내용): 한 줄에 종류+지역이 같이 있음
    t7(예비특보 발효현황): 종류 줄과 지역 줄이 분리돼있어 줄 단위로 거르지않고,
    강원 키워드 하나라도 포함되면 통쨰로 포함.
    """
    body = await _kma_get(
        _PWN_STATUS_URL,
        {
            "serviceKey": settings.KMA_API_KEY,
            "pageNo": 1,
            "numOfRows": 1,
            "dataType": "JSON",
        },
    )
    try:
        raw_items = body.get("items")
        if not raw_items:
            return None
        items = raw_items["item"]
        item = items[0] if isinstance(items, list) else items
    except (KeyError, TypeError, IndexError) as e:
        raise KmaAPIError(f"기상청 특보현황 응답 구조가 예상과 다릅니다: {e}") from None

    parts = _gangwon_relevant_lines(item.get("t6"))
    t7_block = _gangwon_relevant_block(item.get("t7"))
    if t7_block:
        parts.append(t7_block)
    return "\n".join(parts) if parts else None


def _has_content(text: str | None) -> str:
    """"없음" 자리에 공백이 섞여 오는 경우 실측함(예: "o 없 음") - 공백 제거 후 비교."""
    text = (text or "").strip()
    return "" if not text or "없음" in re.sub(r"\s+", "", text) else text


def _gangwon_relevant_lines(text: str | None) -> list[str]:
    text = _has_content(text)
    if not text:
        return []
    return [line for line in text.splitlines() if any(kw in line for kw in _GANGWON_KEYWORDS)]


def _gangwon_relevant_block(text: str | None) -> str | None:
    text = _has_content(text)
    if text and any(kw in text for kw in _GANGWON_KEYWORDS):
        return text
    return None
