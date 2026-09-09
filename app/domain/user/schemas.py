"""회원/인증 - Pydantic 스키마 (요청/응답 검증)."""

from pydantic import BaseModel, ConfigDict

from app.domain.user.models import UserRole


class TokenResponse(BaseModel):
    """소셜 로그인 성공 응답."""

    access_token: str
    token_type: str = "bearer"
    is_new_user: bool


class MessageResponse(BaseModel):
    """단순 메시지 응답."""

    message: str


class ProfileImageResponse(BaseModel):
    """프로필 이미지 업로드 응답."""

    profile_image_url: str


class UserOnboardingRequest(BaseModel):
    """최초 가입 완료 요청. 닉네임/거주지 둘 다 필수."""

    nickname: str
    location: str


class UserProfileUpdate(BaseModel):
    """내 정보 수정 요청 (마이페이지). 보낸 필드만 갱신, 나머지는 유지."""

    nickname: str | None = None
    location: str | None = None


class UserResponse(BaseModel):
    """내 정보 조회 응답."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str | None
    nickname: str | None
    profile_image_url: str | None
    location: str | None
    user_role: UserRole


class PublicProfileResponse(BaseModel):
    """다른 유저의 공개 프로필 조회 응답 (마이페이지보다 훨씬 적은 정보만 노출).

    user_role은 프론트가 관리자 프로필에서 강제 탈퇴 폼을 아예 안 띄우기 위해 포함한다
    (최종 차단은 어차피 백엔드가 하지만, 항상 실패할 폼을 보여주지 않기 위한 UX 목적).
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    nickname: str | None
    location: str | None
    profile_image_url: str | None
    user_role: UserRole
