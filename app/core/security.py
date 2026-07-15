"""JWT 발급/검증, Refresh 로테이션, 블랙리스트."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.domain.user.models import User, UserRole
from app.redis import get_redis

bearer_scheme = HTTPBearer()


def _now() -> datetime:
    """현재 UTC 시각을 반환합니다."""
    return datetime.now(tz=UTC)


# ──────────────────────────────────────────
# 토큰 발급
# ──────────────────────────────────────────

def create_access_token(user_id: int) -> str:
    """Access Token(30분)을 발급합니다."""
    jti = str(uuid.uuid4())
    expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "jti": jti, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str]:
    """Refresh Token(14일)과 jti를 함께 반환합니다. (token, jti)"""
    jti = str(uuid.uuid4())
    expire = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "jti": jti, "exp": expire, "type": "refresh"}
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    """JWT를 디코딩하고 payload를 반환합니다."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다",
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다",
        ) from None


def decode_token_ignore_exp(token: str) -> dict:
    """만료 여부와 무관하게 JWT payload를 반환합니다 (로그아웃 전용)."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다",
        ) from None


# ──────────────────────────────────────────
# Redis — Access 블랙리스트
# ──────────────────────────────────────────

async def add_to_blacklist(jti: str, redis: Redis) -> None:
    """로그아웃된 Access Token jti를 블랙리스트에 등록합니다."""
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    await redis.setex(f"blacklist:{jti}", ttl, "1")


async def is_blacklisted(jti: str, redis: Redis) -> bool:
    """Access Token이 블랙리스트에 등록되어 있는지 확인합니다."""
    return await redis.exists(f"blacklist:{jti}") == 1


# ──────────────────────────────────────────
# Redis — Refresh Token (jti만 저장, 유저당 1개)
# ──────────────────────────────────────────

async def save_refresh_jti(user_id: int, jti: str, redis: Redis) -> None:
    """Refresh Token jti를 Redis에 저장합니다 (재발급 시 덮어써서 로테이션)."""
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.setex(f"refresh:{user_id}", ttl, jti)


async def verify_and_rotate_refresh(user_id: int, incoming_jti: str, redis: Redis) -> bool:
    """Refresh Token jti를 검증합니다. 불일치 시 즉시 삭제(탈취 방어)하고 False를 반환합니다."""
    stored_jti = await redis.get(f"refresh:{user_id}")
    if stored_jti != incoming_jti:
        await redis.delete(f"refresh:{user_id}")
        return False
    return True


async def delete_refresh_token(user_id: int, redis: Redis) -> None:
    """Refresh Token을 Redis에서 삭제합니다 (로그아웃/탈퇴 시 사용)."""
    await redis.delete(f"refresh:{user_id}")


# ──────────────────────────────────────────
# FastAPI 의존성 — 다른 도메인에서 import해서 씀
# ──────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> User:
    """Authorization 헤더의 Access Token을 검증하고 활성 유저를 반환합니다."""
    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="액세스 토큰이 아닙니다",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다",
        )
    if await is_blacklisted(jti, redis):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그아웃된 토큰입니다",
        )

    user_id = int(payload["sub"])
    result = await db.execute(
        select(User).where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="존재하지 않거나 탈퇴한 계정입니다",
        )

    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """관리자 권한을 검증합니다."""
    if user.user_role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user
