"""편의시설 - Pydantic 스키마 (요청/응답 검증)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.facility.models import FacilityType


class FacilityCreateRequest(BaseModel):
    """편의시설 등록 - 관리자 전용"""

    facility_type: FacilityType
    facility_name: str = Field(min_length=1)
    facility_address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    kakao_place_id: str | None = None
    # 연결할 코스 (선택사항, 복수 선택 가능)
    course_ids: list[int] = Field(default_factory=list)
    # 코스 id 안보내면, list() 실행 → 매번 새로운 [] 생성


class FacilityUpdateRequest(BaseModel):
    """편의시설 수정 - 관리자 전용. 부분 수정이므로 전달된 필드만 반영"""

    facility_type: FacilityType | None = None
    facility_name: str | None = Field(default=None, min_length=1)
    facility_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    kakao_place_id: str | None = None
    # None이면 코스 연결 변경 없음, 빈 리스트면 전체 연결 해제
    course_ids: list[int] | None = None


class FacilityResponse(BaseModel):
    """편의시설 조회 시 응답"""

    model_config = ConfigDict(from_attributes=True)

    facility_id: int
    facility_type: FacilityType
    facility_name: str
    facility_address: str | None
    latitude: float
    longitude: float
    kakao_place_id: str | None
    # place_url은 요청 스키마에 없음 - service에서 kakao_place_id로 카카오 로컬 API 조회 후 조립
    # (조립 로직 구현 전까지는 kakao_place_id 있어도 place_url=None으로 응답됨)
    place_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None


class FacilityListResponse(BaseModel):
    """편의시설 목록 조회 시 응답 - offset 페이지네이션"""

    items: list[FacilityResponse]
    total: int
    page: int
    size: int
