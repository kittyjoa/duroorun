"""회원/인증 - 비즈니스 로직."""

import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select, update
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
    get_active_user,
    rotate_refresh_jti,
    save_refresh_jti,
)
from app.domain.course.models import Course
from app.domain.record.models import Record
from app.domain.review.models import Review
from app.domain.user.models import BannedAccount, ProviderType, SocialAccount, User

logger = logging.getLogger(__name__)

_KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_USER_URL = "https://kapi.kakao.com/v2/user/me"

_NAVER_AUTH_URL = "https://nid.naver.com/oauth2.0/authorize"
_NAVER_TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
_NAVER_USER_URL = "https://openapi.naver.com/v1/nid/me"

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USER_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_NICKNAME_PATTERN = re.compile(r"^[가-힣a-zA-Z0-9]+$")
_LOCATION_PATTERN = re.compile(r"^[가-힣a-zA-Z0-9\s]+$")

_LAST_LOGIN_UPDATE_THRESHOLD = timedelta(minutes=5)

# 신규 유저의 약관 동의 전 임시 가입정보(provider_type/provider_uid/name) 저장 키
_PENDING_SIGNUP_PREFIX = "pending_signup:"


@dataclass
class SocialLoginResult:
    """소셜 로그인 콜백 처리 결과.

    기존 유저면 access/refresh 토큰이 채워지고, 신규 유저면 계정을 만들지 않은 채
    signup_token만 채워진다 (약관 동의 + 프로필 입력 후 complete_signup()에서 실제 생성).
    """

    access_token: str | None = None
    refresh_token: str | None = None
    signup_token: str | None = None


def _validate_nickname(nickname: str) -> str:
    nickname = nickname.strip()
    valid_length = settings.NICKNAME_MIN_LENGTH <= len(nickname) <= settings.NICKNAME_MAX_LENGTH
    if not valid_length or not _NICKNAME_PATTERN.match(nickname):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"닉네임은 한글/영문/숫자 {settings.NICKNAME_MIN_LENGTH}"
                f"~{settings.NICKNAME_MAX_LENGTH}자로 입력해주세요"
            ),
        )
    return nickname


def _validate_location(location: str) -> str:
    location = location.strip()
    valid_length = 1 <= len(location) <= settings.LOCATION_MAX_LENGTH
    if not valid_length or not _LOCATION_PATTERN.match(location):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"거주지는 한글/영문/숫자 1~{settings.LOCATION_MAX_LENGTH}자로 입력해주세요",
        )
    return location


async def _touch_last_login(user_id: int, db: AsyncSession) -> None:
    """로그인/토큰 재발급 시 last_login_at을 갱신합니다.

    - 통계용 부가 작업이라 실패해도 로그인/재발급 자체를 막지 않도록 예외를 흡수한다.
    - 최근 _LAST_LOGIN_UPDATE_THRESHOLD(5분) 이내에 이미 갱신됐으면 쓰기를 생략한다.
      Access Token 만료 주기(30분)는 이 임계값보다 길어서 정상적인 재발급 주기 자체는
      막지 못하고, 다중 탭·재시도 등으로 짧은 간격에 몰리는 중복 write만 걸러진다.
    """
    now = datetime.now(UTC)
    try:
        await db.execute(
            update(User)
            .where(
                User.user_id == user_id,
                or_(
                    User.last_login_at.is_(None),
                    User.last_login_at < now - _LAST_LOGIN_UPDATE_THRESHOLD,
                ),
            )
            .values(last_login_at=now)
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("last_login_at 갱신 실패: user_id=%s", user_id)


async def _check_not_banned(
    provider_type: ProviderType, provider_uid: str, db: AsyncSession
) -> None:
    """강제 탈퇴로 차단된 소셜 계정인지 확인합니다. 신규 가입 직전에만 호출."""
    result = await db.execute(
        select(BannedAccount).where(
            BannedAccount.provider_type == provider_type,
            BannedAccount.provider_uid == provider_uid,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="강제 탈퇴 처리된 계정으로는 재가입할 수 없습니다",
        )


async def _finish_social_login(
    provider_type: ProviderType, provider_uid: str, name: str | None, db: AsyncSession, redis: Redis
) -> SocialLoginResult:
    """provider_uid로 기존/신규 유저를 판별해 로그인을 마무리합니다.

    기존 유저는 바로 토큰을 발급하지만, 신규 유저는 약관 동의 전이므로 계정을 만들지
    않는다 — 대신 가입정보를 Redis에 잠깐(PENDING_SIGNUP_EXPIRE_SECONDS) 저장해두고
    signup_token만 돌려준다. 이 값은 이후 complete_signup()에서 약관 동의 + 닉네임/거주지와
    함께 와야 실제 User/SocialAccount row가 생성된다 (동의 안 하고 이탈하면 TTL로 자동 소멸).
    """
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.provider_type == provider_type,
            SocialAccount.provider_uid == provider_uid,
        )
    )
    social = result.scalar_one_or_none()

    if social is None:
        await _check_not_banned(provider_type, provider_uid, db)
        signup_token = secrets.token_urlsafe(32)
        payload = json.dumps({
            "provider_type": provider_type.value,
            "provider_uid": provider_uid,
            "name": name,
        })
        try:
            await redis.setex(
                f"{_PENDING_SIGNUP_PREFIX}{signup_token}",
                settings.PENDING_SIGNUP_EXPIRE_SECONDS,
                payload,
            )
        except RedisError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
            ) from None
        return SocialLoginResult(signup_token=signup_token)

    result = await db.execute(select(User).where(User.user_id == social.user_id))
    user = result.scalar_one()

    # _touch_last_login 내부에서 rollback이 나면 이 세션에 속한 user 객체의 속성이
    # 전부 만료되어, 이후 user.user_id처럼 다시 접근하는 순간 동기 컨텍스트에서 지연 로딩이
    # 시도되며 MissingGreenlet 에러로 이어질 수 있음 — 정수로 미리 꺼내 그 위험을 없앤다.
    user_id = user.user_id
    await _touch_last_login(user_id, db)

    access_token = create_access_token(user_id)
    refresh_token, refresh_jti = create_refresh_token(user_id)
    await save_refresh_jti(user_id, refresh_jti, redis)

    return SocialLoginResult(access_token=access_token, refresh_token=refresh_token)


def _has_valid_image_signature(content_type: str, file_bytes: bytes) -> bool:
    """Content-Type 헤더는 위조 가능하므로 실제 파일 시그니처(매직넘버)로 재검증합니다."""
    if content_type == "image/jpeg":
        return file_bytes.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return file_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP"
    return False


async def get_kakao_auth_url(redis: Redis) -> tuple[str, str]:
    """카카오 OAuth 인증 URL을 생성하고 state를 Redis에 저장합니다. (url, state)를 반환합니다."""
    state = secrets.token_urlsafe(32)
    try:
        await redis.setex(f"oauth:state:kakao:{state}", settings.OAUTH_STATE_EXPIRE_SECONDS, "1")
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
    return f"{_KAKAO_AUTH_URL}?{params}", state


async def kakao_login(
    code: str, state: str, cookie_state: str | None, db: AsyncSession, redis: Redis
) -> SocialLoginResult:
    """카카오 OAuth 콜백을 처리합니다."""
    # 콜백을 받은 브라우저가 로그인을 시작한 브라우저와 같은지 먼저 확인 (로그인 CSRF 방지)
    if not cookie_state or cookie_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 요청입니다",
        )

    # exists → delete 분리 시 레이스 컨디션 가능성이 있으므로 delete 결과로 한 번에 검증
    state_key = f"oauth:state:kakao:{state}"
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

    return await _finish_social_login(ProviderType.KAKAO, provider_uid, name, db, redis)


async def get_naver_auth_url(redis: Redis) -> tuple[str, str]:
    """네이버 OAuth 인증 URL을 생성하고 state를 Redis에 저장합니다. (url, state)를 반환합니다."""
    state = secrets.token_urlsafe(32)
    try:
        await redis.setex(f"oauth:state:naver:{state}", settings.OAUTH_STATE_EXPIRE_SECONDS, "1")
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
        ) from None
    params = urlencode({
        "client_id": settings.NAVER_CLIENT_ID,
        "redirect_uri": settings.NAVER_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    })
    return f"{_NAVER_AUTH_URL}?{params}", state


async def naver_login(
    code: str, state: str, cookie_state: str | None, db: AsyncSession, redis: Redis
) -> SocialLoginResult:
    """네이버 OAuth 콜백을 처리합니다."""
    # 콜백을 받은 브라우저가 로그인을 시작한 브라우저와 같은지 먼저 확인 (로그인 CSRF 방지)
    if not cookie_state or cookie_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 요청입니다",
        )

    # exists → delete 분리 시 레이스 컨디션 가능성이 있으므로 delete 결과로 한 번에 검증
    state_key = f"oauth:state:naver:{state}"
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
                _NAVER_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.NAVER_CLIENT_ID,
                    "client_secret": settings.NAVER_CLIENT_SECRET,
                    "redirect_uri": settings.NAVER_REDIRECT_URI,
                    "code": code,
                    "state": state,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="네이버 토큰 발급에 실패했습니다",
                )
            naver_access_token = token_res.json().get("access_token")
            if not naver_access_token:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="네이버 토큰 발급에 실패했습니다",
                )

            user_res = await client.get(
                _NAVER_USER_URL,
                headers={"Authorization": f"Bearer {naver_access_token}"},
            )
            if user_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="네이버 유저 정보 조회에 실패했습니다",
                )
            user_info = user_res.json()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="네이버 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요",
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="네이버 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요",
        ) from None

    if user_info.get("resultcode") != "00":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="네이버 유저 정보 조회에 실패했습니다",
        )

    naver_response = user_info.get("response") or {}
    provider_uid = naver_response.get("id")
    if not provider_uid:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="네이버 유저 정보 조회에 실패했습니다",
        )
    provider_uid = str(provider_uid)
    name = naver_response.get("name")

    return await _finish_social_login(ProviderType.NAVER, provider_uid, name, db, redis)


async def get_google_auth_url(redis: Redis) -> tuple[str, str]:
    """구글 OAuth 인증 URL을 생성하고 state를 Redis에 저장합니다. (url, state)를 반환합니다."""
    state = secrets.token_urlsafe(32)
    try:
        await redis.setex(f"oauth:state:google:{state}", settings.OAUTH_STATE_EXPIRE_SECONDS, "1")
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
        ) from None
    params = urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
    })
    return f"{_GOOGLE_AUTH_URL}?{params}", state


async def google_login(
    code: str, state: str, cookie_state: str | None, db: AsyncSession, redis: Redis
) -> SocialLoginResult:
    """구글 OAuth 콜백을 처리합니다."""
    # 콜백을 받은 브라우저가 로그인을 시작한 브라우저와 같은지 먼저 확인 (로그인 CSRF 방지)
    if not cookie_state or cookie_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 요청입니다",
        )

    # exists → delete 분리 시 레이스 컨디션 가능성이 있으므로 delete 결과로 한 번에 검증
    state_key = f"oauth:state:google:{state}"
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
                _GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="구글 토큰 발급에 실패했습니다",
                )
            google_access_token = token_res.json().get("access_token")
            if not google_access_token:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="구글 토큰 발급에 실패했습니다",
                )

            user_res = await client.get(
                _GOOGLE_USER_URL,
                headers={"Authorization": f"Bearer {google_access_token}"},
            )
            if user_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="구글 유저 정보 조회에 실패했습니다",
                )
            user_info = user_res.json()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="구글 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요",
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="구글 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요",
        ) from None

    provider_uid = user_info.get("sub")
    if not provider_uid:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="구글 유저 정보 조회에 실패했습니다",
        )
    provider_uid = str(provider_uid)
    name = user_info.get("name")

    return await _finish_social_login(ProviderType.GOOGLE, provider_uid, name, db, redis)


async def complete_signup(
    signup_token: str,
    agree_terms: bool,
    nickname: str,
    location: str,
    db: AsyncSession,
    redis: Redis,
) -> tuple[str, str]:
    """약관 동의 + 닉네임/거주지를 받아 대기 중이던 신규 계정을 실제로 생성합니다.

    signup_token은 소셜 로그인 최초 시도(callback) 시 Redis에 잠깐 저장해둔 가입정보의
    열쇠 — 1회용이라 성공하면 즉시 삭제하고, TTL이 지났으면 처음부터 다시 로그인해야 한다.
    """
    if not agree_terms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이용약관 및 개인정보처리방침에 동의해야 가입할 수 있습니다",
        )

    key = f"{_PENDING_SIGNUP_PREFIX}{signup_token}"
    try:
        raw = await redis.get(key)
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
        ) from None
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="가입 세션이 만료되었습니다. 처음부터 다시 로그인해주세요",
        )

    try:
        await redis.delete(key)
    except RedisError:
        pass  # 삭제 실패해도 TTL로 자동 정리되므로 가입 자체는 계속 진행

    pending = json.loads(raw)
    provider_type = ProviderType(pending["provider_type"])
    provider_uid = pending["provider_uid"]
    name = pending["name"]

    nickname = _validate_nickname(nickname)
    location = _validate_location(location)

    await _check_not_banned(provider_type, provider_uid, db)

    try:
        user = User(
            name=name,
            nickname=nickname,
            location=location,
            terms_agreed_at=datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        db.add(SocialAccount(
            user_id=user.user_id,
            provider_type=provider_type,
            provider_uid=provider_uid,
        ))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 닉네임이거나 이미 연동된 소셜 계정입니다",
        ) from None

    user_id = user.user_id
    await _touch_last_login(user_id, db)

    access_token = create_access_token(user_id)
    refresh_token, refresh_jti = create_refresh_token(user_id)
    await save_refresh_jti(user_id, refresh_jti, redis)

    return access_token, refresh_token


async def refresh_tokens(refresh_token: str, db: AsyncSession, redis: Redis) -> tuple[str, str]:
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

    # 탈퇴한 유저는 Redis에 옛 refresh token이 남아있어도(정리 실패 등) 재발급을 거부한다
    if await get_active_user(user_id, db) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="탈퇴했거나 존재하지 않는 사용자입니다",
        )

    new_access_token = create_access_token(user_id)
    new_refresh_token, new_jti = create_refresh_token(user_id)

    # 검증(GET)과 교체(SET)를 원자적으로 처리 — 동시 재발급 요청 간 경쟁 조건 방지
    is_valid = await rotate_refresh_jti(user_id, incoming_jti, new_jti, redis)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 탈취되었거나 만료되었습니다. 다시 로그인해주세요",
        )

    await _touch_last_login(user_id, db)

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


async def get_public_profile(user_id: int, db: AsyncSession) -> User:
    """다른 유저의 공개 프로필 정보를 조회합니다. 탈퇴했거나 없는 유저는 404."""
    user = await get_active_user(user_id, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 사용자입니다",
        )
    return user


async def update_profile(
    user: User, nickname: str | None, location: str | None, db: AsyncSession
) -> User:
    """닉네임/거주지를 수정합니다 (마이페이지)."""
    if nickname is not None:
        user.nickname = _validate_nickname(nickname)

    if location is not None:
        user.location = _validate_location(location)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 닉네임입니다",
        ) from None

    await db.refresh(user)
    return user


async def upload_profile_image(user: User, file: UploadFile, db: AsyncSession) -> str:
    """프로필 이미지를 R2에 업로드하고 기존 이미지는 삭제합니다."""
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지원하지 않는 이미지 형식입니다 (jpg, png, webp만 가능)",
        )

    max_mb = settings.PROFILE_IMAGE_MAX_SIZE_MB
    max_bytes = max_mb * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이미지 크기는 최대 {max_mb}MB까지 업로드 가능합니다",
        )

    if not _has_valid_image_signature(file.content_type, file_bytes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="파일 내용이 올바른 이미지 형식이 아닙니다",
        )

    extension = _ALLOWED_IMAGE_TYPES[file.content_type]
    try:
        new_url = await upload_file(
            f"profile/{user.user_id}", file_bytes, extension, file.content_type
        )
    except (ClientError, BotoCoreError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="이미지 업로드에 실패했습니다. 잠시 후 다시 시도해주세요",
        ) from None

    old_url = user.profile_image_url
    user.profile_image_url = new_url
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        # DB 저장 실패 시 방금 올린 새 파일이 고아로 남지 않도록 R2에서도 제거
        try:
            await delete_file(new_url)
        except (ClientError, BotoCoreError):
            logger.warning("고아 파일 정리 실패 (R2): user_id=%s, url=%s", user.user_id, new_url)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이미지 저장에 실패했습니다. 잠시 후 다시 시도해주세요",
        ) from None

    # 새 이미지 저장 확정 후에만 기존 이미지 삭제 — 실패해도 응답엔 영향 없음(고아 파일로만 남음)
    if old_url:
        try:
            await delete_file(old_url)
        except (ClientError, BotoCoreError):
            logger.warning("기존 이미지 정리 실패 (R2): user_id=%s, url=%s", user.user_id, old_url)

    return new_url


async def delete_profile_image(user: User, db: AsyncSession) -> None:
    """프로필 이미지를 기본 이미지로 되돌립니다 (DB를 NULL로 먼저 커밋한 뒤 R2 파일 삭제)."""
    old_url = user.profile_image_url
    if not old_url:
        return

    user.profile_image_url = None
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이미지 삭제에 실패했습니다. 잠시 후 다시 시도해주세요",
        ) from None

    # DB 반영 확정 후에만 R2에서 삭제 — 순서가 반대면 R2는 지워졌는데 DB엔 깨진 URL이 남는
    # 상황이 생길 수 있음. 이 쪽은 실패해도 응답엔 영향 없음(고아 파일로만 남음).
    try:
        await delete_file(old_url)
    except (ClientError, BotoCoreError):
        logger.warning("기존 이미지 정리 실패 (R2): user_id=%s, url=%s", user.user_id, old_url)


async def _anonymize_user_data(user: User, db: AsyncSession) -> str | None:
    """탈퇴 공통 처리: 개인정보 익명화 + 소셜 계정 삭제 + 연관 데이터 익명화.

    commit은 호출자가 수행 (강제 탈퇴 시 banned_accounts 기록과 같은 트랜잭션으로 묶기 위함).
    반환값은 삭제 전 프로필 이미지 URL (R2 정리용).
    """
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

    await db.execute(update(Review).where(Review.user_id == user.user_id).values(user_id=None))

    await db.execute(
        update(Course).where(Course.created_by == user.user_id).values(created_by=None)
    )

    return old_profile_image_url


async def withdraw_user(user: User, access_token: str, db: AsyncSession, redis: Redis) -> None:
    """회원 탈퇴(본인) - 단일 트랜잭션 처리."""
    old_profile_image_url = await _anonymize_user_data(user, db)
    await db.commit()

    # Redis 정리 실패해도 DB 탈퇴는 완료 — get_current_user가 deleted_at으로 차단하므로 정상 응답
    try:
        payload = decode_token(access_token)
        jti = payload.get("jti")
        if jti:
            await add_to_blacklist(jti, redis)
        await delete_refresh_token(user.user_id, redis)
    except RedisError:
        logger.warning("탈퇴 시 refresh token 정리 실패 (Redis): user_id=%s", user.user_id)

    # R2 정리 실패해도 탈퇴는 완료 — DB에는 이미 NULL 처리됨(고아 파일로만 남음)
    if old_profile_image_url:
        try:
            await delete_file(old_profile_image_url)
        except (ClientError, BotoCoreError):
            logger.warning(
                "탈퇴 시 프로필 이미지 정리 실패 (R2): user_id=%s, url=%s",
                user.user_id,
                old_profile_image_url,
            )


async def force_withdraw_user(
    user: User, admin_id: int, reason: str, db: AsyncSession, redis: Redis
) -> None:
    """유저 강제 탈퇴(관리자) - 단일 트랜잭션 처리.

    본인 탈퇴와 달리 access_token이 없어 블랙리스트 등록은 생략하고, 재가입 방지를 위해
    social_accounts를 하드 삭제하기 전에 provider 정보를 banned_accounts에 기록한다.
    admin_id는 밴 목록에서 동일 사유/날짜의 밴을 구분하고 누가 처리했는지 감사하기 위함.
    """
    result = await db.execute(select(SocialAccount).where(SocialAccount.user_id == user.user_id))
    social = result.scalar_one_or_none()

    # 익명화로 지워지기 전에 닉네임을 캡처 - 밴 목록에서 관리자가 식별할 수 있게 하기 위함
    nickname_before_anonymize = user.nickname

    old_profile_image_url = await _anonymize_user_data(user, db)

    if social is not None:
        db.add(BannedAccount(
            provider_type=social.provider_type,
            provider_uid=social.provider_uid,
            reason=reason,
            banned_by=admin_id,
            banned_nickname=nickname_before_anonymize,
        ))

    await db.commit()

    # Redis 정리 실패해도 DB 탈퇴는 완료
    try:
        await delete_refresh_token(user.user_id, redis)
    except RedisError:
        logger.warning("강제 탈퇴 시 refresh token 정리 실패 (Redis): user_id=%s", user.user_id)

    # R2 정리 실패해도 탈퇴는 완료 — DB에는 이미 NULL 처리됨(고아 파일로만 남음)
    if old_profile_image_url:
        try:
            await delete_file(old_profile_image_url)
        except (ClientError, BotoCoreError):
            logger.warning(
                "강제 탈퇴 시 프로필 이미지 정리 실패 (R2): user_id=%s, url=%s",
                user.user_id,
                old_profile_image_url,
            )
