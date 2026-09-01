"""관리자 - Pydantic 스키마 (대시보드 통계 응답 형태 정의)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.user.models import ProviderType


class ForceWithdrawRequest(BaseModel):
    """유저 강제 탈퇴 요청."""

    reason: str


class BannedAccountResponse(BaseModel):
    """밴 계정 조회 시 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_type: ProviderType
    provider_uid: str
    reason: str
    banned_at: datetime


class BannedAccountListResponse(BaseModel):
    """밴 목록 조회 응답 - offset 페이지네이션"""

    items: list[BannedAccountResponse]
    total: int
    page: int
    size: int
