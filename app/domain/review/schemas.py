"""리뷰 + 이미지 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.course.models import CourseType, Difficulty


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


class MyReviewResponse(BaseModel):
    """마이페이지 - 내가 쓴 리뷰 응답 (어떤 코스 리뷰인지 알 수 있도록 코스명 포함)"""

    model_config = ConfigDict(from_attributes=True)

    review_id: int
    course_id: int
    course_name: str
    # 프론트가 코스 상세 URL(/courses/{course_type}/{course_id})을 만들 수 있도록 포함
    course_type: CourseType
    # 코스가 삭제(소프트 삭제)되면 코스 상세 API가 404를 반환해서 그쪽 경로의 수정/삭제
    # 버튼에 닿을 수 없다 - 프론트가 이걸로 "삭제된 코스" 표시 + 모달 내 직접 삭제를
    # 판단한다(리뷰 지적)
    course_is_active: bool
    content: str
    difficulty: Difficulty
    created_at: datetime
    updated_at: datetime | None
    images: list[ReviewImageResponse] = []


class MyReviewListResponse(BaseModel):
    """마이페이지 - 내가 쓴 리뷰 목록 응답"""

    items: list[MyReviewResponse]
    total: int
    page: int
    size: int
