"""마이페이지 - 내가 쓴 리뷰 목록(GET /reviews/mine) 조회 테스트."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.domain.course.models import Course, CourseType
from app.domain.record.models import Record
from app.domain.review.models import Review, ReviewImage
from app.domain.review.service import get_my_reviews
from app.domain.user.models import User
from tests.conftest import add_completed_reviews


async def test_get_my_reviews_includes_course_name_type_and_images(db_session, review_test_course):
    """리뷰(이미지 포함)가 있는 유저로 조회하면 코스명·코스 타입·이미지가 정상적으로 채워진다."""
    await add_completed_reviews(db_session, review_test_course, count=1)
    user_id = review_test_course.user_ids[0]

    # Review.review_id만 컬럼으로 가져온다 - 엔티티 전체(select(Review))를 먼저 불러오면
    # 이 시점에 비어있는 images가 세션 identity map에 캐싱돼, 아래에서 이미지를 추가해도
    # get_my_reviews가 같은 세션 안에서 그 캐시된(옛) 빈 목록을 재사용해버린다.
    review_id = await db_session.scalar(
        select(Review.review_id).where(Review.course_id == review_test_course.course_id)
    )
    db_session.add(ReviewImage(review_id=review_id, image_url="https://example.com/a.jpg"))
    await db_session.commit()

    result = await get_my_reviews(session=db_session, user_id=user_id, page=1, size=20)

    assert result.total == 1
    assert len(result.items) == 1
    item = result.items[0]
    assert item.course_id == review_test_course.course_id
    assert item.course_name
    assert item.course_type == CourseType.CUSTOM
    assert len(item.images) == 1
    assert item.images[0].image_url == "https://example.com/a.jpg"


async def test_get_my_reviews_includes_drnb_course_type(db_session):
    """CUSTOM뿐 아니라 두루누비 공식 코스(DRNB) 리뷰도 course_type이 정상적으로 채워진다."""
    course = Course(
        course_type=CourseType.DRNB,
        course_name=f"pytest-drnb-course-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    user = User(nickname=f"pytest-user-{uuid.uuid4().hex[:12]}")
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        Record(
            user_id=user.user_id,
            course_id=course.course_id,
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
            course_id=course.course_id,
            content=f"pytest 리뷰 내용 {uuid.uuid4().hex[:8]}",
            difficulty="NORMAL",
        )
    )
    await db_session.commit()

    try:
        result = await get_my_reviews(session=db_session, user_id=user.user_id, page=1, size=20)

        assert result.total == 1
        assert result.items[0].course_type == CourseType.DRNB
    finally:
        await db_session.execute(delete(Review).where(Review.course_id == course.course_id))
        await db_session.execute(delete(Record).where(Record.user_id == user.user_id))
        await db_session.execute(delete(User).where(User.user_id == user.user_id))
        await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
        await db_session.commit()


async def test_get_my_reviews_pagination_does_not_overlap(db_session):
    """size보다 리뷰가 많을 때 페이지끼리 겹치거나 순서(최신순)가 어긋나지 않는다.

    created_at은 DB server_default=func.now()라 같은 트랜잭션 안에서 한꺼번에 insert하면
    타임스탬프가 전부 같아질 수 있다 - 순서를 확실히 검증하기 위해 명시적으로 다르게 준다.
    """
    owner = User(nickname=f"pytest-owner-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()

    courses = []
    reviews = []
    base_time = datetime.now(UTC)
    for i in range(4):
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
        await db_session.flush()
        courses.append(course)

        review = Review(
            user_id=owner.user_id,
            course_id=course.course_id,
            content=f"pytest 리뷰 {i}",
            difficulty="NORMAL",
            created_at=base_time + timedelta(seconds=i),
        )
        db_session.add(review)
        reviews.append(review)

    await db_session.commit()
    for review in reviews:
        await db_session.refresh(review)

    try:
        page1 = await get_my_reviews(session=db_session, user_id=owner.user_id, page=1, size=2)
        page2 = await get_my_reviews(session=db_session, user_id=owner.user_id, page=2, size=2)

        assert page1.total == 4
        assert page2.total == 4
        assert len(page1.items) == 2
        assert len(page2.items) == 2

        page1_ids = [item.review_id for item in page1.items]
        page2_ids = [item.review_id for item in page2.items]

        # 페이지끼리 겹치는 리뷰가 없어야 한다
        assert set(page1_ids).isdisjoint(page2_ids)

        # created_at desc(최신순) - 가장 나중에 만든 reviews[3]이 1페이지 맨 앞에 와야 한다
        expected_order = [reviews[i].review_id for i in (3, 2, 1, 0)]
        assert page1_ids + page2_ids == expected_order
    finally:
        for review in reviews:
            await db_session.execute(delete(Review).where(Review.review_id == review.review_id))
        for course in courses:
            await db_session.execute(delete(Course).where(Course.course_id == course.course_id))
        await db_session.execute(delete(User).where(User.user_id == owner.user_id))
        await db_session.commit()
