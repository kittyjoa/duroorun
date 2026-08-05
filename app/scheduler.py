"""주기적 배치 작업 스케줄러 (FastAPI 앱 프로세스 안에서 실행).

ㅡ 싱글 프로세스 전제: docker-compose.yml의 backend는 uvicorn worker가 1개라
  스케줄러도 프로세스당 1개만 뜨는 걸 가정함. 나중에 워커나 컨테이너를
  여러 개로 늘리면 이 잡이 그만큼 중복 실행되니 그때는 별도 워커 프로세스로
  분리하거나 분산 락 추가 필요.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.scripts.seed_courses import seed_courses

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_JOB_ID = "seed_courses"


def start_scheduler() -> None:
    """앱 시작 시 스케줄러를 등록·기동합니다.

    ㅡ 24시간 주기로 seed_courses()를 재실행해 두루누비 코스 데이터를 최신화.
    ㅡ next_run_time=now: 앱 기동 시점에 1회 즉시 실행 후 24시간 주기로 반복
      (배포 직후부터 최신 데이터가 반영되도록).
    ㅡ misfire_grace_time/coalesce: 서버 재시작 등으로 실행 시각을 놓쳐도
      1시간 이내면 뒤늦게라도 실행하되, 밀린 실행이 쌓여도 한 번만 실행.
    """
    _scheduler.add_job(
        seed_courses,
        trigger="interval",
        hours=24,
        id=_JOB_ID,
        next_run_time=datetime.now(),
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("코스 시드 스케줄러 시작 (24시간 주기, 기동 시 1회 즉시 실행)")


def shutdown_scheduler() -> None:
    """앱 종료 시 스케줄러를 정리합니다. 실행 중인 잡을 기다리지 않고 즉시 종료."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("코스 시드 스케줄러 종료")
