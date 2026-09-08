"""코스 주변 관광지 추천 - 비즈니스 로직."""

import contextlib
import json
import logging

from fastapi import HTTPException, status
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.tour import TourAPIError
from app.clients.tour import get_nearby_attractions as fetch_nearby_attractions
from app.config import settings
from app.core.rate_limit import check_rate_limit, record_rate_limit_hit
from app.domain.course.models import Course
from app.domain.course.schemas import NearbyAttractionListResponse, NearbyAttractionResponse
from app.redis import get_redis

logger = logging.getLogger(__name__)

# 카드가 무한정 늘어나지 않도록 상한
_MAX_ATTRACTIONS = 10


def _map_item(item: dict) -> NearbyAttractionResponse | None:
    try:
        return NearbyAttractionResponse(
            content_id=item.get("contentid") or None,
            title=item.get("title") or "",
            address=item.get("addr1") or None,
            image_url=item.get("firstimage") or None,
            latitude=float(item["mapy"]),
            longitude=float(item["mapx"]),
            distance_m=float(item["dist"]) if item.get("dist") not in (None, "") else None,
        )
    except (KeyError, ValueError, TypeError):
        # 좌표가 없거나 형식이 이상한 항목은 조용히 건너뜀
        # ㅡ 카드 하나 이상해도 전체 목록 실패 X
        return None


async def _fetch_points(points: list[tuple[float, float]]) -> list[dict]:
    """여러 좌표(시작/종료점)에 대해 관광지를 조회하고, contentid 기준으로 중복을 제거."""
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for lat, lng in points:
        try:
            items = await fetch_nearby_attractions(
                lat,
                lng,
                radius_m=settings.NEARBY_ATTRACTIONS_RADIUS_M,
                num_of_rows=_MAX_ATTRACTIONS,
            )
        except TourAPIError:
            # 관광지 카드는 부가 기능 - 실패해도 재시도/에러 노출 없이 조용히 건너뜀
            logger.exception("관광공사 API 조회 실패: lat=%s, lng=%s", lat, lng)
            continue
        for item in items:
            content_id = item.get("contentid")
            if content_id is not None and content_id in seen_ids:
                continue
            if content_id is not None:
                seen_ids.add(content_id)
            merged.append(item)
    return merged


async def get_nearby_attractions(
    session: AsyncSession, course_id: int, client_ip: str
) -> NearbyAttractionListResponse:
    """코스 시작/종료점 주변 관광지를 조회. course_id 단위로 캐싱."""
    course = await session.get(Course, course_id)
    if course is None or not course.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )

    if not course.has_verification_coords:
        return NearbyAttractionListResponse(items=[])

    cache_key = f"nearby_attractions:{course_id}"

    # Redis는 최적화 수단 / 장애 시 캐시 없이 진행.
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
    except RedisError:
        logger.exception("Redis 조회 실패, 캐시 없이 진행: key=%s", cache_key)
        redis = None
        cached = None

    if cached:
        try:
            return NearbyAttractionListResponse.model_validate(json.loads(cached))
        except (ValueError, ValidationError):
            # 스키마 변경 이후 과거 캐시 때문에 새 스키마 검증 실패하면
            # ㅡ 500 대신 캐시 미스로 취급해 재계산.
            logger.warning("캐시 스키마 불일치, 재계산: key=%s", cache_key)

    # 캐시 미스(실제로 관광공사 API를 새로 호출하는 경우)인 경우 IP 단위로 rate limit
    # ㅡ 같은 코스를 반복 조회하는 정상 사용/테스트는 캐시 히트라 카운트 X.
    if redis is not None:
        rate_limit_key = f"ratelimit:nearby_attractions_fetch:{client_ip}"
        await check_rate_limit(
            redis, rate_limit_key, settings.NEARBY_ATTRACTIONS_RATE_LIMIT_MAX_REQUESTS
        )
        await record_rate_limit_hit(
            redis, rate_limit_key, settings.NEARBY_ATTRACTIONS_RATE_LIMIT_WINDOW_SECONDS
        )

    points = [(course.start_lat, course.start_lng)]
    if (course.start_lat, course.start_lng) != (course.end_lat, course.end_lng):
        points.append((course.end_lat, course.end_lng))

    raw_items = await _fetch_points(points)
    mapped = [attraction for item in raw_items if (attraction := _map_item(item)) is not None]
    mapped.sort(key=lambda a: a.distance_m if a.distance_m is not None else float("inf"))
    response = NearbyAttractionListResponse(items=mapped[:_MAX_ATTRACTIONS])

    if redis is not None:
        with contextlib.suppress(RedisError):
            await redis.set(
                cache_key,
                response.model_dump_json(),
                ex=settings.NEARBY_ATTRACTIONS_CACHE_TTL_SECONDS,
            )
    return response
