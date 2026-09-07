"""이미지는 R2에 업로드됐는데 DB 저장이 실패하면, 올려둔 R2 파일을 정리(롤백)하는지 테스트.

DB commit 실패는 io.BytesIO(unittest.mock.patch)로 흉내내고, R2 클라이언트는 실제
버킷을 건드리지 않도록 MagicMock으로 대체한다.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.domain.review.models import Review
from app.domain.review.service import upload_review_image
from tests.conftest import add_completed_reviews

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


async def test_db_commit_failure_after_r2_upload_cleans_up_r2_file(db_session, review_test_course):
    await add_completed_reviews(db_session, review_test_course, count=1)
    review = await db_session.scalar(
        select(Review).where(Review.course_id == review_test_course.course_id)
    )
    # rollback이 걸리면 review 객체의 속성이 만료되어 재조회가 필요해지는데, 그 재조회는
    # 비동기 컨텍스트 밖에서는 실패한다 - rollback 전에 필요한 값을 미리 꺼내둔다
    user_id = review.user_id
    review_id = review.review_id

    fake_r2 = MagicMock()

    async def failing_commit():
        raise RuntimeError("DB 저장 실패 시뮬레이션")

    file = UploadFile(filename="test.png", file=BytesIO(_PNG_BYTES))

    with (
        patch("app.domain.review.service._get_r2_client", return_value=fake_r2),
        patch.object(db_session, "commit", side_effect=failing_commit),
        pytest.raises(RuntimeError),
    ):
        await upload_review_image(
            session=db_session, user_id=user_id, review_id=review_id, file=file
        )

    # commit이 실패하면 session이 pending 상태로 남을 수 있으므로 정리
    await db_session.rollback()

    assert fake_r2.put_object.call_count == 1, "R2 업로드는 실제로 시도됐어야 한다"
    assert fake_r2.delete_object.call_count == 1, (
        "DB 저장 실패 후에는 방금 올린 R2 파일을 정리(delete_object)해야 한다"
    )

    # DB에는 이미지 레코드가 남지 않아야 한다
    count_result = await db_session.execute(select(Review).where(Review.review_id == review_id))
    reloaded = count_result.scalar_one()
    assert reloaded.images == []
