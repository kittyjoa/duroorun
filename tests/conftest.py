"""pytest 공용 픽스처.

실제 DB/Redis(docker-compose의 db, redis 서비스)를 그대로 사용하고, Gemini 호출만
테스트 안에서 mock 처리한다 - 실제 API 비용/네트워크 의존 없이 빠르고 결정적으로
검증하기 위함. 테스트마다 코스를 새로 만들고 끝나면 관련 데이터를 전부 정리한다.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.domain.course.models import Course, CourseType
from app.domain.record.models import Record
from app.domain.review.models import Review, ReviewSummary
from app.domain.user.models import User


@dataclass
class ReviewTestCourse:
    """테스트용 코스 하나 + 그 코스에 리뷰를 달며 생성된 유저 id 목록(정리용)."""

    course_id: int
    user_ids: list[int] = field(default_factory=list)


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def review_test_course(db_session):
    """리뷰 테스트용 커스텀 코스를 만들고, 종료 후 요약/리뷰/기록/유저/코스를 정리한다."""
    course = Course(
        course_type=CourseType.CUSTOM,
        course_name=f"pytest-course-{uuid.uuid4().hex[:8]}",
        distance=5.0,
        difficulty="NORMAL",
        estimated_time=60,
        start_lat=1.0,
        start_lng=1.0,
        end_lat=2.0,
        end_lng=2.0,
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    ctx = ReviewTestCourse(course_id=course.course_id)
    yield ctx

    await db_session.execute(delete(ReviewSummary).where(ReviewSummary.course_id == ctx.course_id))
    await db_session.execute(delete(Review).where(Review.course_id == ctx.course_id))
    if ctx.user_ids:
        await db_session.execute(delete(Record).where(Record.user_id.in_(ctx.user_ids)))
        await db_session.execute(delete(User).where(User.user_id.in_(ctx.user_ids)))
    await db_session.execute(delete(Course).where(Course.course_id == ctx.course_id))
    await db_session.commit()


async def add_completed_reviews(db_session, ctx: ReviewTestCourse, count: int) -> None:
    """완주 기록 + 리뷰를 count개 만들어 코스에 추가한다 (각각 다른 유저)."""
    for _ in range(count):
        user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
        db_session.add(user)
        await db_session.flush()
        ctx.user_ids.append(user.user_id)

        db_session.add(
            Record(
                user_id=user.user_id,
                course_id=ctx.course_id,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                user_start_lat=1.0,
                user_start_lng=1.0,
                user_end_lat=2.0,
                user_end_lng=2.0,
                duration_seconds=600,
                is_completed=True,
            )
        )
        db_session.add(
            Review(
                user_id=user.user_id,
                course_id=ctx.course_id,
                content=f"pytest 리뷰 내용 {uuid.uuid4().hex[:8]}",
                difficulty="NORMAL",
            )
        )

    await db_session.commit()
