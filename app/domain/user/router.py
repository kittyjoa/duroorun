"""회원/인증 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.domain.user.schemas import TokenResponse
from app.domain.user.service import get_kakao_auth_url, kakao_login
from app.redis import get_redis

router = APIRouter(tags=["auth"])


@router.get("/auth/kakao", summary="카카오 로그인 페이지로 리다이렉트")
async def kakao_auth(redis: Redis = Depends(get_redis)) -> RedirectResponse:
    """카카오 OAuth 인증 페이지로 리다이렉트합니다."""
    url = await get_kakao_auth_url(redis)
    return RedirectResponse(url)


@router.get("/auth/kakao/callback", response_model=TokenResponse, summary="카카오 로그인 콜백")
async def kakao_callback(
    code: str,
    state: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """카카오 OAuth 콜백을 처리하고 JWT를 발급합니다."""
    access_token, refresh_token, is_new_user = await kakao_login(code, state, db, redis)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth/refresh",
    )

    return TokenResponse(access_token=access_token, is_new_user=is_new_user)
