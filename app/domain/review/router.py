"""리뷰 + 이미지 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.domain.review import service as review_service
from app.domain.review.schemas import (
    ReviewCreateRequest,
    ReviewListResponse,
    ReviewResponse,
    ReviewUpdateRequest,
)
from app.domain.user.models import User

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post(
    "/courses/{course_id}", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED
)
async def create_review(
    course_id: int,
    body: ReviewCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """리뷰 작성"""
    return await review_service.create_review(
        session=session,
        user_id=current_user.user_id,
        course_id=course_id,
        body=body,
        background_tasks=background_tasks,
    )


@router.patch("/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: int,
    body: ReviewUpdateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """리뷰 수정"""
    return await review_service.update_review(
        session=session, user_id=current_user.user_id, review_id=review_id, body=body
    )


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """리뷰 삭제 (본인 또는 관리자)"""
    await review_service.delete_review(
        session=session,
        user_id=current_user.user_id,
        review_id=review_id,
        user_role=current_user.user_role,
        background_tasks=background_tasks,
    )


@router.get("/courses/{course_id}", response_model=ReviewListResponse)
async def get_reviews(
    course_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),  # 로그인 확인용, 유저정보 사용X
):
    """코스 리뷰 목록 조회"""
    return await review_service.get_reviews(
        session=session, course_id=course_id, page=page, size=size
    )


@router.post(
    "/{review_id}/images", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED
)
async def upload_review_image(
    review_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """리뷰 이미지 업로드"""
    return await review_service.upload_review_image(
        session=session, user_id=current_user.user_id, review_id=review_id, file=file
    )


@router.delete("/{review_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review_image(
    review_id: int,
    image_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """리뷰 이미지 삭제"""
    await review_service.delete_review_image(
        session=session, user_id=current_user.user_id, review_id=review_id, image_id=image_id
    )
