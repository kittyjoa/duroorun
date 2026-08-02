"""두루누비 API 연동 ㅡ 시드파일이 씀"""

import httpx

from app.config import settings

_COURSE_LIST_URL = f"{settings.DURUNUBI_BASE_URL}/courseList"
_MOBILE_OS = "ETC"
_MOBILE_APP = "duroorun"
_TIMEOUT = 10.0

_SUCCESS_RESULT_CODE = "0000"


class DurunubiAPIError(Exception):
    """두루누비 API 호출/응답 처리 실패."""


async def fetch_course_list(
    page_no: int, num_of_rows: int = 100, crs_kor_nm: str | None = None
) -> tuple[list[dict], int]:
    """두루누비 코스 목록 한 페이지를 조회합니다.

    crs_kor_nm을 넘기면 코스명 기준으로 서버 단에서 필터링됨(부분일치, 예: "해파랑길").
    반환값: 해당 페이지의 코스 원본 dict 리스트, 전체 코스 개수.
    페이지 끝까지 순회하는 건 호출하는 쪽(seed_courses.py)의 책임.
    """
    params = {
        "serviceKey": settings.DURUNUBI_API_KEY,
        "MobileOS": _MOBILE_OS,
        "MobileApp": _MOBILE_APP,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "_type": "json",
    }
    if crs_kor_nm:
        params["crsKorNm"] = crs_kor_nm
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.get(_COURSE_LIST_URL, params=params)
    except httpx.TimeoutException:
        raise DurunubiAPIError("두루누비 API 응답이 지연되고 있습니다.") from None
    except httpx.RequestError:
        raise DurunubiAPIError("두루누비 API에 연결할 수 없습니다.") from None

    if res.status_code != 200:
        raise DurunubiAPIError(f"두루누비 API가 {res.status_code}를 반환했습니다.")

    try:
        data = res.json()
        header = data["response"]["header"]
        result_code = header["resultCode"]
        if result_code != _SUCCESS_RESULT_CODE:
            raise DurunubiAPIError(f"두루누비 API 에러 {result_code}: {header['resultMsg']}")

        body = data["response"]["body"]
        total_count = body["totalCount"]
        items = body.get("items")
        if not items:
            return [], total_count

        item = items["item"]
        # 결과 1건이면: 리스트 X, dict 하나로 옴 (data.go.kr JSON 변환 특성)
        if isinstance(item, dict):
            item = [item]
        return item, total_count
    except ValueError as e:
        # res.json() 실패 — 200인데 JSON이 아닌 응답(HTML 에러 페이지 등)
        raise DurunubiAPIError(f"두루누비 API 응답이 JSON 형식이 아닙니다: {e}") from None
    except (KeyError, TypeError) as e:
        # 기대한 키가 없음 — 두루누비 응답 스키마가 예상과 다름
        raise DurunubiAPIError(f"두루누비 API 응답 구조가 예상과 다릅니다: {e}") from None
