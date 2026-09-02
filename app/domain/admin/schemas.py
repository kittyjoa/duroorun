"""관리자 - Pydantic 스키마 (대시보드 통계 응답 형태 정의)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.facility.models import FacilityType
from app.domain.user.models import ProviderType


class ForceWithdrawRequest(BaseModel):
    """유저 강제 탈퇴 요청."""

    reason: str = Field(min_length=1, max_length=255)


class BannedAccountResponse(BaseModel):
    """밴 계정 조회 시 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_type: ProviderType
    reason: str
    banned_at: datetime


class BannedAccountListResponse(BaseModel):
    """밴 목록 조회 응답 - offset 페이지네이션"""

    items: list[BannedAccountResponse]
    total: int
    page: int
    size: int


class PeriodCountResponse(BaseModel):
    """오늘/이번주/이번달/올해 스냅샷 카운트 (신규 가입자, 탈퇴 수, 완주 횟수 공용)."""

    today: int
    this_week: int
    this_month: int
    this_year: int


class MonthlyYearlyCountResponse(BaseModel):
    """이번달/올해 스냅샷 카운트 (일/주 단위가 의미 없는 지표용, 예: 커스텀 코스 등록)."""

    this_month: int
    this_year: int


class CoursePopularityItem(BaseModel):
    """인기 코스 랭킹 항목 (완주 횟수 기준)."""

    course_id: int
    course_name: str
    completion_count: int


class UserStatsResponse(BaseModel):
    """대시보드 - 유저 통계."""

    total_users: int
    new_users: PeriodCountResponse
    active_users_30d: int
    withdrawn_users: PeriodCountResponse


class RecordStatsResponse(BaseModel):
    """대시보드 - 러닝 기록 통계."""

    total_distance_km: float
    total_completions: int
    completions: PeriodCountResponse


class CourseStatsResponse(BaseModel):
    """대시보드 - 코스 통계."""

    popular_overall: list[CoursePopularityItem]
    popular_drnb: list[CoursePopularityItem]
    popular_custom: list[CoursePopularityItem]
    total_custom_courses: int
    custom_course_registrations: MonthlyYearlyCountResponse


class DashboardStatsResponse(BaseModel):
    """관리자 대시보드 통계 전체 응답."""

    users: UserStatsResponse
    records: RecordStatsResponse
    courses: CourseStatsResponse
    total_reviews: int
    facility_counts_by_type: dict[FacilityType, int]
