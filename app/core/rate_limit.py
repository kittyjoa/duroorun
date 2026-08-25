"""Redis 기반 요청 횟수 제한 (fixed window).

유저별로 window_seconds 동안 max_requests번까지만 허용한다. Redis 장애 시에는
제한 기능 때문에 서비스 전체가 막히지 않도록 그냥 통과시킨다.
"""

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.security import get_current_user
from app.domain.user.models import User
from app.redis import get_redis


async def check_rate_limit(redis: Redis, key: str, max_requests: int) -> None:
    """한도를 이미 넘었으면 429를 던집니다. 카운터는 늘리지 않습니다."""
    try:
        count = await redis.get(key)
    except RedisError:
        return
    if count is not None and int(count) >= max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요",
        )


async def record_rate_limit_hit(redis: Redis, key: str, window_seconds: int) -> None:
    """카운터를 1 늘립니다. 새로 생기는 키면 만료시간을 같이 겁니다."""
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except RedisError:
        pass


def rate_limit_per_request(key_prefix: str, max_requests: int, window_seconds: int):
    """요청이 들어올 때마다(성공/실패 무관) 무조건 카운트하는 의존성을 만듭니다."""

    async def _dependency(
        user: User = Depends(get_current_user),
        redis: Redis = Depends(get_redis),
    ) -> None:
        key = f"ratelimit:{key_prefix}:{user.user_id}"
        await check_rate_limit(redis, key, max_requests)
        await record_rate_limit_hit(redis, key, window_seconds)

    return _dependency
