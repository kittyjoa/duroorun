"""리뷰 + 이미지 - 비즈니스 로직."""

import asyncio
import contextlib
import logging
import uuid
from functools import lru_cache
from math import floor

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from psycopg.errors import UniqueViolation
from sqlalchemy import case, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gemini import summarize_reviews
from app.config import settings
from app.database import AsyncSessionLocal
from app.domain.course.models import Course, Difficulty
from app.domain.record.models import Record
from app.domain.review.models import Review, ReviewImage, ReviewSummary
from app.domain.review.schemas import (
    ReviewCreateRequest,
    ReviewImageResponse,
    ReviewListResponse,
    ReviewResponse,
    ReviewSummaryResponse,
    ReviewUpdateRequest,
)
from app.domain.user.models import UserRole
from app.redis import get_redis

logger = logging.getLogger(__name__)

# AI 리뷰 요약 생성/재생성 임계값 (FEATURES.md: 3개 도달 시 첫 생성, 이후 5개마다 재생성)
_SUMMARY_FIRST_THRESHOLD = 3
_SUMMARY_REGENERATE_INTERVAL = 5
# 리뷰가 많아져도 프롬프트가 무한정 커지지 않도록 최신 리뷰만 골라서 요약에 사용
_SUMMARY_MAX_REVIEWS = 50
# 짧은 시간에 같은 코스의 재생성이 여러 번 트리거돼도(예: 리뷰 연속 삭제) Gemini는 한 번만
# 호출하도록 잡는 락의 TTL(초). Gemini 호출+저장이 끝나면 즉시 해제하며, 이 값은 프로세스가
# 죽는 등 비정상 종료로 해제가 안 됐을 때를 위한 안전장치일 뿐이다.
_SUMMARY_LOCK_TTL_SECONDS = 60
# 코스 하나에 대해 실제로 요약을 만든(Gemini를 호출한) 직후 이 시간(초) 동안은 다시 시도하지
# 않는다. 리뷰 작성/수정/삭제를 반복해 짧은 시간에 재생성을 계속 트리거하는 것을 엔드포인트별
# rate limit과 무관하게(여러 유저가 나눠서 트리거해도) 코스 단위로 막기 위함.
_SUMMARY_COOLDOWN_SECONDS = 60
# 락 경쟁에서 지거나 Gemini 호출 도중 상태가 바뀌어 저장을 포기했을 때, 그 트리거를
# 그냥 버리지 않고 재시도하는 최대 횟수/간격. 너무 오래 매달리지 않도록 짧게 제한한다.
_SUMMARY_MAX_RETRIES = 3
_SUMMARY_RETRY_DELAY_SECONDS = 3

# 락을 잡은 작업만 자기 락을 해제하도록, 저장된 값이 내가 넣은 토큰과 같을 때만 지운다
# (TTL 만료 후 다른 작업이 잡은 새 락을 실수로 지워버리는 것을 방지 - security.py의
# _ROTATE_REFRESH_SCRIPT와 동일한 compare-and-delete 패턴).
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

# TODO: course 도메인과 공유하는 상수라 course/models.py의 Difficulty 옆으로 옮길 예정
# (course 담당과 협의 필요). 옮긴 뒤 아래 두 줄(_DIFFICULTY_SCORE, _SCORE_TO_DIFFICULTY)을
# 삭제하고 from app.domain.course.models import DIFFICULTY_SCORE로 교체할 것
_DIFFICULTY_SCORE = {
    Difficulty.EASY: 1,
    Difficulty.NORMAL: 2,
    Difficulty.HARD: 3,
}
_SCORE_TO_DIFFICULTY = {score: difficulty for difficulty, score in _DIFFICULTY_SCORE.items()}


def _detect_image_content_type(data: bytes) -> str | None:
    """파일 시그니처(매직바이트)로 실제 이미지 형식을 판별합니다.

    클라이언트가 보낸 Content-Type 헤더는 조작 가능해서 신뢰하지 않고,
    파일 맨 앞 바이트가 jpg/png/gif/webp 중 하나의 고유 패턴과 일치하는지 직접 확인한다.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@lru_cache
def _get_r2_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _validate_content(content: str) -> str:
    """리뷰 내용의 앞뒤 공백을 제거하고 길이가 유효한지 확인한다."""
    content = content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="리뷰 내용을 입력해주세요."
        )
    if len(content) > settings.REVIEW_CONTENT_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"리뷰 내용은 {settings.REVIEW_CONTENT_MAX_LENGTH}자 이하로 입력해주세요.",
        )
    return content


async def create_review(
    session: AsyncSession,
    user_id: int,
    course_id: int,
    body: ReviewCreateRequest,
    background_tasks: BackgroundTasks,
) -> ReviewResponse:
    """리뷰 작성"""
    # 코스 존재 확인
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )

    # 완주 인증 확인 (같은 코스를 여러 번 완주했을 수 있으므로 완주한 기록 존재여부만 확인)
    completed = await session.scalar(
        select(
            exists().where(
                Record.user_id == user_id,
                Record.course_id == course_id,
                Record.is_completed.is_(True),
            )
        )
    )
    if not completed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="완주한 코스에만 리뷰를 작성할 수 있습니다.",
        )

    # 코스당 리뷰 1개 제한 확인
    existing = await session.execute(
        select(Review).where(Review.user_id == user_id, Review.course_id == course_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 해당 코스에 리뷰를 작성했습니다."
        )

    review = Review(
        user_id=user_id,
        course_id=course_id,
        content=_validate_content(body.content),
        difficulty=body.difficulty,
    )
    try:
        session.add(review)
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 해당 코스에 리뷰를 작성했습니다."
        ) from err
    await session.refresh(review)
    # AI 요약 생성/재생성 여부 판단은 응답을 막지 않도록 백그라운드로 실행
    # (동기로 처리하면 Gemini 응답을 기다려야 해서, 하필 3/8/13...번째 리뷰를
    # 작성한 사람만 로딩이 길어지는 문제가 생김 - 그걸 막기 위한 조치)
    background_tasks.add_task(_maybe_update_summary, course_id)
    return ReviewResponse.model_validate(review)


async def _count_reviews(session: AsyncSession, course_id: int) -> int:
    """코스의 전체 리뷰 개수를 센다."""
    result = await session.execute(
        select(func.count()).select_from(Review).where(Review.course_id == course_id)
    )
    return result.scalar_one()


async def _maybe_update_summary(course_id: int) -> None:
    """리뷰 개수가 임계값에 도달했으면 AI 요약을 생성/재생성한다.

    락 경쟁에서 지거나(다른 실행이 이미 처리 중) Gemini 호출 도중 상태가 바뀌어 결과를
    버린 경우, 그 실행이 "알아서 최신 상태를 반영했겠지"라고 그냥 끝내지 않고 잠깐
    기다렸다가 스스로 다시 시도한다 - 그렇지 않으면 마침 그 타이밍에 트리거된 변경
    사항이 통째로 유실되어, 다음 리뷰 변경이 생기기 전까지 요약이 갱신되지 않을 수
    있었다(예: A가 리뷰 3개로 Gemini 호출 중 4번째 리뷰가 등록되면, 4번째가 트리거한
    실행은 락을 못 잡아 종료하고 A는 개수가 바뀐 걸 보고 저장을 포기 — 아무도
    성공하지 못하고 끝나는 경우).
    """
    for attempt in range(_SUMMARY_MAX_RETRIES + 1):
        should_retry = await _attempt_update_summary(course_id)
        if not should_retry:
            return
        if attempt < _SUMMARY_MAX_RETRIES:
            await asyncio.sleep(_SUMMARY_RETRY_DELAY_SECONDS)
    # 재시도를 다 써도 안 되면 포기한다 - 이후 다른 리뷰 변경이 생기면 이 함수가 다시
    # 호출되며 자연스럽게 재시도된다.


async def _attempt_update_summary(course_id: int) -> bool:
    """요약 생성/재생성을 한 번 시도한다.

    반환값이 True면 "누군가와 부딪혀서 시도 자체를 못 했으니 다시 해봐야 한다"는
    뜻이고(락 경쟁 패배, 상태 변경으로 인한 저장 포기), False면 "재시도해도 의미
    없다"는 뜻이다(임계값/주기 미달, Gemini 실패, 정상 저장 완료 등 - Gemini 실패는
    다음 리뷰 작성 시 이 함수가 다시 호출되며 자연스럽게 재시도되므로 여기서 즉시
    재시도하지 않는다).

    요청 처리와 별도로(백그라운드 태스크로) 실행되므로 요청 세션을 재사용하지 않고
    새 세션을 연다.

    Redis 락을 상태를 읽기 전에 먼저 잡는다 - 락 획득 후에 읽으면, 같은 코스에 대해
    거의 동시에 트리거된 다른 실행이 "나도 재생성해야지"라고 각자 상태를 읽어놓고
    나중에야 락 경쟁에서 지는 일이 없다(진 쪽은 상태를 읽기도 전에 바로 빠짐). 락을
    먼저 잡지 않고 나중에 잡으면, 이긴 쪽조차 그 사이 상태가 바뀌어 있으면(다른 리뷰가
    막 추가/삭제됨) 저장 직전 재확인에 걸려 결과를 버리게 되는 경우가 있었다.
    """
    lock_key = f"review_summary_lock:{course_id}"
    cooldown_key = f"review_summary_cooldown:{course_id}"
    lock_token = str(uuid.uuid4())
    try:
        redis = await get_redis()
        # 코스 단위 쿨다운 - 방금 막 요약을 만들었으면, 어느 유저가 어느 API(작성/수정/삭제)로
        # 트리거했든 상관없이 잠깐은 다시 시도하지 않는다. 엔드포인트별 rate limit은 유저 1명의
        # 반복 요청만 막으므로, 작성→삭제를 반복하며 우회하거나 여러 유저가 나눠 트리거하는
        # 경우까지 이 쿨다운으로 막는다.
        #
        # 다만 쿨다운 중이라고 그냥 포기하지는 않는다 - 수정/삭제로 요약이 막 무효화된
        # 직후일 수 있는데, 여기서 포기하면 다음 리뷰 변경이 생기기 전까지 요약이 계속
        # 없는 상태로 남는다. 남은 시간만큼만 기다렸다가 최신 상태로 다시 판단한다.
        cooldown_ttl = await redis.ttl(cooldown_key)
        if cooldown_ttl and cooldown_ttl > 0:
            await asyncio.sleep(cooldown_ttl)
        acquired = await redis.set(lock_key, lock_token, nx=True, ex=_SUMMARY_LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.exception("리뷰 AI 요약 락 획득 실패, 잠금 없이 진행: course_id=%s", course_id)
        redis = None
        acquired = True
    if not acquired:
        # 짧은 시간에 같은 코스의 재생성이 여러 번 트리거될 수 있어(예: 리뷰 연속 삭제),
        # 이미 다른 실행이 처리 중이라는 뜻이다. 그 실행이 내 트리거 사유(예: 방금 등록된
        # 리뷰)까지 반영해 저장한다는 보장이 없으므로, 조용히 끝내지 않고 재시도를 요청한다.
        return True

    try:
        async with AsyncSessionLocal() as session:
            review_count = await _count_reviews(session, course_id)
            if review_count < _SUMMARY_FIRST_THRESHOLD:
                return False

            summary_result = await session.execute(
                select(ReviewSummary).where(ReviewSummary.course_id == course_id)
            )
            summary = summary_result.scalar_one_or_none()
            if summary is not None:
                reviews_since_last = review_count - summary.review_count
                if reviews_since_last < _SUMMARY_REGENERATE_INTERVAL:
                    return False

            contents_result = await session.execute(
                select(Review.review_id, Review.content, Review.updated_at)
                .where(Review.course_id == course_id)
                .order_by(Review.created_at.desc())
                .limit(_SUMMARY_MAX_REVIEWS)
            )
            rows = contents_result.all()
            review_contents = [row.content for row in rows]
            # 요약에 실제로 쓴 리뷰들의 스냅샷(id -> updated_at). 저장 직전에 다시 대조해서
            # Gemini 호출 중 그중 하나라도 수정/삭제됐으면 이미 낡은 결과이므로 버린다.
            # (락을 먼저 잡아도, 이 함수 밖의 실제 리뷰 수정/삭제 요청까지 막는 건 아니므로
            # 여전히 필요한 안전장치)
            snapshot = {row.review_id: row.updated_at for row in rows}

        try:
            summary_text = await summarize_reviews(review_contents)
        except Exception:  # noqa: BLE001
            # Gemini API 실패(APIError)뿐 아니라 클라이언트 생성 실패(ValueError, 키 누락 등)도
            # 포함해 광범위하게 잡는다. 백그라운드 최선 노력 작업이므로 여기서 실패해도
            # 다음 리뷰 작성 시 이 함수가 다시 호출되며 자연스럽게 재시도된다. 원인 파악을
            # 위해 로그는 남긴다.
            logger.exception("리뷰 AI 요약 생성 실패: course_id=%s", course_id)
            return False

        summary_text = summary_text.strip() if summary_text else ""
        if not summary_text:
            logger.warning("Gemini가 빈 요약을 반환해 저장하지 않음: course_id=%s", course_id)
            return False

        async with AsyncSessionLocal() as session:
            # 스냅샷(요약에 쓴 최대 50개)에 없는 리뷰가 그 사이 추가/삭제돼도 review_count가
            # 실제 전체 개수와 어긋날 수 있으므로, 전체 개수도 그대로인지 함께 확인한다.
            if await _count_reviews(session, course_id) != review_count:
                return True

            recheck_result = await session.execute(
                select(Review.review_id, Review.updated_at).where(Review.review_id.in_(snapshot))
            )
            current = {row.review_id: row.updated_at for row in recheck_result.all()}
            if current != snapshot:
                # Gemini 호출 중 요약에 쓴 리뷰가 수정되거나 삭제됨 - 저장하지 않고 버리되,
                # 그 변경 사항이 반영되도록 재시도를 요청한다.
                return True

            summary_result = await session.execute(
                select(ReviewSummary).where(ReviewSummary.course_id == course_id).with_for_update()
            )
            summary = summary_result.scalar_one_or_none()
            if summary is None:
                session.add(
                    ReviewSummary(
                        course_id=course_id, summary=summary_text, review_count=review_count
                    )
                )
            else:
                summary.summary = summary_text
                summary.review_count = review_count

            try:
                await session.commit()
            except IntegrityError as err:
                await session.rollback()
                if not isinstance(err.orig, UniqueViolation):
                    logger.exception(
                        "리뷰 AI 요약 저장 중 예상치 못한 DB 오류: course_id=%s", course_id
                    )
                    raise
                # 위 Redis 락으로 대부분 걸러지지만, 락 자체가 실패했거나 TTL이 지난 경우를
                # 대비한 마지막 안전장치. 코스당 요약은 1개만 허용되므로(UNIQUE 제약) 먼저
                # 저장한 쪽만 성공하고 나머지는 여기서 UNIQUE 제약 위반으로 남는다. 이미
                # 요약이 만들어졌다는 뜻이므로 에러 없이 조용히 무시하고 끝낸다.
                return False

        if redis is not None:
            with contextlib.suppress(Exception):
                await redis.set(cooldown_key, "1", ex=_SUMMARY_COOLDOWN_SECONDS)
        return False
    finally:
        if redis is not None:
            with contextlib.suppress(Exception):
                await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)


async def get_review_summary(session: AsyncSession, course_id: int) -> ReviewSummaryResponse | None:
    """코스의 AI 리뷰 요약 조회 (없으면 None - 코스 상세 응답에서 리뷰 원문만 표시)."""
    result = await session.execute(
        select(ReviewSummary).where(ReviewSummary.course_id == course_id)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        return None
    return ReviewSummaryResponse.model_validate(summary)


async def _invalidate_summary(session: AsyncSession, course_id: int) -> None:
    """코스의 기존 AI 요약을 무효화(삭제 대상으로 표시)한다. 커밋은 호출자가 담당한다 -
    호출자가 처리 중인 다른 변경(리뷰 수정/삭제)과 한 트랜잭션으로 묶어 한 번에 커밋해야,
    "리뷰는 저장됐는데 요약 삭제만 실패해 응답은 에러로 나가는" 반쪽짜리 상태를 막을 수 있다.

    어떤 리뷰가 요약에 쓰였는지 추적하지 않으므로, 리뷰 내용이 바뀌거나(수정) 리뷰가
    없어지면(삭제) 보수적으로 항상 무효화한다 - review_count만 보정하고 텍스트는 남겨두면
    "이미 반영됨(차이 0)"으로 계산되어 옛 요약이 갱신 없이 계속 노출되는 문제가 있었다.
    """
    summary_result = await session.execute(
        select(ReviewSummary).where(ReviewSummary.course_id == course_id)
    )
    summary = summary_result.scalar_one_or_none()
    if summary is not None:
        await session.delete(summary)


async def update_review(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    body: ReviewUpdateRequest,
    background_tasks: BackgroundTasks,
) -> ReviewResponse:
    """리뷰 수정"""
    result = await session.execute(
        select(Review).where(Review.review_id == review_id).with_for_update()
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다."
        )
    if review.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 리뷰만 수정할 수 있습니다."
        )

    new_content = _validate_content(body.content) if body.content is not None else None
    content_changed = new_content is not None and new_content != review.content
    if new_content is not None:
        review.content = new_content
    if body.difficulty is not None:
        review.difficulty = body.difficulty

    course_id = review.course_id
    if content_changed:
        # 리뷰 내용이 바뀌면 기존 AI 요약이 옛 내용을 반영한 채로 남아있게 되므로 무효화한다.
        # 리뷰 수정과 같은 트랜잭션(커밋 1번)으로 묶어서, 수정된 리뷰와 무효화 전 요약이
        # 함께 노출되는 순간이나 "리뷰는 저장됐는데 요약 삭제만 실패" 하는 상황을 막는다.
        await _invalidate_summary(session, course_id)

    await session.commit()
    await session.refresh(review)

    if content_changed:
        # 현재 리뷰 기준으로 재생성을 예약한다 (무효화만 하고 끝내면, 이후 새 리뷰가
        # 작성되지 않는 한 요약이 계속 없는 상태로 남을 수 있음).
        background_tasks.add_task(_maybe_update_summary, course_id)

    return ReviewResponse.model_validate(review)


async def delete_review(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    user_role: UserRole,
    background_tasks: BackgroundTasks,
) -> None:
    """리뷰 삭제 (본인 또는 관리자)"""
    result = await session.execute(
        select(Review).where(Review.review_id == review_id).with_for_update()
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다."
        )
    if review.user_id != user_id and user_role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 리뷰만 삭제할 수 있습니다."
        )
    course_id = review.course_id
    keys = [
        image.image_url.removeprefix(f"{settings.R2_PUBLIC_URL.rstrip('/')}/")
        for image in review.images
    ]
    await session.delete(review)
    # 삭제된 리뷰가 기존 요약에 반영돼 있었을 수 있으므로 무효화한다 (update_review와 동일한
    # 정책). 리뷰 삭제와 같은 트랜잭션(커밋 1번)으로 묶는다.
    await _invalidate_summary(session, course_id)
    await session.commit()

    # R2 정리는 best-effort: DB 삭제는 이미 끝났으므로 실패해도 무시 (고아 파일 방지 목적)
    for key in keys:
        with contextlib.suppress(ClientError, BotoCoreError):
            await asyncio.to_thread(
                _get_r2_client().delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
            )

    remaining = await _count_reviews(session, course_id)
    if remaining >= _SUMMARY_FIRST_THRESHOLD:
        # 무효화됐으니 요약이 없는 상태 - 다음 트리거에서 임계값 게이트 없이 바로 재생성된다
        background_tasks.add_task(_maybe_update_summary, course_id)


async def get_average_difficulty(session: AsyncSession, course_id: int) -> Difficulty | None:
    """코스별 유저 체감 난이도 평균 (탈퇴 유저 리뷰도 통계 목적으로 포함, 리뷰가 없으면 None).
    EASY/NORMAL/HARD를 점수로 평균을 낸 뒤 가장 가까운 등급으로 반올림하여 표시한다.
    """
    # 리뷰가 수천 개인 코스에서도 매번 전체 행을 파이썬으로 끌어오지 않도록 평균을 DB에서 계산
    score_expr = case(
        (Review.difficulty == Difficulty.EASY, _DIFFICULTY_SCORE[Difficulty.EASY]),
        (Review.difficulty == Difficulty.NORMAL, _DIFFICULTY_SCORE[Difficulty.NORMAL]),
        (Review.difficulty == Difficulty.HARD, _DIFFICULTY_SCORE[Difficulty.HARD]),
    )
    result = await session.execute(
        select(func.avg(score_expr), func.count())
        .select_from(Review)
        .where(Review.course_id == course_id)
    )
    avg_score, count = result.one()
    if not count:
        return None
    rounded_score = min(max(floor(float(avg_score) + 0.5), 1), 3)
    return _SCORE_TO_DIFFICULTY[rounded_score]


async def get_reviews(
    session: AsyncSession,
    course_id: int,
    page: int,
    size: int,
) -> ReviewListResponse:
    """코스 리뷰 목록 조회 (탈퇴 유저 리뷰는 노출 제외, 최신순으로 조회)"""
    offset = (page - 1) * size
    total_result = await session.execute(
        select(func.count())
        .select_from(Review)
        .where(Review.course_id == course_id, Review.user_id.is_not(None))
    )
    total = total_result.scalar_one()
    result = await session.execute(
        select(Review)
        .where(Review.course_id == course_id, Review.user_id.is_not(None))
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    reviews = result.scalars().all()
    return ReviewListResponse(
        items=[ReviewResponse.model_validate(r) for r in reviews],
        total=total,
        page=page,
        size=size,
    )


async def upload_review_image(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    file: UploadFile,
) -> ReviewResponse:
    """리뷰 이미지 업로드"""
    # 리뷰 존재 및 본인 확인 (동시 업로드 시 개수 제한이 깨지지 않도록 row lock)
    result = await session.execute(
        select(Review).where(Review.review_id == review_id).with_for_update()
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다."
        )
    if review.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 리뷰에만 이미지를 업로드할 수 있습니다.",
        )

    # 이미지 개수 확인
    count_result = await session.execute(
        select(func.count()).select_from(ReviewImage).where(ReviewImage.review_id == review_id)
    )
    if count_result.scalar_one() >= settings.REVIEW_IMAGE_MAX_COUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"리뷰 이미지는 최대 {settings.REVIEW_IMAGE_MAX_COUNT}개까지 업로드할 수 있습니다."
            ),
        )

    # 파일 크기 확인 (max_bytes+1까지만 읽어서 초과 여부 판단, 전체를 다 읽지 않음)
    max_bytes = settings.REVIEW_IMAGE_MAX_SIZE_MB * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이미지 크기는 {settings.REVIEW_IMAGE_MAX_SIZE_MB}MB 이하여야 합니다.",
        )

    # 파일 형식 확인 (Content-Type 헤더는 클라이언트가 조작 가능하므로 실제 파일 시그니처로 검증)
    detected_content_type = _detect_image_content_type(contents)
    if detected_content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="jpg, png, webp, gif 형식만 업로드할 수 있습니다.",
        )

    # R2 업로드
    ext = _IMAGE_EXTENSIONS[detected_content_type]
    key = f"review-images/{uuid.uuid4()}.{ext}"
    try:
        await asyncio.to_thread(
            _get_r2_client().put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=contents,
            ContentType=detected_content_type,
        )
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="이미지 업로드에 실패했습니다.",
        ) from err

    # DB 저장
    image = ReviewImage(
        review_id=review_id, image_url=f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"
    )
    session.add(image)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        with contextlib.suppress(ClientError, BotoCoreError):
            await asyncio.to_thread(
                _get_r2_client().delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
            )
        raise

    # 이미지 포함 응답 반환
    images_result = await session.execute(
        select(ReviewImage).where(ReviewImage.review_id == review_id)
    )
    images = images_result.scalars().all()
    return ReviewResponse(
        review_id=review.review_id,
        user_id=review.user_id,
        course_id=review.course_id,
        content=review.content,
        difficulty=review.difficulty,
        created_at=review.created_at,
        updated_at=review.updated_at,
        images=[ReviewImageResponse.model_validate(img) for img in images],
    )


async def delete_review_image(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    image_id: int,
) -> None:
    """리뷰 이미지 삭제"""
    # 이미지 존재 확인
    image = await session.get(ReviewImage, image_id)
    if image is None or image.review_id != review_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="이미지를 찾을 수 없습니다."
        )

    # 리뷰 소유자 확인
    review = await session.get(Review, review_id)
    if review is None or review.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인의 리뷰 이미지만 삭제할 수 있습니다."
        )

    # DB 삭제를 먼저 확정한 뒤 R2를 정리한다 (반대 순서면 R2 삭제 후 DB commit 실패 시
    # DB에는 남아있는데 실제 파일은 없는 깨진 상태가 될 수 있음)
    key = image.image_url.removeprefix(f"{settings.R2_PUBLIC_URL.rstrip('/')}/")
    await session.delete(image)
    await session.commit()

    with contextlib.suppress(ClientError, BotoCoreError):
        await asyncio.to_thread(
            _get_r2_client().delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
        )
