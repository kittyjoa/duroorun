"""리뷰 수정/삭제 권한(본인 확인) 테스트.

본인이 아닌 다른 유저가 리뷰 수정/삭제를 시도하면 403으로 거절되어야 한다. 관리자는
본인이 아니어도 삭제할 수 있다(신고 대응 등 목적).
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.domain.review.models import Review
from app.domain.review.schemas import ReviewUpdateRequest
from app.domain.review.service import delete_review, update_review
from app.domain.user.models import User, UserRole
from tests.conftest import FakeBackgroundTasks, add_completed_reviews


async def _make_other_user(db_session, ctx) -> int:
    other = User(nickname=f"pytest-other-{uuid.uuid4().hex[:12]}")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    ctx.user_ids.append(other.user_id)
    return other.user_id


async def test_update_review_by_non_owner_is_forbidden(db_session, review_test_course):
    await add_completed_reviews(db_session, review_test_course, count=1)
    review = await db_session.scalar(
        select(Review).where(Review.course_id == review_test_course.course_id)
    )
    other_user_id = await _make_other_user(db_session, review_test_course)

    with pytest.raises(HTTPException) as exc_info:
        await update_review(
            session=db_session,
            user_id=other_user_id,
            review_id=review.review_id,
            body=ReviewUpdateRequest(content="남의 리뷰를 수정 시도", difficulty=None),
            background_tasks=FakeBackgroundTasks(),
        )
    assert exc_info.value.status_code == 403


async def test_delete_review_by_non_owner_is_forbidden(db_session, review_test_course):
    await add_completed_reviews(db_session, review_test_course, count=1)
    review = await db_session.scalar(
        select(Review).where(Review.course_id == review_test_course.course_id)
    )
    other_user_id = await _make_other_user(db_session, review_test_course)

    with pytest.raises(HTTPException) as exc_info:
        await delete_review(
            session=db_session,
            user_id=other_user_id,
            review_id=review.review_id,
            user_role=UserRole.USER,
            background_tasks=FakeBackgroundTasks(),
        )
    assert exc_info.value.status_code == 403


async def test_delete_review_by_admin_succeeds(db_session, review_test_course):
    await add_completed_reviews(db_session, review_test_course, count=1)
    review = await db_session.scalar(
        select(Review).where(Review.course_id == review_test_course.course_id)
    )
    admin_id = await _make_other_user(db_session, review_test_course)

    # 삭제 자체가 성공(예외 없이 반환)해야 한다 - 관리자는 본인 리뷰가 아니어도 지울 수 있다
    await delete_review(
        session=db_session,
        user_id=admin_id,
        review_id=review.review_id,
        user_role=UserRole.ADMIN,
        background_tasks=FakeBackgroundTasks(),
    )

    remaining = await db_session.scalar(select(Review).where(Review.review_id == review.review_id))
    assert remaining is None
