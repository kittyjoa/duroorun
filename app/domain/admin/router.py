"""관리자 대시보드 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_admin
from app.database import get_db
from app.domain.admin import service as admin_service
from app.domain.admin.schemas import BannedAccountListResponse, ForceWithdrawRequest
from app.domain.user.models import User
from app.domain.user.schemas import MessageResponse
from app.redis import get_redis

router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete("/users/{user_id}", response_model=MessageResponse, summary="유저 강제 탈퇴")
async def force_withdraw(
    user_id: int,
    body: ForceWithdrawRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: User = Depends(get_current_admin),
) -> MessageResponse:
    """지속적으로 문제가 되는 유저를 강제 탈퇴 처리합니다."""
    await admin_service.force_withdraw_user(user_id, body.reason, db, redis)
    return MessageResponse(message="유저가 강제 탈퇴 처리되었습니다")


@router.get("/banned-accounts", response_model=BannedAccountListResponse, summary="밴 목록 조회")
async def get_banned_accounts(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> BannedAccountListResponse:
    """강제 탈퇴로 재가입이 막힌 소셜 계정 목록을 조회합니다."""
    return await admin_service.get_banned_accounts(page, size, db)


@router.delete(
    "/banned-accounts/{banned_id}", status_code=status.HTTP_204_NO_CONTENT, summary="밴 해제"
)
async def unban_account(
    banned_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> None:
    """밴을 해제하여 해당 소셜 계정으로 재가입할 수 있게 합니다."""
    await admin_service.unban_account(banned_id, db)
