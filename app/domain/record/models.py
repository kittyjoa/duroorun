"""러닝 기록 - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
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
    )  # 완주인증시 true로 바뀜
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_paused_seconds: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # 필요 시 해제 확인필요해서 일단 주석 남겨뒀어욤— record.user.nickname 같은 직접 접근 가능
    # user: Mapped["User"] = relationship("User")
    # course: Mapped["Course"] = relationship("Course")

    __table_args__ = (
        # 유저당 진행 중(ended_at IS NULL)인 기록은 최대 1개만 허용 (동시 시작 레이스 방지)
        Index(
            "uq_records_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        # 완주(is_completed=true) 처리된 기록은 종료 시각이 반드시 있어야 함
        # — 통계 쿼리들이 is_completed 기준(총계)과 ended_at 기준(기간별)을 섞어 써서,
        # 이 둘이 어긋나면 두 통계 간 숫자가 안 맞게 됨 (관리자 대시보드 리뷰에서 지적)
        CheckConstraint(
            "NOT is_completed OR ended_at IS NOT NULL", name="ck_records_completed_has_ended_at"
        ),
    )
