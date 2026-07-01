"""러닝 기록 - API 엔드포인트 (APIRouter)."""

from fastapi import APIRouter

from app.domain.record.schemas import RecordEndRequest, RecordResponse, RecordStartRequest

router = APIRouter(prefix="/records", tags=["records"])


@router.post("/start", response_model=RecordResponse)
async def start_record(body: RecordStartRequest):
    """러닝시작"""
    pass


@router.patch("/{record_id}/end", response_model=RecordResponse)
async def end_record(record_id: int, body: RecordEndRequest):
    """러닝종료"""
    pass


@router.get("/{record_id}", response_model=RecordResponse)
async def get_record(record_id: int):
    """러닝기록 단건 조회(기록 1개 상세)"""
    pass


@router.get("/", response_model=list[RecordResponse])
async def get_records(page: int = 1, size: int = 20):
    """내 러닝기록 조회(내 기록 전체리스트)"""
    pass


@router.patch("/{record_id}/pause", response_model=RecordResponse)
async def pause_record(record_id: int):
    """러닝 일시정지"""
    pass


@router.patch("/{record_id}/resume", response_model=RecordResponse)
async def resume_record(record_id: int):
    """러닝 재시작"""
    pass


@router.delete("/{record_id}")
async def delete_record(record_id: int):
    """러닝기록 삭제"""
    pass
