"""회원/인증/관리자 - SQLAlchemy ORM 모델 (DB 테이블 정의)."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class ProviderType(str, enum.Enum):
    GOOGLE = "GOOGLE"
    KAKAO = "KAKAO"
    NAVER = "NAVER"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole), default=UserRole.USER, server_default="USER", nullable=False
    )

    name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 최초 가입 시 NULL, 정보 수정 시 자동 갱신
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
    # 탈퇴 시 현재 시각 기록 (row 삭제 없이 익명화 처리)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class SocialAccount(Base):
    """소셜 로그인 연동 정보 — 탈퇴 시 Hard Delete."""

    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("provider_type", "provider_uid", name="uq_social_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.user_id"), nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(SAEnum(ProviderType), nullable=False)
    provider_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="social_accounts")
