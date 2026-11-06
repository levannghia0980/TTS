from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from app.services.tts_service import TTSService

router = APIRouter()


class TTSRequest(BaseModel):
    text: str = Field(..., description="Đoạn văn bản cần chuyển thành giọng nói")
    voice_id: Optional[str] = Field(default=None, description="Mã giọng đọc (ví dụ: vi-VN-HoaiMyNeural, BV074_streaming...)")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)


class SentenceItem(BaseModel):
    id: str
    text: str


class TTSBatchRequest(BaseModel):
    sentences: List[SentenceItem] = Field(..., description="Danh sách các câu cần tổng hợp giọng nói")
    voice_id: Optional[str] = None
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    max_workers: Optional[int] = Field(default=None, ge=1, le=128)


@router.post("", summary="Tổng hợp giọng nói cho một câu đơn lẻ")
async def synthesize_single(req: TTSRequest) -> Dict[str, Any]:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Văn bản không được để trống!")

    res = await TTSService.synthesize_single(req.text, voice_id=req.voice_id, speed=req.speed or 1.0)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Lỗi tạo giọng nói"))
    return res


@router.post("/batch", summary="Tổng hợp giọng nói đa luồng song song cho danh sách câu")
async def synthesize_batch(req: TTSBatchRequest) -> Dict[str, Any]:
    if not req.sentences:
        raise HTTPException(status_code=400, detail="Danh sách câu không được rỗng!")

    sentences_dict = [{"id": s.id, "text": s.text} for s in req.sentences]
    results = await TTSService.synthesize_batch(
        sentences=sentences_dict,
        voice_id=req.voice_id,
        speed=req.speed or 1.0,
        max_workers=req.max_workers
    )

    success_count = sum(1 for r in results if r.get("status") == "success")
    return {
        "status": "success",
        "total": len(results),
        "success_count": success_count,
        "data": results
    }
