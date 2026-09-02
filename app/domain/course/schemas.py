"""코스 (DRNB + 커스텀) - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.course.models import Difficulty
from app.domain.review.schemas import ReviewSummaryResponse


# 강원도 대략적인 경계 박스 (frontend/src/pages/CustomCourseForm.jsx의 _GANGWON_BOXES와 동일)
# ㅡ 커스텀 코스는 강원도 전체 범위로 제한
# 강원 본토 박스 + 철원군 전용 박스 2개로 구성
_GANGWON_MAIN_BOX = {"lat": (36.9, 38.7), "lng": (127.4, 129.5)}
_CHEORWON_BOX = {"lat": (37.95, 38.45), "lng": (127.0, 127.45)}  # 철원군 전 지역이 38선 이북이라 서울과 안 겹침


def _in_box(lat: float, lng: float, box: dict) -> bool:
    return box["lat"][0] <= lat <= box["lat"][1] and box["lng"][0] <= lng <= box["lng"][1]


class CourseWaypointCreate(BaseModel):
    """커스텀 코스 경유지 좌표 입력 - 리스트 순서가 곧 sequence
    ㅡ 강원 본토 박스 + 철원군 박스 중 하나에 속해야 함 (강원도 밖 코스 생성 막기)"""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _validate_gangwon_bounds(self) -> "CourseWaypointCreate":
        if not (
            _in_box(self.latitude, self.longitude, _GANGWON_MAIN_BOX)
            or _in_box(self.latitude, self.longitude, _CHEORWON_BOX)
        ):
            raise ValueError("강원도 지역 내 좌표만 입력할 수 있습니다.")
        return self


class CourseWaypointResponse(BaseModel):
    """커스텀 코스 경유지 좌표 조회 시 응답"""

    model_config = ConfigDict(from_attributes=True)

    waypoint_id: int
    sequence: int
    latitude: float
    longitude: float


class CourseImageResponse(BaseModel):
    """커스텀 코스 이미지 조회 시 응답
    - 업로드는 POST /courses/custom/{course_id}/images에서 처리"""

    model_config = ConfigDict(from_attributes=True)

    image_id: int
    image_url: str
    created_at: datetime


class CourseCreateRequest(BaseModel):
    """커스텀 코스 등록 - 로그인 유저 전용. course_type은 CUSTOM 고정"""

    course_name: str = Field(min_length=1)
    distance: float = Field(gt=0)
    difficulty: Difficulty
    estimated_time: int = Field(gt=0)
    course_description: str | None = None
    # 시작/종료 좌표(start_lat/lng, end_lat/lng)는 service.py에서 첫/마지막 경유지로 자동 저장
    # max_length=500: 대량 좌표 전송 방지
    waypoints: list[CourseWaypointCreate] = Field(min_length=2, max_length=500)


class CourseUpdateRequest(BaseModel):
    """커스텀 코스 수정 - 작성자 본인 전용. 부분 수정이므로 전달된 필드만 반영"""

    course_name: str | None = Field(default=None, min_length=1)
    distance: float | None = Field(default=None, gt=0)
    difficulty: Difficulty | None = None
    estimated_time: int | None = Field(default=None, gt=0)
    course_description: str | None = None
    # 경유지를 다시 보내면 전체 교체 (부분 수정 대상 아님)
    # - 프론트: 경유지 미변경 시 필드 자체를 생략할 것
    # min_length=2라 waypoints를 보내는 순간 항상 최소 2개 필요
    # (이름만 바꾸는 요청엔 waypoints 생략)
    waypoints: list[CourseWaypointCreate] | None = Field(default=None, min_length=2, max_length=500)


class DrnbCourseSummary(BaseModel):
    """DRNB 코스 목록 요소 - 시드 스크립트로 등록된 DB 정보만 사용"""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    dmb_id: str
    course_name: str
    difficulty: Difficulty | None
    estimated_time: int | None
    distance: float | None
    sigun: str | None
    brd_div: str | None
    # GPX 파싱 실패로 완주 인증 기준점(start/end 좌표)이 없는 코스면 False
    has_verification_coords: bool


class DrnbCourseListResponse(BaseModel):
    """DRNB 코스 목록 조회 시 응답 - offset 페이지네이션"""

    items: list[DrnbCourseSummary]
    total: int
    page: int
    size: int


class DrnbCourseDetailResponse(BaseModel):
    """DRNB 코스 상세 조회 시 응답 - 시드 스크립트로 저장된 DB 정보만 사용 (배치 갱신)"""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    dmb_id: str
    course_name: str
    difficulty: Difficulty | None
    estimated_time: int | None
    sigun: str | None
    brd_div: str | None
    distance: float | None
    course_description: str | None
    # 완주 인증 검증 기준점 — 시드 스크립트가 gpxpath를 파싱해 저장
    # 팀 결정(2026-08-02): GPX 파싱 실패로 None이면 완주 인증을 에러로 막고
    # 알림 문구를 명확히 띄우기로 함 — has_verification_coords로 좌표 유무 노출.
    start_lat: float | None
    start_lng: float | None
    end_lat: float | None
    end_lng: float | None
    has_verification_coords: bool
    # 리뷰 도메인 데이터 - review/service.py의 get_average_difficulty, get_review_summary로 계산.
    # 리뷰가 없거나(난이도 평균) 3개 미만(AI 요약)이면 None
    average_difficulty: Difficulty | None = None
    review_summary: ReviewSummaryResponse | None = None


class CustomCourseSummary(BaseModel):
    """커스텀 코스 목록 요소"""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    course_name: str
    distance: float | None
    difficulty: Difficulty | None
    estimated_time: int | None
    created_by: int | None
    is_active: bool
    created_at: datetime


class CustomCourseListResponse(BaseModel):
    """커스텀 코스 목록 조회 시 응답 - offset 페이지네이션"""

    items: list[CustomCourseSummary]
    total: int
    page: int
    size: int


class CustomCourseDetailResponse(BaseModel):
    """커스텀 코스 상세 조회 시 응답 - 경유지/이미지 포함"""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    course_name: str
    distance: float | None
    difficulty: Difficulty | None
    estimated_time: int | None
    course_description: str | None
    created_by: int | None
    # DRNB와 동일하게 record의 완주 인증 기준점으로 쓰임. 다만 커스텀 코스는 등록 시
    # 첫/마지막 경유지로 항상 채워지므로 DRNB의 None 케이스 결정과 무관
    start_lat: float | None
    start_lng: float | None
    end_lat: float | None
    end_lng: float | None
    has_verification_coords: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
    waypoints: list[CourseWaypointResponse]
    images: list[CourseImageResponse]
    # 리뷰 도메인 데이터 - review/service.py의 get_average_difficulty, get_review_summary로 계산.
    # 리뷰가 없거나(난이도 평균) 3개 미만(AI 요약)이면 None
    average_difficulty: Difficulty | None = None
    review_summary: ReviewSummaryResponse | None = None
