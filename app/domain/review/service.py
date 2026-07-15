"""리뷰 + 이미지 - 비즈니스 로직."""

from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.review.models import Review
from app.domain.review.schemas import (
    ReviewCreateRequest,
    ReviewListResponse,
    ReviewResponse,
    ReviewUpdateRequest,
)
from app.domain.user.models import UserRole


async def create_review(
        session: AsyncSession,
        user_id: int,
        course_id: int,
        body: ReviewCreateRequest,
) -> ReviewResponse:
    """리뷰 작성"""
    # 완주 인증 확인 - TODO: record 연동 후 활성화 예정
    # record = await session.execute(
    #     select(Record).where(
    #         Record.user_id == user_id, Record.course_id == course_id, Record.is_completed == True
    #     )
    # )
    # if record.scalar_one_or_none() is None:
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="완주한 코스에만 리뷰를 작성할 수 있습니다.")

    # 코스당 리뷰 1개 제한 확인
    existing = await session.execute(
        select(Review).where(Review.user_id == user_id, Review.course_id == course_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 해당 코스에 리뷰를 작성했습니다.")

    review = Review(
        user_id=user_id,
        course_id=course_id,
        content=body.content,
        difficulty=body.difficulty,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return ReviewResponse.model_validate(review)


async def update_review(
        session: AsyncSession,
        user_id: int,
        review_id: int,
        body: ReviewUpdateRequest,
) -> ReviewResponse:
    """리뷰 수정"""
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다.")
    if review.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 리뷰만 수정할 수 있습니다.")

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
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다.")
    if review.user_id != user_id and user_role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인의 리뷰만 삭제할 수 있습니다.")
    await session.delete(review)
    await session.commit()


async def get_reviews(
        session: AsyncSession,
        course_id: int,
        page: int,
        size: int,
) -> ReviewListResponse:
    """코스 리뷰 목록 조회 (탈퇴 유저 제외, 최신순으로 조회)"""
    offset = (page - 1) * size
    total_result = await session.execute(
        select(func.count()).select_from(Review).where(
            Review.course_id == course_id,
            Review.user_id.is_not(None),
        )
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
    """리뷰 이미지 업로드 - TODO: R2 연동 후 구현"""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="이미지 업로드는 추후 구현 예정입니다.")


async def delete_review_image(
        session: AsyncSession,
        user_id: int,
        review_id: int,
        image_id: int,
) -> None:
    """리뷰 이미지 삭제 - TODO: R2 연동 후 구현"""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="이미지 삭제는 추후 구현 예정입니다.")
