"""디스코드 웹훅 알림 클라이언트."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0


async def send_discord_alert(message: str) -> None:
    """디스코드 웹훅으로 메시지를 보냅니다.

    ㅡ 웹훅 전송 자체가 실패해도 호출부 로직에 영향 주지 않도록 예외를 삼키고 로그
    """
    if not settings.DISCORD_WEBHOOK_URL:
        logger.warning(
            "DISCORD_WEBHOOK_URL이 설정되지 않아 알림을 보내지 못했습니다: %s", message
        )
        return
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(settings.DISCORD_WEBHOOK_URL, json={"content": message})
            res.raise_for_status()
    except httpx.HTTPError:
        logger.exception("디스코드 알림 전송 실패")
