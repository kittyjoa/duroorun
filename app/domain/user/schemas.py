"""회원/인증 - Pydantic 스키마 (요청/응답 검증)."""

from pydantic import BaseModel, ConfigDict


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
