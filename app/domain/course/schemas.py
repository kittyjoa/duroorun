"""코스 (DRNB + 커스텀) - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.course.models import Difficulty


class CourseWaypointCreate(BaseModel):
    """커스텀 코스 경유지 좌표 입력 - 리스트 순서가 곧 sequence"""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CourseWaypointResponse(BaseModel):
    """커스텀 코스 경유지 좌표 조회 시 응답"""

    model_config = ConfigDict(from_attributes=True)

    waypoint_id: int
    sequence: int
    latitude: float
    longitude: float


class CourseImageResponse(BaseModel):
    """커스텀 코스 이미지 조회 시 응답 - 업로드 자체는 R2 업로드 엔드포인트에서 처리"""

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
    waypoints: list[CourseWaypointCreate] = Field(min_length=2)


class CourseUpdateRequest(BaseModel):
    """커스텀 코스 수정 - 작성자 본인 전용. 부분 수정이므로 전달된 필드만 반영"""

    course_name: str | None = Field(default=None, min_length=1)
    distance: float | None = Field(default=None, gt=0)
    difficulty: Difficulty | None = None
    estimated_time: int | None = Field(default=None, gt=0)
    course_description: str | None = None
    # 경유지를 다시 보내면 전체 교체 (부분 수정 대상 아님) - 프론트: 경유지 미변경 시 필드 자체를 생략할 것
    # min_length=2라 waypoints를 보내는 순간 항상 최소 2개 필요 (이름만 바꾸는 요청엔 waypoints 생략)
    waypoints: list[CourseWaypointCreate] | None = Field(default=None, min_length=2)


class DrnbCourseSummary(BaseModel):
    """DRNB 코스 목록 요소 - 시드에 등록된 DB 정보만 (상세정보는 API 실시간 조회)"""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    dmb_id: str
    course_name: str
    difficulty: Difficulty | None
    estimated_time: int | None
    sigun: str | None
    brd_div: str | None


class DrnbCourseListResponse(BaseModel):
    """DRNB 코스 목록 조회 시 응답 - offset 페이지네이션"""

    items: list[DrnbCourseSummary]
    total: int
    page: int
    size: int


class DrnbCourseDetailResponse(BaseModel):
    """DRNB 코스 상세 조회 시 응답 - DB 저장 정보 + 두루누비 API 실시간 조회 결과"""

    # from_attributes 미사용: DB 조회 결과 + API 응답을 service.py에서 직접 합쳐 kwargs로 생성
    # TODO: service.py에서 이 kwargs 조립 완료되면, 필드 누락을 잡아낼 조립 테스트 추가
    course_id: int
    dmb_id: str
    course_name: str
    difficulty: Difficulty | None
    estimated_time: int | None
    sigun: str | None
    brd_div: str | None
    # 아래 두 필드는 두루누비 API 실시간 응답값 (durunubi.py 클라이언트가 채움)
    distance: float | None
    course_description: str | None
    # 아래 네 필드는 시드 스크립트가 gpxpath를 파싱해 DB에 저장해둔 값
    # (완주 인증 검증 기준점이므로 API 장애와 무관하게 조회 가능해야 함)
    # TODO(record PR #7 연동): None 허용이 record의 두 좌표 사이 거리 검증과 맞물림.
    # seed_courses.py가 항상 non-null로 채운다는 전제인데, 시드 실패/누락 시
    # record 쪽에서 None을 어떻게 처리할지(검증 실패 vs 예외) 유선님과 confirm 필요.
    start_lat: float | None
    start_lng: float | None
    end_lat: float | None
    end_lng: float | None


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
    # DRNB와 동일하게 record의 완주 인증 기준점으로 쓰임 — None 처리 정책은 위 TODO와 동일 이슈
    start_lat: float | None
    start_lng: float | None
    end_lat: float | None
    end_lng: float | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
    waypoints: list[CourseWaypointResponse]
    images: list[CourseImageResponse]
