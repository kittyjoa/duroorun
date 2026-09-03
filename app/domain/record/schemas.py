"""러닝 기록 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.course.models import CourseType


class RecordStartRequest(BaseModel):
    """러닝시작: 시작 눌렀을 때 보내는 데이터"""

    course_id: int
    user_start_lat: float = Field(ge=-90, le=90)
    user_start_lng: float = Field(ge=-180, le=180)


class RecordEndRequest(BaseModel):
    """러닝종료: 종료 눌렀을 때 보내는 데이터"""

    user_end_lat: float = Field(ge=-90, le=90)
    user_end_lng: float = Field(ge=-180, le=180)


class RecordResponse(BaseModel):
    """러닝기록 조회 시 응답부분"""

    model_config = ConfigDict(from_attributes=True)

    record_id: int
    course_id: int
    duration_seconds: int | None
    started_at: datetime
    ended_at: datetime | None
    paused_at: datetime | None
    # 진행 중 지금까지 일시정지로 쓴 누적 시간(초) - 새로고침 등으로 진행 중인 기록을
    # 복구할 때, 프론트가 경과 시간을 정확히 재계산하는 데 필요
    total_paused_seconds: int
    created_at: datetime
    pace: float | None
    is_completed: bool
    # 완주 인증이 유저 잘못이 아닌 코스 쪽 문제로 처리되지 않았을 때만 채워짐
    # (러닝 도중 코스가 비활성화됐거나, 코스에 완주 인증 기준 좌표가 없는 경우)
    # 그 외에는 항상 None — end_record가 아닌 다른 조회 응답에서도 None으로 나감
    verification_message: str | None = None


class MyRecordResponse(BaseModel):
    """내 러닝기록 목록 - 어떤 코스 기록인지 알 수 있도록 코스명 포함"""

    model_config = ConfigDict(from_attributes=True)

    record_id: int
    course_id: int
    course_name: str
    # 다른 코스에서 진행 중인 기록을 안내할 때, 프론트가 그 기록 화면 URL
    # (/records/start/{course_type}/{course_id})을 만들 수 있도록 포함
    course_type: CourseType
    duration_seconds: int | None
    started_at: datetime
    ended_at: datetime | None
    paused_at: datetime | None
    total_paused_seconds: int
    created_at: datetime
    pace: float | None
    is_completed: bool
    verification_message: str | None = None


class MyRecordListResponse(BaseModel):
    """내 러닝기록 목록 응답 (코스명 포함)"""

    items: list[MyRecordResponse]
    total: int
    page: int
    size: int
