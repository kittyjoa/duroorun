"""리뷰 + 이미지 - 비즈니스 로직."""

import asyncio
import contextlib
import uuid
from functools import lru_cache
from math import floor

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.course.models import Course, Difficulty
from app.domain.record.models import Record
from app.domain.review.models import Review, ReviewImage
from app.domain.review.schemas import (
    ReviewCreateRequest,
    ReviewImageResponse,
    ReviewListResponse,
    ReviewResponse,
    ReviewUpdateRequest,
)
from app.domain.user.models import UserRole

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
    """파일 시그니처(매직바이트)로 실제 이미지 형식을 판별합니다."""
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


async def create_review(
    session: AsyncSession,
    user_id: int,
    course_id: int,
    body: ReviewCreateRequest,
) -> ReviewResponse:
    """리뷰 작성"""
    # 코스 존재 확인
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="코스를 찾을 수 없습니다."
        )

    # 완주 인증 확인 (같은 코스를 여러 번 완주했을 수 있으므로 존재 여부만 확인)
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
        content=body.content,
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
    return ReviewResponse.model_validate(review)


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

    if body.content is not None:
        review.content = body.content
    if body.difficulty is not None:
        review.difficulty = body.difficulty

    await session.commit()
    await session.refresh(review)
    return ReviewResponse.model_validate(review)


async def delete_review(
    session: AsyncSession,
    user_id: int,
    review_id: int,
    user_role: UserRole,
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
    # 리뷰 존재 및 본인 확인
    review = await session.get(Review, review_id)
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
