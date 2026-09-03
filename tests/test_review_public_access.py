"""코스 리뷰 목록 조회가 실제로 비로그인 상태에서도 되는지(라우터 레벨) 테스트.

get_reviews 서비스 함수 자체는 애초에 user 매개변수를 받지 않으므로, 서비스 함수만
직접 호출하는 다른 테스트들과 달리 이건 "라우터에 인증 의존성이 없는지"를 확인하는
것이 목적이다 - 그래서 서비스 함수가 아니라 실제 ASGI 앱에 Authorization 헤더 없이
요청을 보내 응답 상태코드로 확인한다.
"""

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import add_completed_reviews


async def test_get_reviews_succeeds_without_auth_header(db_session, review_test_course):
    """Authorization 헤더 없이 리뷰 목록을 조회해도 401이 아니라 200이어야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=1)
    course_id = review_test_course.course_id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/v1/reviews/courses/{course_id}?offset=0&size=20")

    assert res.status_code == 200, f"비로그인 리뷰 조회는 200이어야 하는데: {res.status_code}"
    data = res.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
