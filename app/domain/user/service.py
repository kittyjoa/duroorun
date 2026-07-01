"""회원/인증 - 비즈니스 로직."""

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, create_refresh_token, save_refresh_jti
from app.domain.user.models import ProviderType, SocialAccount, User

_KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_USER_URL = "https://kapi.kakao.com/v2/user/me"


async def get_kakao_auth_url(redis: Redis) -> str:
    """카카오 OAuth 인증 URL을 생성하고 state를 Redis에 저장합니다."""
    state = secrets.token_urlsafe(32)
    await redis.setex(f"oauth:state:{state}", 300, "1")
    params = urlencode({
        "client_id": settings.KAKAO_CLIENT_ID,
        "redirect_uri": settings.KAKAO_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    })
    return f"{_KAKAO_AUTH_URL}?{params}"


async def kakao_login(
    code: str, state: str, db: AsyncSession, redis: Redis
) -> tuple[str, str, bool]:
    """카카오 OAuth 콜백을 처리하고 (access_token, refresh_token, is_new_user)를 반환합니다."""
    # exists → delete 분리 시 레이스 컨디션 가능성이 있으므로 delete 결과로 한 번에 검증
    state_key = f"oauth:state:{state}"
    if await redis.delete(state_key) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="유효하지 않은 state입니다")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            token_res = await client.post(
                _KAKAO_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.KAKAO_CLIENT_ID,
                    "client_secret": settings.KAKAO_CLIENT_SECRET,
                    "redirect_uri": settings.KAKAO_REDIRECT_URI,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="카카오 토큰 발급에 실패했습니다")
            kakao_access_token = token_res.json().get("access_token")
            if not kakao_access_token:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="카카오 토큰 발급에 실패했습니다")

            user_res = await client.get(
                _KAKAO_USER_URL,
                headers={"Authorization": f"Bearer {kakao_access_token}"},
            )
            if user_res.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="카카오 유저 정보 조회에 실패했습니다")
            user_info = user_res.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="카카오 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요")
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="카카오 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요")

    provider_uid = user_info.get("id")
    if not provider_uid:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="카카오 유저 정보 조회에 실패했습니다")
    provider_uid = str(provider_uid)
    kakao_account = user_info.get("kakao_account", {})
    name = kakao_account.get("name")
    profile_image_url = kakao_account.get("profile", {}).get("profile_image_url")

    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.provider_type == ProviderType.KAKAO,
            SocialAccount.provider_uid == provider_uid,
        )
    )
    social = result.scalar_one_or_none()

    is_new_user = social is None
    if is_new_user:
        user = User(name=name, profile_image_url=profile_image_url)
        db.add(user)
        await db.flush()
        db.add(SocialAccount(
            user_id=user.user_id,
            provider_type=ProviderType.KAKAO,
            provider_uid=provider_uid,
        ))
    else:
        result = await db.execute(select(User).where(User.user_id == social.user_id))
        user = result.scalar_one()

    await db.commit()

    access_token = create_access_token(user.user_id)
    refresh_token, refresh_jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, refresh_jti, redis)

    return access_token, refresh_token, is_new_user
