"""마이페이지 - 내가 쓴 리뷰 목록(GET /reviews/mine) 조회 테스트."""

from sqlalchemy import select

from app.domain.review.models import Review, ReviewImage
from app.domain.review.service import get_my_reviews
from tests.conftest import add_completed_reviews


async def test_get_my_reviews_includes_course_name_and_images(db_session, review_test_course):
    """리뷰(이미지 포함)가 있는 유저로 조회하면 코스명과 이미지가 정상적으로 채워진다."""
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
    assert len(item.images) == 1
    assert item.images[0].image_url == "https://example.com/a.jpg"
