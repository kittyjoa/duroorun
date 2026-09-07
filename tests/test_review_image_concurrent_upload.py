"""리뷰 이미지 동시 업로드 시 최대 개수 초과 방지 테스트.

upload_review_image는 이미지 개수를 세기 전에 리뷰 행을 with_for_update()로 잠근다 -
동시에 두 업로드 요청이 들어와도 두 번째 요청의 잠금 획득(및 그 이후의 개수 확인)은
첫 번째 요청이 커밋할 때까지 대기하므로, 두 번째 요청은 이미 늘어난 개수를 보고
정상적으로 거절되어야 한다. 이 테스트는 그 직렬화가 실제로 동작해서 최대 개수를
넘기지 않는지, 그리고 거절된 쪽은 R2 업로드 자체를 시도하지 않는지(고아 파일이 생기지
않는지) 확인한다.
"""

import asyncio
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.domain.review.models import Review, ReviewImage
from app.domain.review.service import upload_review_image
from tests.conftest import add_completed_reviews

# 최소한의 유효한 PNG 시그니처 (실제 이미지 내용은 검증 로직상 중요하지 않음)
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


async def test_concurrent_uploads_do_not_exceed_max_count(db_session, review_test_course):
    """이미지가 (최대-1)개인 상태에서 동시 업로드 2개가 들어오면, 하나만 성공하고
    최종 이미지 개수는 정확히 최대 개수를 넘지 않아야 한다."""
    await add_completed_reviews(db_session, review_test_course, count=1)
    course_id = review_test_course.course_id
    user_id = review_test_course.user_ids[0]
    review = await db_session.scalar(select(Review).where(Review.course_id == course_id))
    review_id = review.review_id

    # 이미 (최대-1)개의 이미지가 있는 상태를 만든다 - 남은 자리는 정확히 1개
    for _ in range(settings.REVIEW_IMAGE_MAX_COUNT - 1):
        db_session.add(ReviewImage(review_id=review_id, image_url=f"https://fake/{uuid.uuid4().hex}.png"))
    await db_session.commit()

    fake_r2 = MagicMock()

    async def attempt():
        async with AsyncSessionLocal() as session:
            file = UploadFile(filename="test.png", file=BytesIO(_PNG_BYTES))
            try:
                await upload_review_image(
                    session=session, user_id=user_id, review_id=review_id, file=file
                )
                return "ok"
            except HTTPException as err:
                return err.status_code

    with patch("app.domain.review.service._get_r2_client", return_value=fake_r2):
        results = await asyncio.gather(attempt(), attempt())

    assert results.count("ok") == 1 and results.count(400) == 1, (
        f"동시 업로드 중 정확히 하나만 성공하고 나머지는 400이어야 하는데: {results}"
    )

    count_result = await db_session.execute(
        select(func.count()).select_from(ReviewImage).where(ReviewImage.review_id == review_id)
    )
    final_count = count_result.scalar_one()
    max_count = settings.REVIEW_IMAGE_MAX_COUNT
    assert final_count == max_count, f"최종 개수는 {max_count}여야: {final_count}"

    # 거절된 요청은 개수 확인 단계에서 바로 400을 반환하므로, row lock 덕분에
    # R2 업로드(put_object) 자체가 시도된 적이 없어야 한다 - 고아 파일이 생기지 않는다.
    put_calls = fake_r2.put_object.call_count
    assert put_calls == 1, f"R2 업로드는 1건만 호출됐어야: {put_calls}회"
