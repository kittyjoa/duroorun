"""회원/인증 - 비즈니스 로직."""

import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.r2 import delete_file, upload_file
from app.config import settings
from app.core.security import (
    add_to_blacklist,
    create_access_token,
    create_refresh_token,
    decode_token,
    decode_token_ignore_exp,
    delete_refresh_token,
    save_refresh_jti,
    verify_and_rotate_refresh,
)
from app.domain.course.models import Course
from app.domain.record.models import Record
from app.domain.user.models import ProviderType, SocialAccount, User

_KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_USER_URL = "https://kapi.kakao.com/v2/user/me"

_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


async def get_kakao_auth_url(redis: Redis) -> str:
    """카카오 OAuth 인증 URL을 생성하고 state를 Redis에 저장합니다."""
    state = secrets.token_urlsafe(32)
    try:
        await redis.setex(f"oauth:state:{state}", settings.OAUTH_STATE_EXPIRE_SECONDS, "1")
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
        ) from None
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
    try:
        deleted = await redis.delete(state_key)
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
        ) from None
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 state입니다",
        )

    try:
        async with httpx.AsyncClient(timeout=settings.OAUTH_API_TIMEOUT) as client:
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
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="카카오 토큰 발급에 실패했습니다",
                )
            kakao_access_token = token_res.json().get("access_token")
            if not kakao_access_token:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="카카오 토큰 발급에 실패했습니다",
                )

            user_res = await client.get(
                _KAKAO_USER_URL,
                headers={"Authorization": f"Bearer {kakao_access_token}"},
            )
            if user_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="카카오 유저 정보 조회에 실패했습니다",
                )
            user_info = user_res.json()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="카카오 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요",
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="카카오 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요",
        ) from None

    provider_uid = user_info.get("id")
    if not provider_uid:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="카카오 유저 정보 조회에 실패했습니다",
        )
    provider_uid = str(provider_uid)
    name = user_info.get("kakao_account", {}).get("name")

    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.provider_type == ProviderType.KAKAO,
            SocialAccount.provider_uid == provider_uid,
        )
    )
    social = result.scalar_one_or_none()

    is_new_user = social is None
    if is_new_user:
        try:
            user = User(name=name)
            db.add(user)
            await db.flush()
            db.add(SocialAccount(
                user_id=user.user_id,
                provider_type=ProviderType.KAKAO,
                provider_uid=provider_uid,
            ))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 연동된 소셜 계정입니다",
            ) from None
    else:
        result = await db.execute(select(User).where(User.user_id == social.user_id))
        user = result.scalar_one()

    access_token = create_access_token(user.user_id)
    refresh_token, refresh_jti = create_refresh_token(user.user_id)
    await save_refresh_jti(user.user_id, refresh_jti, redis)

    return access_token, refresh_token, is_new_user


async def refresh_tokens(refresh_token: str, redis: Redis) -> tuple[str, str]:
    """Refresh Token을 검증하고 새 Access Token + Refresh Token을 발급합니다."""
    payload = decode_token(refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="리프레시 토큰이 아닙니다",
        )

    user_id = int(payload["sub"])
    incoming_jti = payload.get("jti")
    if not incoming_jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다",
        )

    is_valid = await verify_and_rotate_refresh(user_id, incoming_jti, redis)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 탈취되었거나 만료되었습니다. 다시 로그인해주세요",
        )

    new_access_token = create_access_token(user_id)
    new_refresh_token, new_jti = create_refresh_token(user_id)
    await save_refresh_jti(user_id, new_jti, redis)

    return new_access_token, new_refresh_token


async def logout(access_token: str, redis: Redis) -> None:
    """Access Token을 블랙리스트에 등록하고 Refresh Token을 삭제합니다."""
    # 만료 토큰도 서명 검증 후 user_id 추출 — 쿠키 경로와 무관하게 항상 세션 삭제 보장
    payload = decode_token_ignore_exp(access_token)
    user_id = int(payload["sub"])
    jti = payload.get("jti")

    if jti:
        await add_to_blacklist(jti, redis)
    await delete_refresh_token(user_id, redis)


async def upload_profile_image(user: User, file: UploadFile, db: AsyncSession) -> str:
    """프로필 이미지를 R2에 업로드하고 기존 이미지는 삭제합니다."""
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지원하지 않는 이미지 형식입니다 (jpg, png, webp만 가능)",
        )

    file_bytes = await file.read()
    max_mb = settings.PROFILE_IMAGE_MAX_SIZE_MB
    if len(file_bytes) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이미지 크기는 최대 {max_mb}MB까지 업로드 가능합니다",
        )

    extension = _ALLOWED_IMAGE_TYPES[file.content_type]
    new_url = await upload_file(
        f"profile/{user.user_id}", file_bytes, extension, file.content_type
    )

    old_url = user.profile_image_url
    user.profile_image_url = new_url
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        # DB 저장 실패 시 방금 올린 새 파일이 고아로 남지 않도록 R2에서도 제거
        try:
            await delete_file(new_url)
        except ClientError:
            pass
        raise

    # 새 이미지 저장 확정 후에만 기존 이미지 삭제 — 실패해도 응답엔 영향 없음(고아 파일로만 남음)
    if old_url:
        try:
            await delete_file(old_url)
        except ClientError:
            pass

    return new_url


async def withdraw_user(user: User, access_token: str, db: AsyncSession, redis: Redis) -> None:
    """회원 탈퇴: 개인정보 익명화 + 소셜 계정 삭제 + 연관 데이터 익명화 (단일 트랜잭션)."""
    now = datetime.now(tz=UTC)

    old_profile_image_url = user.profile_image_url

    # row 삭제 없이 익명화 — 탈퇴 후에도 통계 집계에 계속 활용
    user.name = None
    user.nickname = None
    user.profile_image_url = None
    user.location = None
    user.deleted_at = now

    # 개인 식별 정보 즉시 파기
    await db.execute(delete(SocialAccount).where(SocialAccount.user_id == user.user_id))

    # Soft Delete이므로 DB 트리거 미발동 — 서비스 레이어에서 직접 NULL 처리
    await db.execute(update(Record).where(Record.user_id == user.user_id).values(user_id=None))

    # TODO: review 모델 구현 후 reviews 테이블 user_id NULL 업데이트 추가

    await db.execute(
        update(Course).where(Course.created_by == user.user_id).values(created_by=None)
    )

    await db.commit()

    # Redis 정리 실패해도 DB 탈퇴는 완료 — get_current_user가 deleted_at으로 차단하므로 정상 응답
    try:
        payload = decode_token(access_token)
        jti = payload.get("jti")
        if jti:
            await add_to_blacklist(jti, redis)
        await delete_refresh_token(user.user_id, redis)
    except RedisError:
        pass

    # R2 정리 실패해도 탈퇴는 완료 — DB에는 이미 NULL 처리됨(고아 파일로만 남음)
    if old_profile_image_url:
        try:
            await delete_file(old_profile_image_url)
        except ClientError:
            pass
