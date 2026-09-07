"""회원/인증 - API 엔드포인트 (APIRouter)."""

from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rate_limit import check_rate_limit, rate_limit_per_request, record_rate_limit_hit
from app.core.security import bearer_scheme, get_current_user
from app.database import get_db
from app.domain.user.models import User
from app.domain.user.schemas import (
    MessageResponse,
    ProfileImageResponse,
    TokenResponse,
    UserOnboardingRequest,
    UserProfileUpdate,
    UserResponse,
)
from app.domain.user.service import (
    delete_profile_image,
    get_google_auth_url,
    get_kakao_auth_url,
    get_naver_auth_url,
    google_login,
    kakao_login,
    logout,
    naver_login,
    refresh_tokens,
    update_profile,
    upload_profile_image,
    withdraw_user,
)
from app.redis import get_redis

router = APIRouter(tags=["auth"])

_REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
_OAUTH_STATE_COOKIE_PATH = "/api/v1/auth"

# 유저당 10분에 5번까지
_RATE_LIMIT_MAX_REQUESTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 600


def _oauth_redirect_start(url: str, state: str) -> RedirectResponse:
    """소셜사 인증 페이지로 리다이렉트하며, state를 쿠키에도 심어 콜백 브라우저와 대조합니다.

    Redis 저장만으로는 "그 state가 실존하는지"만 확인될 뿐, 콜백을 받은 브라우저가
    로그인을 시작한 그 브라우저인지는 보장 못 함 — 공격자가 자신의 code/state를 담은
    콜백 URL을 피해자에게 전달하면 피해자가 공격자 계정으로 로그인되는 로그인 CSRF가
    가능해짐. 짧게 만료되는 httpOnly 쿠키로 브라우저를 묶어 이를 막는다.
    """
    redirect = RedirectResponse(url)
    redirect.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.OAUTH_STATE_EXPIRE_SECONDS,
        path=_OAUTH_STATE_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN or None,
    )
    return redirect


def _oauth_success_redirect(refresh_token: str) -> RedirectResponse:
    """소셜 로그인 성공 후 프론트로 리다이렉트합니다.

    소셜사 콜백은 브라우저 전체 페이지 이동이라 JSON을 직접 응답해도 프론트(SPA)가
    받을 방법이 없음 — access_token은 URL에 노출되면 브라우저 히스토리/Referrer/서버
    로그로 새어나갈 수 있어 절대 싣지 않는다. refresh_token만 쿠키로 실어 보내고,
    프론트는 도착 즉시 /auth/refresh를 호출해 access_token을 받은 뒤 /users/me로
    온보딩 완료 여부(닉네임/거주지 유무)를 직접 조회해 이동 경로를 정한다.
    """
    redirect = RedirectResponse(f"{settings.FRONTEND_URL}/oauth/callback")
    redirect.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN or None,
    )
    redirect.delete_cookie(
        key="oauth_state", path=_OAUTH_STATE_COOKIE_PATH, domain=settings.COOKIE_DOMAIN or None
    )
    return redirect


def _oauth_error_redirect(detail: str) -> RedirectResponse:
    """소셜 로그인 실패 시 raw JSON 대신 프론트 로그인 페이지로 리다이렉트합니다."""
    params = urlencode({"error": detail})
    redirect = RedirectResponse(f"{settings.FRONTEND_URL}/login?{params}")
    redirect.delete_cookie(
        key="oauth_state", path=_OAUTH_STATE_COOKIE_PATH, domain=settings.COOKIE_DOMAIN or None
    )
    return redirect


@router.get("/auth/kakao", summary="카카오 로그인 페이지로 리다이렉트")
async def kakao_auth(redis: Redis = Depends(get_redis)) -> RedirectResponse:
    """카카오 OAuth 인증 페이지로 리다이렉트합니다."""
    url, state = await get_kakao_auth_url(redis)
    return _oauth_redirect_start(url, state)


@router.get("/auth/kakao/callback", summary="카카오 로그인 콜백")
async def kakao_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """카카오 OAuth 콜백을 처리하고 프론트로 리다이렉트합니다."""
    if error or not code:
        return _oauth_error_redirect("로그인이 취소되었습니다")
    try:
        _, refresh_token = await kakao_login(code, state, oauth_state, db, redis)
    except HTTPException as e:
        return _oauth_error_redirect(e.detail)
    return _oauth_success_redirect(refresh_token)


@router.get("/auth/naver", summary="네이버 로그인 페이지로 리다이렉트")
async def naver_auth(redis: Redis = Depends(get_redis)) -> RedirectResponse:
    """네이버 OAuth 인증 페이지로 리다이렉트합니다."""
    url, state = await get_naver_auth_url(redis)
    return _oauth_redirect_start(url, state)


@router.get("/auth/naver/callback", summary="네이버 로그인 콜백")
async def naver_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """네이버 OAuth 콜백을 처리하고 프론트로 리다이렉트합니다."""
    if error or not code:
        return _oauth_error_redirect("로그인이 취소되었습니다")
    try:
        _, refresh_token = await naver_login(code, state, oauth_state, db, redis)
    except HTTPException as e:
        return _oauth_error_redirect(e.detail)
    return _oauth_success_redirect(refresh_token)


@router.get("/auth/google", summary="구글 로그인 페이지로 리다이렉트")
async def google_auth(redis: Redis = Depends(get_redis)) -> RedirectResponse:
    """구글 OAuth 인증 페이지로 리다이렉트합니다."""
    url, state = await get_google_auth_url(redis)
    return _oauth_redirect_start(url, state)


@router.get("/auth/google/callback", summary="구글 로그인 콜백")
async def google_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """구글 OAuth 콜백을 처리하고 프론트로 리다이렉트합니다."""
    if error or not code:
        return _oauth_error_redirect("로그인이 취소되었습니다")
    try:
        _, refresh_token = await google_login(code, state, oauth_state, db, redis)
    except HTTPException as e:
        return _oauth_error_redirect(e.detail)
    return _oauth_success_redirect(refresh_token)


@router.post("/auth/refresh", response_model=TokenResponse, summary="토큰 재발급")
async def token_refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """Refresh Token 쿠키로 새 Access Token과 Refresh Token을 발급합니다."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token이 없습니다",
        )

    new_access_token, new_refresh_token = await refresh_tokens(refresh_token, db, redis)

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN or None,
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

    response.delete_cookie(
        key="refresh_token", path=_REFRESH_COOKIE_PATH, domain=settings.COOKIE_DOMAIN or None
    )

    return MessageResponse(message="로그아웃 되었습니다")


@router.get("/users/me", response_model=UserResponse, summary="내 정보 조회")
async def get_my_profile(user: User = Depends(get_current_user)) -> UserResponse:
    """내 정보를 조회합니다."""
    return UserResponse.model_validate(user)


@router.put("/users/me", response_model=UserResponse, summary="최초 가입 완료")
async def complete_onboarding(
    body: UserOnboardingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserResponse:
    """카카오 로그인 최초 가입 시 닉네임/거주지를 필수로 입력받습니다."""
    updated = await update_profile(user, body.nickname, body.location, db)
    return UserResponse.model_validate(updated)


@router.patch("/users/me", response_model=UserResponse, summary="내 정보 수정")
async def update_my_profile(
    body: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    user: User = Depends(get_current_user),
) -> UserResponse:
    """마이페이지에서 닉네임/거주지를 수정합니다.

    닉네임 중복 등으로 실패한 시도는 요청 횟수 제한에 포함하지 않는다 —
    성공했을 때만 카운트해서, 마음에 드는 닉네임을 찾는 정상적인 시행착오까지 막지 않기 위함.
    """
    rate_limit_key = f"ratelimit:profile_update:{user.user_id}"
    await check_rate_limit(redis, rate_limit_key, _RATE_LIMIT_MAX_REQUESTS)

    updated = await update_profile(user, body.nickname, body.location, db)

    await record_rate_limit_hit(redis, rate_limit_key, _RATE_LIMIT_WINDOW_SECONDS)
    return UserResponse.model_validate(updated)


@router.post(
    "/users/me/image",
    response_model=ProfileImageResponse,
    summary="프로필 이미지 업로드",
    dependencies=[
        Depends(
            rate_limit_per_request(
                "image_upload", _RATE_LIMIT_MAX_REQUESTS, _RATE_LIMIT_WINDOW_SECONDS
            )
        )
    ],
)
async def upload_my_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileImageResponse:
    """프로필 이미지를 R2에 업로드하고 URL을 저장합니다."""
    url = await upload_profile_image(user, file, db)
    return ProfileImageResponse(profile_image_url=url)


@router.delete(
    "/users/me/image",
    response_model=MessageResponse,
    summary="프로필 이미지 삭제",
    dependencies=[
        Depends(
            # 업로드와 key_prefix 공유 — 업로드/삭제 번갈아 반복하는 남용도 같이 막기 위함
            rate_limit_per_request(
                "image_upload", _RATE_LIMIT_MAX_REQUESTS, _RATE_LIMIT_WINDOW_SECONDS
            )
        )
    ],
)
async def delete_my_image(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageResponse:
    """프로필 이미지를 삭제하고 기본 이미지로 되돌립니다."""
    await delete_profile_image(user, db)
    return MessageResponse(message="프로필 이미지가 삭제되었습니다")


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

    response.delete_cookie(
        key="refresh_token", path=_REFRESH_COOKIE_PATH, domain=settings.COOKIE_DOMAIN or None
    )

    return MessageResponse(message="회원 탈퇴가 완료되었습니다")
