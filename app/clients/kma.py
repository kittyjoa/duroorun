"""기상청(kma) API 연동
ㅡ 단기예보(좌표 기반) + 기상특보(강원 전체, stnId=105)."""

import asyncio
import re
from datetime import datetime, timedelta
from math import cos, log, pi, sin, tan
from zoneinfo import ZoneInfo

import httpx

from app.config import settings

_TIMEOUT = 10.0
_SUCCESS_RESULT_CODE = "00"

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
    """오늘 하루치 단기예보(기온/강수확률/강수형태/하늘상태)를 조회.

    ㅡ 원본 API: 발표시각 기준 최대 약 3일치를 1~3시간 간격으로 줌
    ㅡ 우리 서비스: 러너가 오늘 코스 괜찮은지 확인 목적이라 오늘 날짜 슬롯만 걸러서 반환.
    """
    now = datetime.now(KST)
    base_date, base_time = get_latest_base_datetime(now)
    today = now.strftime("%Y%m%d")
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

    return [
        item
        for item in items
        if item.get("fcstDate") == today and item.get("category") in _FORECAST_CATEGORIES
    ]


# ===== 기상특보 (강원 전체, stnId=105 고정) =====
_WARNING_LIST_URL = f"{settings.KMA_BASE_URL}/WthrWrnInfoService/getWthrWrnList"
_WARNING_MSG_URL = f"{settings.KMA_BASE_URL}/WthrWrnInfoService/getWthrWrnMsg"
_STN_ID_GANGWON = "105"
_WARNING_TYPES = (
    "강풍",
    "풍랑",
    "호우",
    "대설",
    "태풍",
    "한파",
    "폭염",
    "건조",
    "안개",
    "황사",
    "열대야",
    "폭풍해일",
    "지진해일",
)
# 특보 제목에 종류가 여러 개 붙어 나오는 경우 발견.
# (예: "강풍주의보·풍랑주의보 해제·풍랑주의보 변경")
# 그래서 2단계로 수정:
#   1) 그룹 1: "강풍주의보·풍랑주의보"처럼 ·로 이어붙은 종류 덩어리 전체를 통으로 잡음
#   2) 그룹 2: 그 덩어리 바로 뒤에 오는 액션(해제/발표/변경) 하나를 잡음
# → 그룹 1 안에서 종류 이름("강풍", "풍랑")을 하나씩 다시 뽑아내서,
#   그룹 2에서 잡은 액션을 그 종류들 전부에 똑같이 적용.
_TYPE_ALTERNATION = "|".join(_WARNING_TYPES)
_ACTION_GROUP_PATTERN = re.compile(
    rf"((?:(?:{_TYPE_ALTERNATION})(?:주의보|경보)?[·,]?)+)\s*(해제|발표|변경)"
)
_TYPE_PATTERN = re.compile(_TYPE_ALTERNATION)
# 원문 조립 시 실제 내용이 있는 필드만 포함 (t5는 타임스탬프, "없음" 플레이스홀더는 제외)
_MSG_TEXT_FIELDS = ("t1", "t2", "t3", "t4", "t6", "t7")


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
        if header["resultCode"] != _SUCCESS_RESULT_CODE:
            raise KmaAPIError(
                f"기상청 특보 API 에러 {header['resultCode']}: {header['resultMsg']}"
            )
        return data["response"]["body"]
    except ValueError as e:
        raise KmaAPIError(f"기상청 특보 API 응답이 JSON 형식이 아닙니다: {e}") from None
    except (KeyError, TypeError) as e:
        raise KmaAPIError(f"기상청 특보 API 응답 구조가 예상과 다릅니다: {e}") from None


def _format_warning_message(item: dict) -> str | None:
    lines = []
    for key in _MSG_TEXT_FIELDS:
        value = (item.get(key) or "").strip()
        if value and "없음" not in value:
            lines.append(value)
    return "\n".join(lines) if lines else None


async def get_weather_warning() -> str | None:
    """강원 전체(stnId=105) 기준 현재 발효 중인 기상특보 원문을 조회.

    특보는 발표/해제/변경 이벤트의 흐름이라 날짜로 필터링 X.
    ㅡ 최근 이벤트 목록을 종류별로 그룹핑해 각 종류의 최신 상태만 남기고,
    아직 해제되지 않은 종류만 원문을 가져와 이어붙임.

    fromTmFc/toTmFc 날짜 범위 파라미터는 딕셔너리에서 뺌.
    ㅡ 실측 결과 이 파라미터를 넣으면 서버가 거의 항상 DB_ERROR 반환,
    아예 빼면 성공 + 최근/현재 이벤트만 자동으로 돌려줌.
    ㅡ 날짜 필터 넣었다가 실패하면 "특보 없음"으로 잘못 처리된 경우도 있었음.
    """
    body = await _kma_get(
        _WARNING_LIST_URL,
        {
            "serviceKey": settings.KMA_API_KEY,
            "pageNo": 1,
            "numOfRows": 100,
            "dataType": "JSON",
            "stnId": _STN_ID_GANGWON,
        },
    )
    # _kma_get은 자기 안에서만 KeyError/TypeError를 KmaAPIError로 바꿈.
    # ㅡ try/except로 감싸 항상 KmaAPIError만 던지도록
    # ㅡ 기상특보 쪽이 이상한 응답 줘도 단기예보 결과까지 같이 죽지 않도록
    try:
        raw_items = body.get("items")
        if not raw_items:
            return None
        items = raw_items["item"]
        if isinstance(items, dict):
            items = [items]
    except (KeyError, TypeError) as e:
        raise KmaAPIError(f"기상청 특보 목록 응답 구조가 예상과 다릅니다: {e}") from None

    # tmFc 오름차순으로 훑으면서 종류별 최신 상태(action)를 계속 덮어쓴다
    items_sorted = sorted(items, key=lambda it: (it.get("tmFc", 0), it.get("tmSeq", 0)))
    latest_action: dict[str, str] = {}
    latest_item: dict[str, dict] = {}
    for item in items_sorted:
        title = item.get("title", "")
        for types_blob, action in _ACTION_GROUP_PATTERN.findall(title):
            for warning_type in _TYPE_PATTERN.findall(types_blob):
                latest_action[warning_type] = action
                latest_item[warning_type] = item

    active_types = [wtype for wtype, action in latest_action.items() if action != "해제"]
    if not active_types:
        return None

    async def _fetch_message(wtype: str) -> str | None:
        item = latest_item[wtype]
        msg_body = await _kma_get(
            _WARNING_MSG_URL,
            {
                "serviceKey": settings.KMA_API_KEY,
                "pageNo": 1,
                "numOfRows": 5,
                "dataType": "JSON",
                "stnId": item.get("stnId", _STN_ID_GANGWON),
                "tmFc": item["tmFc"],
            },
        )
        try:
            msg_items = msg_body.get("items")
            if not msg_items:
                return None
            msg_item = msg_items["item"]
            if isinstance(msg_item, list):
                msg_item = msg_item[0]
        except (KeyError, TypeError) as e:
            raise KmaAPIError(f"기상청 특보 통보문 응답 구조가 예상과 다릅니다: {e}") from None
        return _format_warning_message(msg_item)

    # 활성 종류가 여러 개(예: 태풍 시즌에 강풍+풍랑+호우 동시 발효)일 때 순차 호출하면
    # 종류 수만큼 왕복시간이 누적됨 → 병렬 조회 방식으로 변경.
    texts = await asyncio.gather(*(_fetch_message(wtype) for wtype in active_types))
    return "\n\n".join(text for text in texts if text) or None
