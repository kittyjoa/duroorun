"""회원/인증 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import bearer_scheme, get_current_user
from app.database import get_db
from app.domain.user.models import User
from app.domain.user.schemas import (
    MessageResponse,
    ProfileImageResponse,
    TokenResponse,
    UserProfileUpdate,
    UserResponse,
)
from app.domain.user.service import (
    get_kakao_auth_url,
    kakao_login,
    logout,
    refresh_tokens,
    update_profile,
    upload_profile_image,
    withdraw_user,
)
from app.redis import get_redis

router = APIRouter(tags=["auth"])

_REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"


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
        path=_REFRESH_COOKIE_PATH,
    )

    return TokenResponse(access_token=access_token, is_new_user=is_new_user)


@router.post("/auth/refresh", response_model=TokenResponse, summary="토큰 재발급")
async def token_refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """Refresh Token 쿠키로 새 Access Token과 Refresh Token을 발급합니다."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token이 없습니다",
        )

    new_access_token, new_refresh_token = await refresh_tokens(refresh_token, redis)

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_REFRESH_COOKIE_PATH,
    )

    return TokenResponse(access_token=new_access_token, is_new_user=False)


@router.post("/auth/logout", response_model=MessageResponse, summary="로그아웃")
async def logout_endpoint(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    redis: Redis = Depends(get_redis),
) -> MessageResponse:
    """Access Token을 무효화하고 Refresh Token을 삭제합니다."""
    await logout(credentials.credentials, redis)

    response.delete_cookie(key="refresh_token", path=_REFRESH_COOKIE_PATH)

    return MessageResponse(message="로그아웃 되었습니다")


@router.get("/users/me", response_model=UserResponse, summary="내 정보 조회")
async def get_my_profile(user: User = Depends(get_current_user)) -> UserResponse:
    """내 정보를 조회합니다."""
    return UserResponse.model_validate(user)


@router.patch("/users/me", response_model=UserResponse, summary="내 정보 수정")
async def update_my_profile(
    body: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserResponse:
    """닉네임/거주지를 수정합니다. 최초 가입 완료 시에도 이 엔드포인트를 사용합니다."""
    updated = await update_profile(user, body.nickname, body.location, db)
    return UserResponse.model_validate(updated)


@router.post("/users/me/image", response_model=ProfileImageResponse, summary="프로필 이미지 업로드")
async def upload_my_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileImageResponse:
    """프로필 이미지를 R2에 업로드하고 URL을 저장합니다."""
    url = await upload_profile_image(user, file, db)
    return ProfileImageResponse(profile_image_url=url)


@router.delete("/users/me", response_model=MessageResponse, summary="회원 탈퇴")
async def withdraw(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    user: User = Depends(get_current_user),
) -> MessageResponse:
    """개인정보를 익명화하고 소셜 계정을 삭제합니다."""
    await withdraw_user(user, credentials.credentials, db, redis)

    response.delete_cookie(key="refresh_token", path=_REFRESH_COOKIE_PATH)

    return MessageResponse(message="회원 탈퇴가 완료되었습니다")
