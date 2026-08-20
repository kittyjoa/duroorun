"""러닝 기록 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    pace: float | None
    is_completed: bool
    # 코스에 완주 인증 기준 좌표가 없어서 인증 판정 자체가 불가능한 경우에만 채워짐
    # (그 외에는 항상 None — end_record가 아닌 다른 조회 응답에서도 None으로 나감)
    verification_message: str | None = None


class RecordListResponse(BaseModel):
    """러닝기록 목록 조회 응답"""

    items: list[RecordResponse]
    total: int
    page: int
    size: int
