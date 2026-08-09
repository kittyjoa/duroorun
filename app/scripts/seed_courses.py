"""두루누비 코스 시드 스크립트 (GPX 파싱하여 시작/종료 좌표 저장)."""
# mvp 단계: 강원도 중심 해파랑길 코스만 필터 걸어서 가져옴
# 추후 v2 고도화된다면: 두루누비 전체 코스 가져와서 활용하는 서비스

import asyncio
import logging
import selectors
import sys
from pathlib import Path

import gpxpy
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.durunubi import DurunubiAPIError, fetch_course_list
from app.database import AsyncSessionLocal
from app.domain.course.models import Course, CourseType, Difficulty

# Course의 관계/FK가 참조하는 다른 도메인 모델들 — 직접 안 써도 import해야
# SQLAlchemy가 courses.created_by(→users), course_facility(→facilities) 매핑을 해석할 수 있음
from app.domain.facility import models as _facility_models  # noqa: F401
from app.domain.user import models as _user_models  # noqa: F401
from app.scripts.manual_courses import MANUAL_COURSES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 500  # 페이지네이션 응답이 이상해도 무한루프에 빠지지 않도록 상한
_GPX_TIMEOUT = 10.0
_TRAIL_NAME = "해파랑길"  # 두루누비 전체 코스 중 우리 서비스가 다루는 노선만 서버단에서 필터링
# 두루누비 API에 지역 파라미터가 없어 sigun 필터 사용
_TARGET_REGION = "강원"

_LEVEL_TO_DIFFICULTY = {"1": Difficulty.EASY, "2": Difficulty.NORMAL, "3": Difficulty.HARD}


def _is_target_region(item: dict) -> bool:
    """API 응답 item이 강원도 코스인지 확인 (sigun 필드 접두어 기준)."""
    return (item.get("sigun") or "").startswith(_TARGET_REGION)


def _parse_estimated_time(raw: str | None) -> int | None:
    """crsTotlRqrmHour를 분 단위 정수로 변환.

    ㅡ 필드명은 "Hour"지만 실측 API 응답값은 이미 분 단위
    ㅡ 소수 문자열이 와도 int() 캐스팅 실패로 코스 전체가 스킵되지 않도록
       float 경유 후 반올림.
    """
    if not raw:
        return None
    return round(float(raw))


def _map_item(item: dict) -> dict:
    """두루누비 API 응답 원본 dict -매핑-> courses 테이블 컬럼 dict"""
    return {
        "course_type": CourseType.DRNB,
        "dmb_id": item["crsIdx"],
        "course_name": item["crsKorNm"],
        "distance": float(item["crsDstnc"]) if item.get("crsDstnc") else None,
        "difficulty": _LEVEL_TO_DIFFICULTY.get(item.get("crsLevel")),
        "estimated_time": _parse_estimated_time(item.get("crsTotlRqrmHour")),
        "course_description": item.get("crsContents") or None,
        "sigun": item.get("sigun") or None,
        "brd_div": item.get("brdDiv") or None,
    }


async def _upsert_courses(session: AsyncSession, items: list[dict]) -> None:
    """한 페이지 분량의 코스를 dmb_id 기준으로 upsert(update + insert)."""
    rows = []
    for item in items:
        try:
            rows.append(_map_item(item))
        except (KeyError, ValueError, TypeError):
            logger.warning("코스 필드 매핑 실패, 스킵: crsIdx=%s", item.get("crsIdx"))
    if not rows:
        return

    # dmb_id 중복 있으면 나중값 덮어쓴거 1개만 남기고 INSERT문에 넘기기
    rows = list({row["dmb_id"]: row for row in rows}.values())

    stmt = pg_insert(Course).values(rows)
    update_cols = {
        col: stmt.excluded[col]
        for col in (
            "course_name", "distance", "difficulty", "estimated_time",
            "course_description", "sigun", "brd_div",
        )
    }
    # 이번에 API 응답에 다시 나타난 코스는 재활성화 (예전에 비활성화됐던 경우 대비)
    update_cols["is_active"] = True
    stmt = stmt.on_conflict_do_update(index_elements=["dmb_id"], set_=update_cols)
    await session.execute(stmt)
    await session.commit()


async def _deactivate_missing_courses(session: AsyncSession, seen_dmb_ids: set[str]) -> None:
    """이번 실행에서 API 응답에 없었던 기존 DRNB 코스를 비활성화.

    ㅡ 두루누비 목록에서 실제로 빠진 코스(폐쇄/통합 등)가 계속 활성 상태로 남는 것 방지.
    ㅡ 이 시드가 관리하는 범위(해파랑길 + 강원)로 대상을 제한
    ㅡ seen_dmb_ids가 비어있으면(이번 실행에서 아무것도 못 받음) 스킵
       → 일시적 API 이상으로 전체 코스가 비활성화되는 것 방지.
    """
    if not seen_dmb_ids:
        return
    result = await session.execute(
        select(Course).where(
            Course.course_type == CourseType.DRNB,
            Course.course_name.contains(_TRAIL_NAME),
            Course.sigun.startswith(_TARGET_REGION),
            Course.is_active.is_(True),
            Course.dmb_id.is_not(None),
            Course.dmb_id.not_in(seen_dmb_ids),
        )
    )
    missing = result.scalars().all()
    if not missing:
        return
    for course in missing:
        course.is_active = False
    await session.commit()
    logger.warning(
        "API 응답에서 빠진 코스 %d건 비활성화: %s", len(missing), [c.dmb_id for c in missing]
    )


async def _fetch_all_courses() -> tuple[list[dict], dict[str, str], bool]:
    """두루누비파일 fetch_course_list를 페이지 끝까지 반복 호출
    ㅡ 강원도 코스만 걸러서 전체 코스와 dmb_id -> gpxpath 매핑을 반환.
    ㅡ total_count는 crs_kor_nm 필터 기준(전체 해파랑길) 전체 개수라,
       강원 필터링 후 개수와는 별도로 추적.
    ㅡ 반환값 세 번째 요소(complete): total_count까지 다 받았다고 확인됐을때만 True,
       페이지 중간에 빈 응답을 받거나 페이지 상한에 걸리면 False"""
    all_items: list[dict] = []
    gpx_urls: dict[str, str] = {}
    page_no = 1
    fetched_count = 0
    complete = False
    while page_no <= _MAX_PAGES:
        items, total_count = await fetch_course_list(
            page_no, num_of_rows=_PAGE_SIZE, crs_kor_nm=_TRAIL_NAME
        )
        if not items:
            logger.warning(
                "페이지 %d에서 빈 응답을 받아 수집을 중단합니다 (누적 %d/%d건).",
                page_no, fetched_count, total_count,
            )
            break
        fetched_count += len(items)
        items = [item for item in items if _is_target_region(item)]
        all_items.extend(items)
        gpx_urls.update(
            {item["crsIdx"]: item["gpxpath"] for item in items if item.get("gpxpath")}
        )
        logger.info(
            "코스 목록 수집 %d/%d건 (강원 %d건)", fetched_count, total_count, len(all_items)
        )
        if fetched_count >= total_count:
            complete = True
            break
        page_no += 1
    else:
        logger.warning("페이지 상한(%d)에 도달해 목록 수집을 중단했습니다.", _MAX_PAGES)
    return all_items, gpx_urls, complete


# 두루누비 강원도 해파랑길 코스들 중 6개가 계속 누락되어 생긴 병합 함수
def _merge_manual_courses(
    all_items: list[dict], gpx_sources: dict[str, str | Path]
) -> tuple[list[dict], dict[str, str | Path]]:
    """API 응답에 없는 코스만 MANUAL_COURSES로 보충. API에 있으면 항상 API 데이터가 우선.

    ㅡ API가 나중에 이 코스를 정상 반환하기 시작하면, seen_ids에 이미 포함되므로
      여기서 자동으로 걸러져서 수동 데이터는 안 쓰임.
    ㅡ 인자를 대체하지 않고, return 값으로만 이루어진 결과를 새로 준다?
    """
    seen_ids = {item["crsIdx"] for item in all_items}
    missing_manual = [m for m in MANUAL_COURSES if m["crsIdx"] not in seen_ids]
    if not missing_manual:
        return all_items, gpx_sources
    logger.info(
        "API 미제공 코스 %d건을 수동 데이터로 보충: %s",
        len(missing_manual), [m["crsIdx"] for m in missing_manual],
    )
    merged_sources = {
        **gpx_sources,
        **{m["crsIdx"]: m["gpx_path"] for m in missing_manual if m.get("gpx_path")},
    }
    return all_items + missing_manual, merged_sources


def _extract_start_end(gpx_text: str) -> tuple[float, float, float, float] | None:
    """GPX 텍스트에서 첫/마지막 좌표를 추출. gpx가 track인지 route인지 아직 모름
       ㅡ 제3의구조거나 아예 없으면 좌표 추출 다시 생각해봐야함"""
    gpx = gpxpy.parse(gpx_text)
    points = [pt for track in gpx.tracks for seg in track.segments for pt in seg.points]
    if not points:
        points = [pt for route in gpx.routes for pt in route.points]
    if not points:
        return None
    first, last = points[0], points[-1]
    return first.latitude, first.longitude, last.latitude, last.longitude


async def _try_fetch_coords(
    client: httpx.AsyncClient, gpx_source: str | Path
) -> tuple[float, float, float, float] | None:
    """gpx_source(API gpxpath URL 문자열 또는 수동 파일 Path)를 읽어 좌표 반환.

    ㅡ 다운로드/파일읽기/파싱 어느 쪽이 실패해도 None.
    """
    try:
        if isinstance(gpx_source, Path):
            gpx_text = gpx_source.read_text(encoding="utf-8")
        else:
            res = await client.get(gpx_source)
            res.raise_for_status()
            gpx_text = res.text
        return _extract_start_end(gpx_text)
    except (httpx.HTTPError, OSError):
        return None
    except Exception:  # noqa: BLE001 — GPX 포맷이 코스마다 달라 파싱실패원인 특정 어려움
        return None


async def _sync_coordinates(session: AsyncSession, gpx_sources: dict[str, str | Path]) -> None:
    """gpx_sources에 있는 모든 DRNB 코스의 GPX를 매번 다시 읽어 좌표를 최신화한다.

    ㅡ 두루누비 원본 경로가 바뀌어도(완주 인증 기준점) 다음 실행 때 반영되도록 매번 재조회.
    ㅡ GPX 다운로드/파싱 실패 시 기존 좌표를 지우지 않고 그대로 둠 (일시적 네트워크 오류 대비).
    ㅡ 값이 실제로 안 바뀐 코스는 대입/커밋을 건너뛰어 불필요한 updated_at 갱신 방지.
    """
    result = await session.execute(
        select(Course).where(
            Course.course_type == CourseType.DRNB,
            Course.dmb_id.in_(gpx_sources.keys()),
        )
    )
    courses = result.scalars().all()
    if not courses:
        return

    failed: list[str] = []
    # 코스 단위로 커밋 — 한 코스의 GPX 다운로드/파싱이 나중에 실패해도
    # 그 앞에서 이미 성공한 코스들의 좌표 저장까지 롤백되지 않게
    async with httpx.AsyncClient(timeout=_GPX_TIMEOUT) as client:
        for course in courses:
            gpx_source = gpx_sources.get(course.dmb_id)
            coords = await _try_fetch_coords(client, gpx_source) if gpx_source else None
            if coords is None:
                failed.append(course.dmb_id)
                continue
            current = (course.start_lat, course.start_lng, course.end_lat, course.end_lng)
            if current != coords:
                course.start_lat, course.start_lng, course.end_lat, course.end_lng = coords
                await session.commit()

    if failed:
        logger.warning(
            "좌표 추출 실패 코스 %d건 (완주 인증 기준점 없이 시드됨): %s", len(failed), failed
        )


async def seed_courses() -> None:
    async with AsyncSessionLocal() as session:
        try:
            all_items, gpx_sources, complete = await _fetch_all_courses()
        except DurunubiAPIError as e:
            logger.error("두루누비 API 호출 실패, 시드를 중단합니다: %s", e)
            return

        all_items, gpx_sources = _merge_manual_courses(all_items, gpx_sources)

        for i in range(0, len(all_items), _PAGE_SIZE):
            await _upsert_courses(session, all_items[i : i + _PAGE_SIZE])
        logger.info("코스 upsert 완료: %d건", len(all_items))

        if complete:
            seen_dmb_ids = {item["crsIdx"] for item in all_items}
            await _deactivate_missing_courses(session, seen_dmb_ids)
        else:
            logger.warning(
                "코스 목록을 끝까지 수집하지 못해 이번 실행은 비활성화 처리를 건너뜁니다."
            )

        await _sync_coordinates(session, gpx_sources)
        logger.info("시드 완료")


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg(async)가 Windows 기본 이벤트 루프(ProactorEventLoop)를 지원하지 않음
        asyncio.run(
            seed_courses(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(seed_courses())
