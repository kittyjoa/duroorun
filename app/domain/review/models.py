"""리뷰 + 이미지 - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain.course.models import Difficulty


class Review(Base):
    """코스 리뷰"""

    __tablename__ = "reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # nullable=True : 탈퇴한 유저 리뷰 아이디를 NULL로 변경해서 내용은 남겨야함.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.user_id"), nullable=True, index=True
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.course_id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty, create_type=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    images: Mapped[list["ReviewImage"]] = relationship(
        "ReviewImage",
        cascade="all, delete-orphan",
        order_by="ReviewImage.created_at",
        lazy="selectin",
    )

    # 같은 코스에 리뷰 1개만 작성가능
    __table_args__ = (UniqueConstraint("course_id", "user_id", name="uq_reviews_course_user"),)


class ReviewImage(Base):
    """리뷰 이미지"""

    __tablename__ = "review_images"

    image_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.review_id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewSummary(Base):
    """AI 리뷰 요약"""

    __tablename__ = "review_summaries"

    summary_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.course_id"), nullable=False, unique=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
