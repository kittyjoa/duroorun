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
from sqlalchemy import exists, func, select
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

logger = logging.getLogger(__name__)

# AI 리뷰 요약 생성/재생성 임계값 (FEATURES.md: 3개 도달 시 첫 생성, 이후 5개마다 재생성)
_SUMMARY_FIRST_THRESHOLD = 3
_SUMMARY_REGENERATE_INTERVAL = 5
# 리뷰가 많아져도 프롬프트가 무한정 커지지 않도록 최신 리뷰만 골라서 요약에 사용
_SUMMARY_MAX_REVIEWS = 50

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
    """리뷰 내용의 앞뒤 공백을 제거하고 빈 값이 아닌지 확인한다."""
    content = content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="리뷰 내용을 입력해주세요."
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
    result = await session.execute(
        select(func.count()).select_from(Review).where(Review.course_id == course_id)
    )
    return result.scalar_one()


async def _maybe_update_summary(course_id: int) -> None:
    """리뷰 개수가 임계값에 도달했으면 AI 요약을 생성/재생성한다.

    요청 처리와 별도로(백그라운드 태스크로) 실행되므로 요청 세션을 재사용하지 않고
    새 세션을 연다. 판단에 필요한 데이터만 먼저 읽고 세션을 닫은 뒤 Gemini를 호출한다
    — 응답이 느려질 때 DB 락/트랜잭션/커넥션을 그만큼 오래 붙들고 있지 않기 위함.
    Gemini 호출이 실패해도 예외를 삼키고 조용히 종료한다 — 다음 리뷰가 작성될 때
    이 함수가 다시 호출되면서 자연스럽게 재시도된다.
    """
    async with AsyncSessionLocal() as session:
        review_count = await _count_reviews(session, course_id)
        if review_count < _SUMMARY_FIRST_THRESHOLD:
            return

        summary_result = await session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == course_id)
        )
        summary = summary_result.scalar_one_or_none()
        if summary is not None:
            reviews_since_last = review_count - summary.review_count
            if reviews_since_last < _SUMMARY_REGENERATE_INTERVAL:
                return

        contents_result = await session.execute(
            select(Review.content)
            .where(Review.course_id == course_id)
            .order_by(Review.created_at.desc())
            .limit(_SUMMARY_MAX_REVIEWS)
        )
        review_contents = contents_result.scalars().all()

    try:
        summary_text = await summarize_reviews(review_contents)
    except Exception:  # noqa: BLE001
        # Gemini API 실패(APIError)뿐 아니라 클라이언트 생성 실패(ValueError, 키 누락 등)도
        # 포함해 광범위하게 잡는다. 백그라운드 최선 노력 작업이므로 여기서 실패해도
        # 다음 리뷰 작성 시 이 함수가 다시 호출되며 자연스럽게 재시도된다. 원인 파악을
        # 위해 로그는 남긴다.
        logger.exception("리뷰 AI 요약 생성 실패: course_id=%s", course_id)
        return

    if not summary_text or not summary_text.strip():
        logger.warning("Gemini가 빈 요약을 반환해 저장하지 않음: course_id=%s", course_id)
        return

    async with AsyncSessionLocal() as session:
        # Gemini 호출 사이에 리뷰가 삭제되어 3개 미만이 됐을 수 있으므로 재확인
        review_count = await _count_reviews(session, course_id)
        if review_count < _SUMMARY_FIRST_THRESHOLD:
            return

        summary_result = await session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == course_id).with_for_update()
        )
        summary = summary_result.scalar_one_or_none()
        if summary is None:
            session.add(
                ReviewSummary(course_id=course_id, summary=summary_text, review_count=review_count)
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
            # 두 리뷰가 거의 동시에 작성되면 백그라운드 작업도 거의 동시에 두 번 실행될 수
            # 있음. 둘 다 "요약이 아직 없다"고 판단해서 각자 Gemini를 호출하지만,
            # 코스당 요약은 1개만 허용되므로(UNIQUE 제약) 먼저 저장한 쪽만 성공하고
            # 나머지는 여기서 UNIQUE 제약 위반으로 남는다. 이미 요약이 만들어졌다는
            # 뜻이므로 에러 없이 조용히 무시하고 끝낸다.


async def get_review_summary(session: AsyncSession, course_id: int) -> ReviewSummaryResponse | None:
    """코스의 AI 리뷰 요약 조회 (없으면 None - 코스 상세 응답에서 리뷰 원문만 표시)."""
    result = await session.execute(
        select(ReviewSummary).where(ReviewSummary.course_id == course_id)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        return None
    return ReviewSummaryResponse.model_validate(summary)


async def update_review(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    body: ReviewUpdateRequest,
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

    await session.commit()
    await session.refresh(review)

    if content_changed:
        # 리뷰 내용이 바뀌면 기존 AI 요약이 옛 내용을 반영한 채로 남아있게 되므로 무효화한다.
        # Gemini를 다시 호출하지는 않고(비용), 이후 리뷰 개수가 재생성 기준을 충족하면
        # 자연스럽게 다시 생성된다 - 그 전까지는 "요약 없음"으로 리뷰 원문만 표시된다.
        summary_result = await session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == review.course_id)
        )
        summary = summary_result.scalar_one_or_none()
        if summary is not None:
            await session.delete(summary)
            await session.commit()

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
    await session.commit()

    # R2 정리는 best-effort: DB 삭제는 이미 끝났으므로 실패해도 무시 (고아 파일 방지 목적)
    for key in keys:
        with contextlib.suppress(ClientError, BotoCoreError):
            await asyncio.to_thread(
                _get_r2_client().delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
            )

    remaining = await _count_reviews(session, course_id)
    if remaining < _SUMMARY_FIRST_THRESHOLD:
        # 리뷰가 3개 미만으로 줄면 기존 AI 요약은 더 이상 유효하지 않음
        # (FEATURES.md: 3개 미만이면 요약 없이 리뷰 원문만 표시)
        summary_result = await session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == course_id)
        )
        summary = summary_result.scalar_one_or_none()
        if summary is not None:
            await session.delete(summary)
            await session.commit()
    else:
        summary_result = await session.execute(
            select(ReviewSummary).where(ReviewSummary.course_id == course_id).with_for_update()
        )
        summary = summary_result.scalar_one_or_none()
        if summary is not None and summary.review_count > remaining:
            # 삭제로 실제 리뷰 수가 줄었는데 review_count 기준값이 그대로면, 다음
            # 재생성까지 필요한 "+5"가 실제보다 더 많이 쌓여야 하는 것처럼 계산되어
            # 재생성 시점이 불필요하게 늦어진다. 기준값을 현재 개수로 맞춰 방지한다.
            summary.review_count = remaining
            await session.commit()
        # 리뷰 삭제도 재생성 여부를 다시 판단할 계기이므로 백그라운드로 재평가한다
        # (요약이 아직 한 번도 생성되지 않은 경우를 포함).
        background_tasks.add_task(_maybe_update_summary, course_id)


# TODO(course 담당): 코스 상세 조회(get_drnb_course/get_custom_course)에서
# 이 함수를 가져다 응답에 포함해 주세요.
async def get_average_difficulty(session: AsyncSession, course_id: int) -> Difficulty | None:
    """코스별 유저 체감 난이도 평균 (탈퇴 유저 리뷰도 통계 목적으로 포함, 리뷰가 없으면 None).
    EASY/NORMAL/HARD를 점수로 평균을 낸 뒤 가장 가까운 등급으로 반올림하여 표시한다.
    """
    result = await session.execute(select(Review.difficulty).where(Review.course_id == course_id))
    difficulties = result.scalars().all()
    if not difficulties:
        return None
    avg_score = sum(_DIFFICULTY_SCORE[d] for d in difficulties) / len(difficulties)
    rounded_score = min(max(floor(avg_score + 0.5), 1), 3)
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
