import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from app.core.config import settings
from app.constants.voices import ALL_VOICES

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = Field(default=None, description="Chỉ nhận gemini-3.1-flash-lite hoặc gemini-3.5-flash-lite")
    tts_engine: Optional[str] = None
    selected_voice: Optional[str] = None
    tts_threads: Optional[int] = Field(default=None, ge=1, le=128)
    capcut_cookie: Optional[str] = None
    tiktok_session_id: Optional[str] = None


class TestGeminiRequest(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = "gemini-3.1-flash-lite"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


@router.get("", summary="Lấy toàn bộ cấu hình cài đặt hiện tại")
def get_settings() -> Dict[str, Any]:
    settings.reload_from_env()
    return {
        "gemini_api_key": mask_key(settings.GEMINI_API_KEY),
        "has_gemini_key": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip()),
        "gemini_model": settings.GEMINI_MODEL,
        "supported_gemini_models": [
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite"
        ],
        "tts_engine": settings.TTS_ENGINE,
        "selected_voice": settings.SELECTED_VOICE,
        "tts_threads": settings.TTS_MAX_WORKERS,
        "has_capcut_cookie": bool(settings.CAPCUT_COOKIE and settings.CAPCUT_COOKIE.strip()),
        "has_tiktok_session": bool(settings.TIKTOK_SESSION_ID and settings.TIKTOK_SESSION_ID.strip())
    }


@router.post("", summary="Lưu cấu hình cài đặt vào file .env")
def update_settings(req: SettingsUpdateRequest) -> Dict[str, Any]:
    updates = {}
    if req.gemini_api_key is not None:
        updates["GEMINI_API_KEY"] = req.gemini_api_key.strip()
    if req.gemini_model is not None:
        valid_models = {"gemini-3.1-flash-lite", "gemini-3.5-flash-lite"}
        if req.gemini_model not in valid_models:
            raise HTTPException(
                status_code=400,
                detail=f"Model không hợp lệ. Chỉ chấp nhận một trong hai model: {list(valid_models)}"
            )
        updates["GEMINI_MODEL"] = req.gemini_model.strip()
    if req.tts_engine is not None:
        updates["TTS_ENGINE"] = req.tts_engine.strip()
    if req.selected_voice is not None:
        new_voice = req.selected_voice.strip()
        updates["SELECTED_VOICE"] = new_voice
        # Khi đổi giọng mới: Xóa sạch toàn bộ mp3 giọng cũ và cập nhật session tạo lại từ câu 1
        from app.services.page_cache_manager import page_cache_manager
        from app.services.session_manager import session_manager
        page_cache_manager.clear_audio_cache()
        session_manager.update_all_sessions_voice(new_voice)
    if req.tts_threads is not None:
        updates["TTS_MAX_WORKERS"] = str(req.tts_threads)
    if req.capcut_cookie is not None:
        updates["CAPCUT_COOKIE"] = req.capcut_cookie.strip()
    if req.tiktok_session_id is not None:
        updates["TIKTOK_SESSION_ID"] = req.tiktok_session_id.strip()

    if updates:
        settings.save_to_env(updates)

    return {
        "status": "success",
        "message": "Đã lưu cài đặt thành công vào .env",
        "updated_fields": list(updates.keys())
    }


@router.post("/test-gemini", summary="Kiểm tra kết nối và tính hợp lệ của Google Gemini API Key")
async def test_gemini_connection(req: TestGeminiRequest) -> Dict[str, Any]:
    raw_key = (req.api_key or settings.GEMINI_API_KEY or "").strip()
    if not raw_key:
        raise HTTPException(status_code=400, detail="Chưa có Google Gemini API Key để kiểm tra!")

    # Lấy key đầu tiên nếu có nhiều key cách nhau bởi dấu phẩy
    key = raw_key.split(",")[0].strip()
    if key.startswith("gsk_"):
        raise HTTPException(
            status_code=400,
            detail="Bạn đang nhập nhầm Groq API Key (bắt đầu bằng 'gsk_...'). Google Gemini Key phải bắt đầu bằng 'AIzaSy...'."
        )

    chosen_model = req.model or settings.GEMINI_MODEL or "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                # Tự động lưu key hợp lệ vào file .env
                if raw_key:
                    settings.save_to_env({
                        "GEMINI_API_KEY": raw_key,
                        "GEMINI_MODEL": chosen_model
                    })

                data = resp.json()
                models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
                return {
                    "status": "success",
                    "message": f"🎉 Kết nối Google Gemini API thành công! Đã tự động lưu vào hệ thống.",
                    "tested_model": chosen_model,
                    "total_available_models": len(models)
                }
            elif resp.status_code in (400, 403):
                err_msg = "API Key không hợp lệ hoặc bị từ chối truy cập."
                try:
                    err_json = resp.json()
                    err_msg = err_json.get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                raise HTTPException(status_code=400, detail=f"Lỗi Gemini API ({resp.status_code}): {err_msg}")
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Lỗi máy chủ Google ({resp.status_code}): {resp.text}")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi mạng khi kết nối tới máy chủ Google Gemini: {str(exc)}")


@router.get("/voices", summary="Lấy danh sách 18 giọng đọc chuẩn từ ReviewMatThon")
def get_voices() -> Dict[str, Any]:
    return {
        "status": "success",
        "total": len(ALL_VOICES),
        "voices": ALL_VOICES
    }

