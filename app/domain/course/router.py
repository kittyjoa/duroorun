"""코스 (DRNB + 커스텀) - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter, Depends, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.domain.course import service as course_service
from app.domain.course.models import Difficulty
from app.domain.course.schemas import (
    GANGWON_BOUNDARY_PATH,
    CourseCreateRequest,
    CourseUpdateRequest,
    CustomCourseDetailResponse,
    CustomCourseListResponse,
    DrnbCourseDetailResponse,
    DrnbCourseListResponse,
)
from app.domain.user.models import User

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/gangwon-boundary")
async def get_gangwon_boundary():
    """강원도 경계 geojson 원본 그대로 반환 (프론트 커스텀 코스 폼이 경유지 지역을
    백엔드와 동일한 폴리곤으로 검증하는 데 사용). 정적 공개 데이터라 인증 불필요.
    ㅡ 도 경계는 거의 안 바뀌므로 캐시 헤더를 길게 둠"""
    return FileResponse(
        GANGWON_BOUNDARY_PATH,
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/drnb", response_model=DrnbCourseListResponse)
async def get_drnb_courses(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    brd_div: str | None = Query(default=None),
    sigun: str | None = Query(default=None),
    difficulty: Difficulty | None = Query(default=None),
    distance_min: float | None = Query(default=None, ge=0),
    distance_max: float | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """DRNB(두루누비) 코스 목록 조회 (구간/지역/난이도/거리 필터 지원)
    ㅡ 거리 필터는 프론트에서 범위 UI 가능"""
    return await course_service.get_drnb_courses(
        session=session,
        page=page,
        size=size,
        brd_div=brd_div,
        sigun=sigun,
        difficulty=difficulty,
        distance_min=distance_min,
        distance_max=distance_max,
    )


@router.get("/drnb/{course_id}", response_model=DrnbCourseDetailResponse)
async def get_drnb_course(course_id: int, session: AsyncSession = Depends(get_db)):
    """DRNB(두루누비) 코스 상세 조회"""
    return await course_service.get_drnb_course(session=session, course_id=course_id)


@router.post(
    "/custom", response_model=CustomCourseDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_course(
    body: CourseCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """커스텀 코스 등록 (로그인 유저 전용)"""
    return await course_service.create_course(
        session=session, user_id=current_user.user_id, body=body
    )


@router.get("/custom", response_model=CustomCourseListResponse)
async def get_custom_courses(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    created_by: int | None = Query(default=None, ge=1),
    difficulty: Difficulty | None = Query(default=None),
    distance_min: float | None = Query(default=None, ge=0),
    distance_max: float | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """커스텀 코스 목록 조회 (전체 공개. created_by/난이도/거리 필터 지원)
    ㅡ 거리 필터는 프론트에서 범위 UI 가능"""
    return await course_service.get_custom_courses(
        session=session,
        page=page,
        size=size,
        created_by=created_by,
        difficulty=difficulty,
        distance_min=distance_min,
        distance_max=distance_max,
    )


@router.get("/custom/{course_id}", response_model=CustomCourseDetailResponse)
async def get_custom_course(course_id: int, session: AsyncSession = Depends(get_db)):
    """커스텀 코스 상세 조회 (경유지/이미지 포함)"""
    return await course_service.get_custom_course(session=session, course_id=course_id)


@router.patch("/custom/{course_id}", response_model=CustomCourseDetailResponse)
async def update_course(
    course_id: int,
    body: CourseUpdateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """커스텀 코스 수정 (작성자 본인 전용, 부분 수정)"""
    return await course_service.update_course(
        session=session, user_id=current_user.user_id, course_id=course_id, body=body
    )


@router.delete("/custom/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """커스텀 코스 삭제 (작성자 본인 전용, Soft Delete)"""
    await course_service.delete_course(
        session=session, user_id=current_user.user_id, course_id=course_id
    )


@router.post(
    "/custom/{course_id}/images",
    response_model=CustomCourseDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_course_image(
    course_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """커스텀 코스 이미지 업로드 (작성자 본인 전용)"""
    return await course_service.upload_course_image(
        session=session, user_id=current_user.user_id, course_id=course_id, file=file
    )


@router.delete("/custom/{course_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course_image(
    course_id: int,
    image_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """커스텀 코스 이미지 삭제 (작성자 본인 전용)"""
    await course_service.delete_course_image(
        session=session, user_id=current_user.user_id, course_id=course_id, image_id=image_id
    )
