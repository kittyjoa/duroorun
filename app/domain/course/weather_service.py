"""코스 날씨·안전 브리핑 - 비즈니스 로직."""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import kma
from app.clients.gemini import generate_weather_briefing
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

    특보가 없을 때 모달 안에 통계칩으로 보여주는 용도
    ㅡ 이미 받아온 단기예보 데이터에서 계산만 함."""
    temps = [float(item["fcstValue"]) for item in items if item.get("category") == "TMP"]
    if not temps:
        return None, None
    return min(temps), max(temps)


def _get_weather_tip(min_temp: float | None, max_temp: float | None) -> str | None:
    """최저/최고 기온 기준 규칙 기반 팁 한 줄 만들기.

    특보가 없을 때만 프론트가 노출.
    ㅡ AI 호출 없이 서버에서 계산하므로 추가 지연/비용 X
    (특보 있을 때는 이미 특보원문+판단코멘트로 모달이 충분히 풍부)
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


async def _fetch_weather_data(nx: int, ny: int) -> tuple[list[dict] | None, str | None]:
    """단기예보/특보를 asyncio.gather로 독립 호출 - 하나 실패해도 나머지 그대로 진행.

    둘 다 실패했을 때만 503 던지고, "API 실패"/"API는 성공했지만 결과가 없음(예: 특보 없음)"
    구분하기 위해 성공 여부 플래그를 함께 추적.
    """

    async def _forecast() -> tuple[bool, list[dict] | None]:
        try:
            return True, await kma.get_short_term_forecast(nx, ny)
        except KmaAPIError:
            logger.exception("단기예보 조회 실패: nx=%s, ny=%s", nx, ny)
            return False, None

    async def _warning() -> tuple[bool, str | None]:
        try:
            return True, await kma.get_weather_warning()
        except KmaAPIError:
            logger.exception("기상특보 조회 실패")
            return False, None

    (forecast_ok, forecast_items), (warning_ok, warning_raw_text) = await asyncio.gather(
        _forecast(), _warning()
    )
    if not forecast_ok and not warning_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="날씨 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        )
    return forecast_items, warning_raw_text


async def _generate_briefing_text(
    location_hint: str | None, forecast_text: str, warning_raw_text: str | None
) -> str:
    """Gemini로 브리핑 문구를 생성. 실패 시 원본 데이터로 조립한 문구로 폴백."""
    try:
        text = await generate_weather_briefing(location_hint, forecast_text, warning_raw_text)
    except Exception:  # noqa: BLE001
        # google.genai APIError, 타임아웃, 클라이언트 생성 실패(키 누락 등) 모두 포함해
        # 광범위하게 잡는다 - AI 문구 생성이 실패해도 원본 데이터로 최소한의 정보는 보여준다.
        logger.exception("날씨 브리핑 AI 생성 실패")
        text = None

    if text:
        return text.strip()

    if warning_raw_text:
        warning_note = "특보가 발효 중이니 위 원문을 확인해주세요."
    else:
        warning_note = "현재 발효 중인 특보는 없습니다."
    return f"오늘 예보: {forecast_text}\n\n{warning_note}"


async def get_weather_briefing(
    session: AsyncSession, course_id: int, client_ip: str
) -> WeatherBriefingResponse:
    """코스 날씨·안전 브리핑을 조회. 지역(격자) 단위로 캐싱해 AI가 다듬은 최종
    문구까지 저장하므로, 같은 격자에 속한 다른 코스는 캐시를 그대로 재사용."""
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
    cache_key = f"weather_briefing:{nx}:{ny}"

    # Redis는 최적화 수단 / 장애 시 캐시 없이 그냥 진행
    # ㅡ rate_limit.py의 기존 관례(RedisError는 조용히 통과)와 동일.
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
    except RedisError:
        logger.exception("Redis 조회 실패, 캐시 없이 진행: key=%s", cache_key)
        redis = None
        cached = None

    if cached:
        try:
            return WeatherBriefingResponse.model_validate(json.loads(cached))
        except (ValueError, ValidationError):
            # 배포 사이클에서 스키마에 필드가 추가/변경되면,
            # 캐시 미스처럼 취급해 재계산
            # (최대 캐시 TTL 동안만 발생하는 일시적 상황이라 자연 복구됨)
            logger.warning("캐시 스키마 불일치, 재계산: key=%s", cache_key)

    # 캐시 미스(실제로 기상청/Gemini 호출)만 IP 단위로 rate limit
    # ㅡ 같은 코스 반복 조회하는 정상 사용/테스트는 캐시히트라 카운트 X
    if redis is not None:
        rate_limit_key = f"ratelimit:weather_briefing_fetch:{client_ip}"
        await check_rate_limit(
            redis, rate_limit_key, settings.WEATHER_BRIEFING_RATE_LIMIT_MAX_REQUESTS
        )
        await record_rate_limit_hit(
            redis, rate_limit_key, settings.WEATHER_BRIEFING_RATE_LIMIT_WINDOW_SECONDS
        )

    forecast_items, warning_raw_text = await _fetch_weather_data(nx, ny)
    forecast_text = _format_forecast_text(forecast_items or [])
    briefing = await _generate_briefing_text(course.sigun, forecast_text, warning_raw_text)
    min_temp, max_temp = _get_temp_stats(forecast_items or [])

    response = WeatherBriefingResponse(
        warning_raw_text=warning_raw_text,
        briefing=briefing,
        condition=_get_current_condition(forecast_items or []),
        min_temp=min_temp,
        max_temp=max_temp,
        tip=_get_weather_tip(min_temp, max_temp),
        generated_at=datetime.now(UTC),
    )
    if redis is not None:
        with contextlib.suppress(RedisError):
            await redis.set(
                cache_key,
                response.model_dump_json(),
                ex=settings.WEATHER_BRIEFING_CACHE_TTL_SECONDS,
            )
    return response
