"""회원/인증/관리자 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter

router = APIRouter(tags=["auth"])

# 소셜 로그인 / 회원 API는 순차적으로 추가
