"""코스 (DRNB + 커스텀) - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CourseType(enum.StrEnum):
    DRNB = "DRNB"
    CUSTOM = "CUSTOM"


class Difficulty(enum.StrEnum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    HARD = "HARD"


class Course(Base):
    """코스 (두루누비 공식 코스 + 유저 커스텀 코스)."""

    __tablename__ = "courses"

    course_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_type: Mapped[CourseType] = mapped_column(SAEnum(CourseType), nullable=False)
    dmb_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)  # 두루누비 코스 고유번호(crsIdx)
    course_name: Mapped[str] = mapped_column(String, nullable=False)
    # 탈퇴 유저의 커스텀 코스는 created_by=NULL 처리 후 서비스에 계속 노출
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[Difficulty | None] = mapped_column(SAEnum(Difficulty), nullable=True)
    estimated_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    course_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sigun: Mapped[str | None] = mapped_column(String, nullable=True)
    brd_div: Mapped[str | None] = mapped_column(String, nullable=True)
    # 완주 인증 검증 기준점 — 런타임에 두루누비 API 미호출하고 DB 값만 사용
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    waypoints: Mapped[list["CourseWaypoint"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseWaypoint.sequence",
    )
    images: Mapped[list["CourseImage"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    # CourseFacility는 facility 도메인에 정의 — 문자열 참조로 순환 import 방지
    course_facilities: Mapped[list["CourseFacility"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )


class CourseWaypoint(Base):
    """커스텀 코스 경유지 좌표 — CUSTOM 코스 전용."""

    __tablename__ = "course_waypoints"
    __table_args__ = (UniqueConstraint("course_id", "sequence", name="uq_waypoint_course_sequence"),)

    waypoint_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.course_id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="waypoints")


class CourseImage(Base):
    """커스텀 코스 이미지 (Cloudflare R2) — CUSTOM 코스 전용."""

    __tablename__ = "course_images"

    image_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.course_id"), nullable=False, index=True)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    course: Mapped["Course"] = relationship(back_populates="images")
