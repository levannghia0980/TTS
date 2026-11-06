from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from app.services.translate_service import TranslateService

router = APIRouter()


class TranslateRequest(BaseModel):
    text: Optional[str] = None
    texts: Optional[List[str]] = None
    model: Optional[str] = Field(default=None, description="gemini-3.1-flash-lite hoặc gemini-3.5-flash-lite")
    api_key: Optional[str] = None


@router.post("", summary="Dịch đoạn văn bản hoặc danh sách đoạn văn sang tiếng Việt bằng Gemini")
async def translate(req: TranslateRequest) -> Dict[str, Any]:
    try:
        # Nếu gửi danh sách đoạn
        if req.texts is not None and len(req.texts) > 0:
            results = await TranslateService.translate_batch(req.texts, model=req.model, api_key=req.api_key)
            return {
                "status": "success",
                "total": len(results),
                "data": results
            }

        # Nếu gửi 1 đoạn đơn
        if req.text is not None and req.text.strip():
            translated = await TranslateService.translate_single(req.text, model=req.model, api_key=req.api_key)
            return {
                "status": "success",
                "original": req.text,
                "translated": translated
            }

        raise HTTPException(status_code=400, detail="Vui lòng cung cấp 'text' hoặc 'texts' cần dịch.")

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi trong quá trình dịch thuật: {str(e)}")
