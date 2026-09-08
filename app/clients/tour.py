"""한국관광공사 국문 관광정보 API 연동 - 위치기반 관광정보 조회."""

import httpx

from app.config import settings

_LOCATION_BASED_LIST_URL = f"{settings.TOUR_BASE_URL}/locationBasedList2"
_MOBILE_OS = "ETC"
_MOBILE_APP = "duroorun"
_TIMEOUT = 10.0

_SUCCESS_RESULT_CODE = "0000"


class TourAPIError(Exception):
    """관광공사 API 호출/응답 처리 실패."""


async def get_nearby_attractions(
    lat: float, lng: float, radius_m: int, num_of_rows: int = 10
) -> list[dict]:
    """좌표 기준 반경 내 관광지 목록을 조회 (거리순 정렬은 API가 기본 제공)."""
    params = {
        "serviceKey": settings.TOUR_API_KEY,
        "MobileOS": _MOBILE_OS,
        "MobileApp": _MOBILE_APP,
        "pageNo": 1,
        "numOfRows": num_of_rows,
        "_type": "json",
        "mapX": lng,
        "mapY": lat,
        "radius": radius_m,
        "arrange": "E",  # 거리순
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.get(_LOCATION_BASED_LIST_URL, params=params)
    except httpx.TimeoutException:
        raise TourAPIError("관광공사 API 응답이 지연되고 있습니다.") from None
    except httpx.RequestError:
        raise TourAPIError("관광공사 API에 연결할 수 없습니다.") from None

    if res.status_code != 200:
        raise TourAPIError(f"관광공사 API가 {res.status_code}를 반환했습니다.")

    try:
        data = res.json()
        header = data["response"]["header"]
        result_code = header["resultCode"]
        if result_code != _SUCCESS_RESULT_CODE:
            raise TourAPIError(f"관광공사 API 에러 {result_code}: {header['resultMsg']}")

        body = data["response"]["body"]
        items = body.get("items")
        if not items:
            return []

        item = items["item"]
        if isinstance(item, dict):
            item = [item]
        return item
    except ValueError as e:
        raise TourAPIError(f"관광공사 API 응답이 JSON 형식이 아닙니다: {e}") from None
    except (KeyError, TypeError) as e:
        raise TourAPIError(f"관광공사 API 응답 구조가 예상과 다릅니다: {e}") from None
