"""관리자 대시보드 - 비즈니스 로직 (통계 집계 등)."""

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin.schemas import BannedAccountListResponse, BannedAccountResponse
from app.domain.user.models import BannedAccount, User
from app.domain.user.service import force_withdraw_user as _force_withdraw_user


async def force_withdraw_user(user_id: int, reason: str, db: AsyncSession, redis: Redis) -> None:
    """유저 강제 탈퇴 (관리자 전용)."""
    result = await db.execute(
        select(User).where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 탈퇴한 유저입니다",
        )

    await _force_withdraw_user(user, reason, db, redis)


async def get_banned_accounts(page: int, size: int, db: AsyncSession) -> BannedAccountListResponse:
    """밴(재가입 차단) 계정 목록 조회."""
    total = (await db.execute(select(func.count()).select_from(BannedAccount))).scalar_one()

    result = await db.execute(
        select(BannedAccount)
        .order_by(BannedAccount.banned_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = result.scalars().all()

    return BannedAccountListResponse(
        items=[BannedAccountResponse.model_validate(b) for b in items],
        total=total,
        page=page,
        size=size,
    )


async def unban_account(banned_id: int, db: AsyncSession) -> None:
    """밴 해제 - banned_accounts row 삭제."""
    result = await db.execute(delete(BannedAccount).where(BannedAccount.id == banned_id))
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 밴 계정입니다",
        )
    await db.commit()
