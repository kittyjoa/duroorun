"""리뷰 + 이미지 - 비즈니스 로직."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.course.models import Course
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

    # 완주 인증 확인 - TODO: record 연동 후 활성화 예정
    # record = await session.execute(
    #     select(Record).where(
    #         Record.user_id == user_id, Record.course_id == course_id, Record.is_completed == True
    #     )
    # )
    # if record.scalar_one_or_none() is None:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="완주한 코스에만 리뷰를 작성할 수 있습니다.",
    #     )

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
    review.updated_at = datetime.now(UTC)

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


async def get_reviews(
        session: AsyncSession,
        course_id: int,
        page: int,
        size: int,
) -> ReviewListResponse:
    """코스 리뷰 목록 조회 (탈퇴 유저 포함, 최신순으로 조회)"""
    offset = (page - 1) * size
    total_result = await session.execute(
        select(func.count()).select_from(Review).where(Review.course_id == course_id)
    )
    total = total_result.scalar_one()
    result = await session.execute(
        select(Review)
        .where(Review.course_id == course_id)
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

    # 파일 크기 확인 (제한 초과 시 즉시 중단, 전체를 다 읽지 않음)
    max_bytes = settings.REVIEW_IMAGE_MAX_SIZE_MB * 1024 * 1024
    chunks = []
    total_size = 0
    while chunk := await file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"이미지 크기는 {settings.REVIEW_IMAGE_MAX_SIZE_MB}MB 이하여야 합니다.",
            )
        chunks.append(chunk)
    contents = b"".join(chunks)

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

    # R2에서 삭제
    key = image.image_url.removeprefix(f"{settings.R2_PUBLIC_URL.rstrip('/')}/")
    try:
        await asyncio.to_thread(
            _get_r2_client().delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
        )
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="이미지 삭제에 실패했습니다.",
        ) from err

    await session.delete(image)
    await session.commit()
