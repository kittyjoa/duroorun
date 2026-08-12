"""주기적 배치 작업 스케줄러 (FastAPI 앱 프로세스 안에서 실행).

ㅡ 싱글 프로세스 전제: docker-compose.yml의 backend는 uvicorn worker가 1개라
  스케줄러도 프로세스당 1개만 뜨는 걸 가정함. 나중에 워커나 컨테이너를
  여러 개로 늘리면 이 잡이 그만큼 중복 실행되니 그때는 별도 워커 프로세스로
  분리하거나 분산 락 추가 필요.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.scripts.seed_courses import seed_courses

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_JOB_ID = "seed_courses"


def start_scheduler() -> None:
    """앱 시작 시 스케줄러를 등록·기동합니다.

    ㅡ 24시간 주기로 seed_courses()를 재실행해 두루누비 코스 데이터를 최신화.
    ㅡ next_run_time: SEED_ON_STARTUP=true일 때만 기동 즉시 1회 실행. false면 이 인자를
      아예 안 넘김. 트리거가 알아서 "24시간 뒤 첫 실행"으로 계산.
    ㅡ 로컬 서버 켤때마다 API 호출되는 걸 막기 위해 기본값은 false.
      로컬에서 즉시실행 테스트하려면 .env에 SEED_ON_STARTUP=true로 켜면 됨.
    ㅡ replace_existing=True: 이미 같은 id로 등록된 job이 있어도 덮어씀
    ㅡ misfire_grace_time/coalesce: 서버 재시작 등으로 실행 시각을 놓쳐도
      1시간 이내면 뒤늦게라도 실행하되, 밀린 실행이 쌓여도 한 번만 실행.
    """
    job_kwargs = {"next_run_time": datetime.now()} if settings.SEED_ON_STARTUP else {}
    _scheduler.add_job(
        seed_courses,
        trigger="interval",
        hours=24,
        id=_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        **job_kwargs,
    )
    _scheduler.start()
    logger.info(
        "코스 시드 스케줄러 시작 (24시간 주기, 기동 시 즉시 실행=%s)", settings.SEED_ON_STARTUP
    )


def shutdown_scheduler() -> None:
    """앱 종료 시 스케줄러를 정리합니다. 실행 중인 잡을 기다리지 않고 즉시 종료."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("코스 시드 스케줄러 종료")
