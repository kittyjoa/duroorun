"""편의시설 - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.domain.course.models import Course

_KAKAO_PLACE_URL_TEMPLATE = "https://place.map.kakao.com/{}"


class FacilityType(enum.StrEnum):
    RESTROOM = "RESTROOM"
    PARKING = "PARKING"
    LOCKER = "LOCKER"
    OTHERS = "OTHERS"


class Facility(Base):
    """편의시설 — 관리자만 등록/수정/삭제 가능."""

    __tablename__ = "facilities"
    __table_args__ = (
        # 같은 카카오 장소를 같은 시설 타입으로 중복 등록하는 것 방지
        # (NULL은 예외, 유니크 제약은 kakao_place_id가 채워진 경우에만 작동)
        UniqueConstraint("kakao_place_id", "facility_type", name="uq_facility_kakao_place_type"),
    )

    facility_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facility_type: Mapped[FacilityType] = mapped_column(SAEnum(FacilityType), nullable=False)
    facility_name: Mapped[str] = mapped_column(String, nullable=False)
    facility_address: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    kakao_place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    course_facilities: Mapped[list["CourseFacility"]] = relationship(
        back_populates="facility",
        cascade="all, delete-orphan",
    )

    @property
    def place_url(self) -> str | None:
        """kakao_place_id로 계산해 카카오맵 장소 상세 URL 조립 (컬럼 저장 X)."""
        if self.kakao_place_id is None:
            return None
        return _KAKAO_PLACE_URL_TEMPLATE.format(self.kakao_place_id)


class CourseFacility(Base):
    """코스 ↔ 편의시설 N:M 중간 테이블."""

    __tablename__ = "course_facility"

    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.course_id"), primary_key=True
    )
    facility_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("facilities.facility_id"), primary_key=True
    )
    # 관리자가 매핑을 언제 연결했는지 추적용
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Course는 course 도메인에 정의 — 문자열 참조로 순환 import 방지
    course: Mapped["Course"] = relationship(back_populates="course_facilities")
    facility: Mapped["Facility"] = relationship(back_populates="course_facilities")
