"""API 라우터 통합."""

from fastapi import APIRouter

from app.domain.facility.router import router as facility_router
from app.domain.user.router import router as user_router

router = APIRouter(prefix="/api/v1")

# 도메인 라우터 추가 (각자 작업 완료 후 여기에 include)
router.include_router(user_router)
router.include_router(facility_router)  # 지영
# router.include_router(course_router)   # 지영
# router.include_router(record_router)   # 유선
# router.include_router(review_router)   # 유선
