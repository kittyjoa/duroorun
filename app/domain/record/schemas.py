"""러닝 기록 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RecordStartRequest(BaseModel):
    """러닝시작: 시작 눌렀을 때 보내는 데이터"""

    course_id: int
    user_start_lat: float
    user_start_lng: float


class RecordEndRequest(BaseModel):
    """러닝종료: 종료 눌렀을 때 보내는 데이터"""

    user_end_lat: float
    user_end_lng: float


class RecordResponse(BaseModel):
    """러닝기록 조회 시 응답부분"""

    model_config = ConfigDict(from_attributes=True)

    record_id: int
    course_id: int
    duration_seconds: int | None
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
    pace: float | None
    is_completed: bool


