"""리뷰 + 이미지 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.course.models import Difficulty


class ReviewCreateRequest(BaseModel):
    """리뷰 작성 요청"""

    content: str
    difficulty: Difficulty


class ReviewUpdateRequest(BaseModel):
    """리뷰 수정 요청"""

    content: str | None = None
    difficulty: Difficulty | None = None


class ReviewImageResponse(BaseModel):
    """리뷰 이미지 응답"""

    model_config = ConfigDict(from_attributes=True)

    image_id: int
    image_url: str
    created_at: datetime


class ReviewResponse(BaseModel):
    """리뷰 조회 시 응답"""

    model_config = ConfigDict(from_attributes=True)

    review_id: int
    user_id: int | None
    course_id: int
    content: str
    difficulty: Difficulty
    created_at: datetime
    updated_at: datetime | None
    images: list[ReviewImageResponse] = []


class ReviewListResponse(BaseModel):
    """리뷰 목록 응답"""

    items: list[ReviewResponse]
    total: int
    page: int
    size: int


class ReviewSummaryResponse(BaseModel):
    """AI 리뷰 요약 응답"""

    model_config = ConfigDict(from_attributes=True)

    summary: str
    review_count: int
    updated_at: datetime
