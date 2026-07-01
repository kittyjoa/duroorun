"""러닝 기록 - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Record(Base):
    """러닝 기록"""

    __tablename__ = "records"
    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.user_id"), nullable=True, index=True
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.course_id"), nullable=False, index=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pace: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_start_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_end_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_end_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    ) #완주인증시 true로 바뀜
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 필요 시 해제 확인필요해서 일단 주석 남겨뒀어욤— record.user.nickname 같은 직접 접근 가능
    # user: Mapped["User"] = relationship("User")
    # course: Mapped["Course"] = relationship("Course")
