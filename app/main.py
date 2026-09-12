"""FastAPI 앱 진입점."""

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_router
from app.config import settings
from app.redis import close_redis
from app.scheduler import shutdown_scheduler, start_scheduler

# Windows 기본 이벤트 루프(ProactorEventLoop)는 psycopg async 드라이버와 호환되지 않음
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        await close_redis()


app = FastAPI(title="두루런 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
