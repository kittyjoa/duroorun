"""회원/인증 - Pydantic 스키마 (요청/응답 검증)."""

from pydantic import BaseModel


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
