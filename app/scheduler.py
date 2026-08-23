"""주기적 배치 작업 스케줄러 (FastAPI 앱 프로세스 안에서 실행).

ㅡ 싱글 프로세스 전제: docker-compose.yml의 backend는 uvicorn worker가 1개라
  스케줄러도 프로세스당 1개만 뜨는 걸 가정함. 나중에 워커나 컨테이너를
  여러 개로 늘리면 이 잡이 그만큼 중복 실행되니 그때는 별도 워커 프로세스로
  분리하거나 분산 락 추가 필요.
"""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clients.discord import send_discord_alert
from app.clients.durunubi import DurunubiAPIError
from app.config import settings
from app.scripts.seed_courses import seed_courses

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_JOB_ID = "seed_courses"
_MAX_ATTEMPTS = 3
# 1차 실패 후 1분, 2차 실패 후 5분 대기하고 재시도 (일시적 API/네트워크 blip 대응)
_RETRY_DELAYS_SECONDS = (60, 300)


async def _run_seed_courses_with_retry() -> None:
    """seed_courses()를 실행합니다.

    ㅡ DurunubiAPIError(네트워크/외부 API 계열, 일시적일 가능성이 높음)만 최대
      _MAX_ATTEMPTS회 재시도. 그 외 예외(코드 버그, DB 오류 등 재시도해도 같은
      결과가 나올 가능성이 높은 것들)는 재시도 없이 즉시 디스코드로 알림.
    ㅡ 다른 프로세스가 이미 시드 돌려서 락 못 잡으면, 예외 없이 정상 스킵(return)
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await seed_courses()
            return
        except DurunubiAPIError:
            logger.exception("두루누비 API 호출 실패 (시도 %d/%d)", attempt, _MAX_ATTEMPTS)
            if attempt == _MAX_ATTEMPTS:
                await send_discord_alert(
                    f"🚨 두루누비 코스 시드가 {_MAX_ATTEMPTS}회 재시도 후에도 "
                    "API 호출에 실패했습니다. 서버 로그(course_sync_logs)를 확인해주세요."
                )
                return
            await asyncio.sleep(_RETRY_DELAYS_SECONDS[attempt - 1])
        except Exception:
            logger.exception("두루누비 코스 시드 중 예상치 못한 오류 (재시도 없이 즉시 알림)")
            await send_discord_alert(
                "🚨 두루누비 코스 시드가 예상치 못한 오류로 실패했습니다(재시도 없이 즉시 알림). "
                "서버 로그(course_sync_logs)를 확인해주세요."
            )
            return


def start_scheduler() -> None:
    """앱 시작 시 스케줄러를 등록·기동합니다.

    ㅡ 매일 08:00(고정 시각)에 seed_courses()를 실행해 두루누비 코스 데이터를 최신화.
      두루누비 원본 데이터가 매일 오전 07:30 이후 동기화되는 점을 고려한 시각.
    ㅡ interval: 앱 기동 시점 기준으로 24시간마다 도는 거라 재시작할 때마다 실행 시각 밀림.
      cron(채택): 고정 시각 실행(신청서 동기화 계획에 맞추기 위해)
    ㅡ next_run_time: SEED_ON_STARTUP=true일 때만 기동 즉시 1회 실행.
      false면 이 인자를 아예 안 넘김. 트리거가 알아서 "다음 08:00"으로 계산.
    ㅡ 로컬 서버 켤때마다 API 호출되는 걸 막기 위해 기본값은 false.
      로컬에서 즉시실행 테스트하려면 .env에 SEED_ON_STARTUP=true로 켜면 됨.
    ㅡ replace_existing=True: 이미 같은 id로 등록된 job이 있어도 덮어씀
    ㅡ misfire_grace_time/coalesce: 서버 재시작 등으로 실행 시각을 놓쳐도
      1시간 이내면 뒤늦게라도 실행하되, 밀린 실행이 쌓여도 한 번만 실행.
    """
    job_kwargs = {"next_run_time": datetime.now()} if settings.SEED_ON_STARTUP else {}
    _scheduler.add_job(
        _run_seed_courses_with_retry,
        trigger=CronTrigger(hour=8, minute=0),
        id=_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        **job_kwargs,
    )
    _scheduler.start()
    logger.info(
        "코스 시드 스케줄러 시작 (매일 08:00, 기동 시 즉시 실행=%s)", settings.SEED_ON_STARTUP
    )


def shutdown_scheduler() -> None:
    """앱 종료 시 스케줄러를 정리합니다. 실행 중인 잡을 기다리지 않고 즉시 종료."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("코스 시드 스케줄러 종료")
