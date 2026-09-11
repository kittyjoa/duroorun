"""코스 날씨·안전 브리핑 - 비즈니스 로직."""

import asyncio
import hashlib
import json
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import kma
from app.clients.gemini import generate_forecast_summary, generate_warning_relevance_comment
from app.clients.kma import KmaAPIError
from app.config import settings
from app.core.rate_limit import check_rate_limit, record_rate_limit_hit
from app.domain.course.models import Course
from app.domain.course.schemas import WeatherBriefingResponse
from app.redis import get_redis

logger = logging.getLogger(__name__)

_PTY_LABEL = {"0": None, "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}
_SKY_LABEL = {"1": "맑음", "3": "구름많음", "4": "흐림"}

_HEAT_TIP_THRESHOLD_C = 28.0
_COLD_TIP_THRESHOLD_C = 5.0
_SWING_TIP_THRESHOLD_C = 10.0

# 기상특보 원문은 시군/코스와 무관한 전역(강원 전체) 값이라 캐시 키 하나.
_WARNING_RAW_CACHE_KEY = "weather_warning_raw"

# (코드리뷰: review summary와 같은 redis 락 추가)
# 새 특보가 뜬 직후 같은 시군의 코스를 여러 명이 동시에 여는 경우 대비:
# ㅡ 락을 먼저 잡은 요청만 실제로 호출, 나머지는 결과가 캐시에 올라오길 기다렸다 재사용.
# ㅡ TTL은 Gemini 타임아웃(GEMINI_TIMEOUT_SECONDS)보다 넉넉하게 잡아,
# 정상 처리 중에 락이 먼저 만료돼 다른 요청이 끼어드는 일이 없도록.
_WARNING_COMMENT_LOCK_TTL_SECONDS = 40
# 락을 못 잡은 요청이 결과를 기다리는 최대 시간
# ㅡ 이보다 오래 걸리면 기다리던 요청도 직접 계산,
# 사용자를 무한정 기다리게 하는 것보다 아주 드물게 중복 호출되는 편이 나음.
_WARNING_COMMENT_LOCK_WAIT_SECONDS = 5.0
_WARNING_COMMENT_LOCK_POLL_INTERVAL_SECONDS = 0.2

# 락을 잡은 요청만 자기 락을 해제하도록,
# 저장된 값이 내가 넣은 토큰과 같을 때만 지운다
# (review 도메인 방식과 동일 - 비교 후 지우기).
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class _ForecastBriefing(BaseModel):
    """격자(nx, ny) 단위로 캐싱되는 예보 요약
    ㅡ 단기예보 조회 성공 여부(ok)도 함께 저장,
    캐시 히트로 재사용할 때도 전체 실패 여부(503 판단)를 알 수 있게."""

    ok: bool
    paragraph: str
    condition: str | None
    min_temp: float | None
    max_temp: float | None
    tip: str | None


class _WarningRaw(BaseModel):
    """전역(강원 전체) 특보 원문 - 시군/코스와 무관하게 캐시 키 하나."""

    ok: bool
    text: str | None


def _get_location_hint(course: Course) -> str | None:
    """특보 관련성 코멘트/캐시 키에 쓸 지역 힌트.

    ㅡ 커스텀코스는 시작/종료 좌표 지역 다를 수 있어서 둘 다 전달."""
    if course.sigun and course.end_sigun and course.sigun != course.end_sigun:
        return f"{course.sigun}, {course.end_sigun}"
    return course.sigun or course.end_sigun


def _get_representative_point(course: Course) -> tuple[float, float] | None:
    """완주 인증 기준점(start/end)의 중간점을 대표 좌표로 사용.

    ㅡ 커스텀 코스가 시군 2개에 걸칠 수 있어 중간점을 씀. 좌표가 없으면 None."""
    if not course.has_verification_coords:
        return None
    return (
        (course.start_lat + course.end_lat) / 2,
        (course.start_lng + course.end_lng) / 2,
    )


def _format_forecast_text(items: list[dict]) -> str:
    """단기예보 원본 항목들을 사람이 읽기 좋은 텍스트로 정리 (Gemini 프롬프트 입력용)."""
    if not items:
        return "예보 데이터 없음"

    by_time: dict[str, dict[str, str]] = {}
    for item in items:
        by_time.setdefault(item["fcstTime"], {})[item["category"]] = item["fcstValue"]

    lines = []
    for time_str in sorted(by_time):
        values = by_time[time_str]
        parts = []
        if "TMP" in values:
            parts.append(f"기온 {values['TMP']}도")
        precipitation = _PTY_LABEL.get(values.get("PTY", "0"))
        if precipitation:
            parts.append(precipitation)
        if "POP" in values:
            parts.append(f"강수확률 {values['POP']}%")
        sky = _SKY_LABEL.get(values.get("SKY", ""))
        if sky:
            parts.append(sky)
        if parts:
            lines.append(f"{time_str[:2]}시: {', '.join(parts)}")
    return "\n".join(lines) if lines else "예보 데이터 없음"


def _get_current_condition(items: list[dict]) -> str | None:
    """예보 항목 중 현재 시각과 가장 가까운 슬롯의 하늘상태/강수형태를 하나만 뽑기.

    ㅡ 프론트가 날씨 아이콘/애니메이션을 고르는 용도
    ㅡ 날씨 아이콘은 버튼을 누른 시간과 가장 가까운 날씨 표시용
    ㅡ AI를 거치기 전 원본 예보 데이터에서 직접 뽑음
    ㅡ PTY(강수형태)가 있으면 SKY(하늘상태)보다 우선: 눈/비 표시가 더 중요."""
    if not items:
        return None
    by_time: dict[str, dict[str, str]] = {}
    for item in items:
        by_time.setdefault(item["fcstTime"], {})[item["category"]] = item["fcstValue"]
    if not by_time:
        return None

    now = datetime.now(kma.KST)
    # ㅡ 하루 안에서 '버튼을 누른 지금과 가장 가까운 시각 하나' 고르는 함수
    # 이전) 시각 숫자 차이 방식 고정: 밤 11시대에 누를때 문제 발생
    # 정해진 시간마다 날씨 예보 내려오는데, 밤 11시 발표는 다음날 날씨 내용
    # ㅡ 하루가 오늘 날짜면: 시각 숫자 차이로 비교
    # ㅡ 하루가 오늘이 아니면(밤 11:10~자정): 제일 이른 시각
    forecast_date = items[0].get("fcstDate")
    if forecast_date == now.strftime("%Y%m%d"):
        # 예보 시각은 항상 정시(MM=00)라 HHMM 숫자 차이가 실제 시간 차이와 비례
        now_hm = int(now.strftime("%H%M"))
        nearest_time = min(by_time, key=lambda t: abs(int(t) - now_hm))
    else:
        nearest_time = min(by_time)
    values = by_time[nearest_time]

    precipitation = _PTY_LABEL.get(values.get("PTY", "0"))
    if precipitation:
        return precipitation
    return _SKY_LABEL.get(values.get("SKY", ""))


def _get_temp_stats(items: list[dict]) -> tuple[float | None, float | None]:
    """예보 항목에서 그날 최저/최고 기온을 뽑기.

    모달 안에 통계칩으로 항상 보여주는 용도
    ㅡ 이미 받아온 단기예보 데이터에서 계산만."""
    temps = [float(item["fcstValue"]) for item in items if item.get("category") == "TMP"]
    if not temps:
        return None, None
    return min(temps), max(temps)


def _get_weather_tip(min_temp: float | None, max_temp: float | None) -> str | None:
    """최저/최고 기온 기준 규칙 기반 팁 한 줄 만들기.

    특보 유무와 무관하게 프론트가 항상 노출.
    ㅡ AI 호출 없이 서버에서 계산하므로 추가 지연/비용 X
    """
    if min_temp is None or max_temp is None:
        return None
    if max_temp >= _HEAT_TIP_THRESHOLD_C:
        return "더위 조심! 수분 보충하고 자외선 차단제도 챙기세요"
    if min_temp <= _COLD_TIP_THRESHOLD_C:
        return "쌀쌀해요, 겉옷 챙기세요"
    if max_temp - min_temp >= _SWING_TIP_THRESHOLD_C:
        return "일교차가 크니 얇은 겉옷 하나 챙기면 좋아요"
    return "쾌적한 날씨예요, 즐거운 러닝 되세요!"


_CacheModel = TypeVar("_CacheModel", bound=BaseModel)
_T = TypeVar("_T")


async def _immediate(value: _T) -> _T:
    """1. async def: 호출해도 함수 바로 실행 X,
    나중에 실행할 준비가 된 껍데기 '코루틴 객체'만 생김
    2. await 붙여야 '지금 진짜 실행해서 결과 받아와'
    3. asyncio.gather에 다같이 넘기고 싶어서
    이 함수 이용해서 코루틴 껍데기 씌워주는것."""
    return value


async def _read_cache(
    redis: Redis | None, key: str, model: type[_CacheModel]
) -> _CacheModel | None:
    """1. 캐시 조회 (redis get)
    2. rate limit 체크
    3. 캐시 미스만 계산+저장 (실제 api 호출)"""
    if redis is None:
        return None
    try:
        cached = await redis.get(key)
    except RedisError:
        logger.exception("Redis 조회 실패, 캐시 없이 진행: key=%s", key)
        return None
    if not cached:
        return None
    try:
        return model.model_validate(json.loads(cached))
    except (ValueError, ValidationError):
        # 배포 사이클에서 스키마에 필드가 추가/변경되면, 캐시 미스처럼 취급해 재계산
        # (최대 캐시 TTL 동안만 발생하는 일시적 상황이라 자연 복구됨)
        logger.warning("캐시 스키마 불일치, 재계산: key=%s", key)
        return None


async def _compute_forecast_briefing(redis: Redis | None, nx: int, ny: int) -> _ForecastBriefing:
    """단기예보를 새로 조회해 예보 요약 문단 + 통계를 만들고, 격자 단위로 캐싱.

    단기예보 갱신 주기(3시간)에 맞춰 정상 결과는 3시간,
    조회 실패 결과는 짧게(5분) 캐싱해 장애 복구된 뒤에도 오래 남지 않게.
    """
    try:
        forecast_ok, forecast_items = True, await kma.get_short_term_forecast(nx, ny)
    except KmaAPIError:
        logger.exception("단기예보 조회 실패: nx=%s, ny=%s", nx, ny)
        forecast_ok, forecast_items = False, None

    forecast_text = _format_forecast_text(forecast_items or [])
    try:
        paragraph = await generate_forecast_summary(forecast_text)
    except Exception:  # noqa: BLE001
        # google.genai APIError, 타임아웃, 클라이언트 생성 실패(키 누락 등) 모두 포함해
        # 광범위하게 잡는다 - AI 문구 생성이 실패해도 원본 데이터로 최소한의 정보는 보여준다.
        logger.exception("날씨 브리핑 AI 생성 실패(예보 요약)")
        paragraph = None
    if not paragraph:
        paragraph = f"오늘 예보: {forecast_text}"

    min_temp, max_temp = _get_temp_stats(forecast_items or [])
    briefing = _ForecastBriefing(
        ok=forecast_ok,
        paragraph=paragraph.strip(),
        condition=_get_current_condition(forecast_items or []),
        min_temp=min_temp,
        max_temp=max_temp,
        tip=_get_weather_tip(min_temp, max_temp),
    )
    if redis is not None:
        ttl = (
            settings.WEATHER_BRIEFING_CACHE_TTL_SECONDS
            if forecast_ok
            else settings.WEATHER_BRIEFING_PARTIAL_FAILURE_CACHE_TTL_SECONDS
        )
        with suppress(RedisError):
            await redis.set(
                f"weather_forecast_briefing:{nx}:{ny}", briefing.model_dump_json(), ex=ttl
            )
    return briefing


async def _compute_warning_raw(redis: Redis | None) -> _WarningRaw:
    """기상특보를 새로 조회해 전역 캐시에 저장 (성공/실패 공통으로 짧은 TTL).

    특보는 예보와 달리 발표 시점을 예측할 수 없는 긴급 정보,
    ㅡ 훨씬 짧은 TTL을 쓰고, 시군/코스와 무관하게 캐시 엔트리를 하나만.
    """
    try:
        warning_ok, warning_raw_text = True, await kma.get_weather_warning()
    except KmaAPIError:
        logger.exception("기상특보 조회 실패")
        warning_ok, warning_raw_text = False, None

    warning = _WarningRaw(ok=warning_ok, text=warning_raw_text)
    if redis is not None:
        with suppress(RedisError):
            await redis.set(
                _WARNING_RAW_CACHE_KEY,
                warning.model_dump_json(),
                ex=settings.WEATHER_WARNING_RAW_CACHE_TTL_SECONDS,
            )
    return warning


_WARNING_COMMENT_FALLBACK = "특보가 발효 중이니 위 원문을 확인해주세요."


async def _redis_get(redis: Redis, key: str) -> str | None:
    try:
        return await redis.get(key)
    except RedisError:
        logger.exception("Redis 조회 실패: key=%s", key)
        return None


async def _generate_warning_comment_text(location_hint: str | None, warning_raw_text: str) -> str:
    try:
        comment = await generate_warning_relevance_comment(location_hint, warning_raw_text)
    except Exception:  # noqa: BLE001
        logger.exception("날씨 브리핑 AI 생성 실패(특보 관련성 코멘트)")
        comment = None
    return (comment or _WARNING_COMMENT_FALLBACK).strip()


async def _get_warning_comment(
    redis: Redis | None, location_hint: str | None, warning_raw_text: str
) -> str:
    """특보-코스 지역 관련성 코멘트를 (시군, 특보 원문 해시) 단위 캐시에서 읽거나 새로 생성.

    캐시 키에 특보 원문 해시를 넣어둬서, 특보 내용이 바뀌면 TTL을 기다리지 않고도
    바로 다른 캐시 엔트리를 참조(자동 무효화).
    ㅡ TTL은 해제된 지 오래된 특보 캐시가 Redis에 무한정 남지 않게 하는 안전장치.

    새 특보 직후 같은 (시군, 특보) 조합에 요청이 몰려도 Gemini를 한 번만 부르도록
    락을 건다 - 락을 못 잡은 요청은 결과가 캐시에 올라올 때까지 기다렸다 재사용.
    """
    if redis is None:
        return await _generate_warning_comment_text(location_hint, warning_raw_text)

    warning_hash = hashlib.sha256(warning_raw_text.encode()).hexdigest()[:16]
    cache_key = f"weather_warning_comment:{location_hint or ''}:{warning_hash}"

    cached = await _redis_get(redis, cache_key)
    if cached:
        return cached

    lock_key = f"{cache_key}:lock"
    lock_token = str(uuid.uuid4())
    try:
        acquired = await redis.set(
            lock_key, lock_token, nx=True, ex=_WARNING_COMMENT_LOCK_TTL_SECONDS
        )
    except RedisError:
        logger.exception("Redis 락 획득 실패, 락 없이 진행: key=%s", lock_key)
        acquired = None

    if not acquired:
        # 다른 요청이 이미 같은 코멘트를 생성 중 - 결과가 캐시에 올라올 때까지 기다린다.
        waited = 0.0
        while waited < _WARNING_COMMENT_LOCK_WAIT_SECONDS:
            await asyncio.sleep(_WARNING_COMMENT_LOCK_POLL_INTERVAL_SECONDS)
            waited += _WARNING_COMMENT_LOCK_POLL_INTERVAL_SECONDS
            cached = await _redis_get(redis, cache_key)
            if cached:
                return cached
        # 끝까지 안 올라오면 직접 계산
        # - 사용자를 무한정 기다리게 하는 것보단 드물게 중복 호출되는 편이 낫다.
        return await _generate_warning_comment_text(location_hint, warning_raw_text)

    try:
        comment = await _generate_warning_comment_text(location_hint, warning_raw_text)
        with suppress(RedisError):
            await redis.set(
                cache_key, comment, ex=settings.WEATHER_WARNING_COMMENT_CACHE_TTL_SECONDS
            )
        return comment
    finally:
        with suppress(RedisError):
            await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)


async def get_weather_briefing(
    session: AsyncSession, course_id: int, client_ip: str
) -> WeatherBriefingResponse:
    """코스 날씨·안전 브리핑을 조회.

    예보 요약(격자 단위, ~3시간 캐싱)과 특보(전역 1개, ~5분 캐싱)를
    서로 다른 TTL로 독립적으로 캐싱한 뒤 조합.
    """
    course = await session.get(Course, course_id)
    if course is None or not course.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )

    point = _get_representative_point(course)
    if point is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="코스 좌표 정보가 없어 날씨 브리핑을 제공할 수 없습니다.",
        )
    nx, ny = kma.latlng_to_grid(*point)
    forecast_cache_key = f"weather_forecast_briefing:{nx}:{ny}"

    # Redis는 최적화 수단 / 장애 시 캐시 없이 그냥 진행
    # ㅡ rate_limit.py의 기존 관례(RedisError는 조용히 통과)와 동일.
    try:
        redis = await get_redis()
    except RedisError:
        logger.exception("Redis 연결 실패, 캐시 없이 진행")
        redis = None

    forecast_cached = await _read_cache(redis, forecast_cache_key, _ForecastBriefing)
    warning_cached = await _read_cache(redis, _WARNING_RAW_CACHE_KEY, _WarningRaw)

    # 예보/특보 중 하나라도 캐시 미스면(실제로 기상청 API 새로 호출) IP 단위로 rate limit
    # ㅡ 둘 다 캐시 히트인, 같은 코스 반복 조회하는 정상 사용/테스트는 카운트 X.
    # (특보-관련성 Gemini 호출은 공공데이터포털 쿼터와 무관해 대상에서 제외)
    if redis is not None and (forecast_cached is None or warning_cached is None):
        rate_limit_key = f"ratelimit:weather_briefing_fetch:{client_ip}"
        await check_rate_limit(
            redis, rate_limit_key, settings.WEATHER_BRIEFING_RATE_LIMIT_MAX_REQUESTS
        )
        await record_rate_limit_hit(
            redis, rate_limit_key, settings.WEATHER_BRIEFING_RATE_LIMIT_WINDOW_SECONDS
        )

    # 특보 원문은 Gemini 없이 캐시/KMA 조회만 하면 되므로 먼저 확정.
    # "예보 요약 생성"과 "특보 관련성 코멘트 생성" Gemini 호출 2개를
    # 순차적으로 기다리지 않고 동시에 실행 가능하도록.
    warning_raw = warning_cached or await _compute_warning_raw(redis)

    if not warning_raw.ok:
        warning_paragraph_coro = _immediate("특보 정보를 확인하지 못했습니다.")
    elif warning_raw.text:
        warning_paragraph_coro = _get_warning_comment(
            redis, _get_location_hint(course), warning_raw.text
        )
    else:
        warning_paragraph_coro = _immediate("현재 발효 중인 특보는 없습니다.")

    forecast_briefing, warning_paragraph = await asyncio.gather(
        _immediate(forecast_cached)
        if forecast_cached is not None
        else _compute_forecast_briefing(redis, nx, ny),
        warning_paragraph_coro,
    )

    if not forecast_briefing.ok and not warning_raw.ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="날씨 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    return WeatherBriefingResponse(
        warning_raw_text=warning_raw.text,
        briefing=forecast_briefing.paragraph,
        warning_comment=warning_paragraph,
        condition=forecast_briefing.condition,
        min_temp=forecast_briefing.min_temp,
        max_temp=forecast_briefing.max_temp,
        tip=forecast_briefing.tip,
        generated_at=datetime.now(UTC),
    )
