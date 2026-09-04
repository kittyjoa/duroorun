"""코스 (DRNB + 커스텀) - Pydantic 스키마 (요청/응답 검증)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from app.domain.course.models import Difficulty
from app.domain.review.schemas import ReviewSummaryResponse

# 강원도 실제 경계(폴리곤) - 통계청 SGIS 시도 경계 데이터에서 강원도만 추출
# (출처/추출: app/scripts/extract_gangwon_boundary.py, 공공누리 제1유형)
# ㅡ 프론트도 이 파일을 GET /courses/gangwon-boundary로 그대로 받아 같은 폴리곤으로 검증함
#   (router.py) - 경로 상수를 여기 하나만 둬서 프론트/백엔드가 다른 파일을 보는 일이 없게 함
GANGWON_BOUNDARY_PATH = Path(__file__).parent / "gangwon_boundary" / "gangwon_boundary.geojson"
with GANGWON_BOUNDARY_PATH.open(encoding="utf-8") as _f:
    _GANGWON_BOUNDARY: BaseGeometry = shape(json.load(_f)["geometry"])


def _in_gangwon(lat: float, lng: float) -> bool:
    # shapely는 (경도, 위도)=(x, y) 순서 - lat/lng 그대로 넣으면 조용히 틀린 결과 나옴
    # covers(): contains()와 달리 경계선 위의 점도 포함 (도 경계 걸친 좌표 포함 위해)
    return _GANGWON_BOUNDARY.covers(Point(lng, lat))


class CourseWaypointCreate(BaseModel):
    """커스텀 코스 경유지 좌표 입력 - 리스트 순서가 곧 sequence
    ㅡ 강원도 실제 경계(폴리곤) 안에 있어야 함 (강원도 밖 코스 생성 막기)"""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _validate_gangwon_bounds(self) -> "CourseWaypointCreate":
        if not _in_gangwon(self.latitude, self.longitude):
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


# 터무니없는 값(DB 정수 범위 초과 등)을 막기 위한 상한선 - 정밀 한도 X
_COURSE_NAME_MAX_LENGTH = 100
_COURSE_DESCRIPTION_MAX_LENGTH = 2000
_DISTANCE_MAX_KM = 500.0
_ESTIMATED_TIME_MAX_MINUTES = 10000


def _strip_and_reject_blank(value: str) -> str:
    """앞뒤 공백을 지우고, 공백만 있던 경우를 거부합니다."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("공백만으로는 입력할 수 없습니다.")
    return stripped


# min_length=1은 raw 길이만 보므로 공백 같은 값도 통과시킴 - strip 후 재검증 필요
_NonBlankStr = Annotated[str, AfterValidator(_strip_and_reject_blank)]


class CourseCreateRequest(BaseModel):
    """커스텀 코스 등록 - 로그인 유저 전용. course_type은 CUSTOM 고정"""

    course_name: _NonBlankStr = Field(min_length=1, max_length=_COURSE_NAME_MAX_LENGTH)
    distance: float = Field(gt=0, le=_DISTANCE_MAX_KM)
    difficulty: Difficulty
    estimated_time: int = Field(gt=0, le=_ESTIMATED_TIME_MAX_MINUTES)
    course_description: str | None = Field(default=None, max_length=_COURSE_DESCRIPTION_MAX_LENGTH)
    # 시작/종료 좌표(start_lat/lng, end_lat/lng)는 service.py에서 첫/마지막 경유지로 자동 저장
    # max_length=500: 대량 좌표 전송 방지
    waypoints: list[CourseWaypointCreate] = Field(min_length=2, max_length=500)


class CourseUpdateRequest(BaseModel):
    """커스텀 코스 수정 - 작성자 본인 전용. 부분 수정이므로 전달된 필드만 반영"""

    course_name: _NonBlankStr | None = Field(
        default=None, min_length=1, max_length=_COURSE_NAME_MAX_LENGTH
    )
    distance: float | None = Field(default=None, gt=0, le=_DISTANCE_MAX_KM)
    difficulty: Difficulty | None = None
    estimated_time: int | None = Field(default=None, gt=0, le=_ESTIMATED_TIME_MAX_MINUTES)
    course_description: str | None = Field(default=None, max_length=_COURSE_DESCRIPTION_MAX_LENGTH)
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
    # created_by가 가리키는 유저의 닉네임 - service.py에서 course.creator로 eager load 후 채워 넣음
    # (탈퇴 등으로 created_by가 NULL이면 이 값도 None)
    creator_nickname: str | None = None
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
    # created_by가 가리키는 유저의 닉네임 - service.py에서 course.creator로 eager load 후 채워 넣음
    # (탈퇴 등으로 created_by가 NULL이면 이 값도 None)
    creator_nickname: str | None = None
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
