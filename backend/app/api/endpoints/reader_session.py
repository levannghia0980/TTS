# -*- coding: utf-8 -*-
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.services.session_manager import session_manager
from app.constants.voices import get_male_voice_for_lang

router = APIRouter(prefix="/session", tags=["Reader Session"])


class StartSessionRequest(BaseModel):
    session_id: str = Field(..., description="Mã định danh phiên (tabId hoặc URL hash)")
    blocks: List[Dict[str, Any]] = Field(..., description="Danh sách các đoạn văn bản thô từ trang web")
    profile: str = Field("general", description="Thể loại dịch: 'general' (báo chí, kiến thức) hoặc 'story' (truyện)")
    voice_id: Optional[str] = Field(None, description="Mã giọng đọc TTS (CapCut / Edge)")
    orig_voice_id: Optional[str] = Field(None, description="Mã giọng đọc bản gốc (tự động theo ngôn ngữ nếu rỗng)")
    vi_voice_id: Optional[str] = Field(None, description="Mã giọng đọc bản dịch tiếng Việt")
    lang: Optional[str] = Field("en", description="Mã ngôn ngữ phát hiện của trang (en, zh, vi, ja...)")
    page_url: Optional[str] = Field("", description="Đường dẫn trang web")
    mode: Optional[str] = Field("orig", description="Chế độ phát mặc định ('orig' hoặc 'vi')")
    speed: float = Field(1.0, description="Tốc độ đọc (0.75 - 2.0)")
    model: Optional[str] = Field(None, description="Mô hình Gemini")


class SeekRequest(BaseModel):
    session_id: str
    index: int


class SwitchModeRequest(BaseModel):
    session_id: str
    mode: str = Field(..., description="'orig' hoặc 'vi'")


@router.post("/start")
async def start_session(req: StartSessionRequest):
    """
    Khởi động phiên đọc mới:
    - Mặc định đọc bản GỐC bằng giọng nam đặc trưng của ngôn ngữ trang web.
    - Không đợi dịch, tạo ngay audio bản gốc cho câu 0 & 1 (<0.5s).
    - Hỗ trợ chuyển sang bản dịch tiếng Việt tức thì mà không cần nạp lại trang.
    """
    # Tách các khối văn bản (blocks) thành từng câu/vế câu hoàn chỉnh
    sentences_data = []
    import re

    def split_sub_clauses(text: str, max_chars: int = 120) -> List[str]:
        if len(text) <= max_chars:
            return [text]
        parts = re.split(r'([,;:—–\-\,\;\:\，\；\：]+|\s+(?:và|nhưng|mà|cùng|hoặc|and|but|or|while)\s+)', text)
        chunks = []
        cur = ""
        for p in parts:
            if not p:
                continue
            if len(cur + p) <= max_chars:
                cur += p
            else:
                if cur.strip():
                    chunks.append(cur.strip())
                cur = p
        if cur.strip():
            chunks.append(cur.strip())
        return [c for c in chunks if len(c) > 1] or [text]

    for b_idx, block in enumerate(req.blocks):
        raw_text = block.get("text", "").strip()
        xid = block.get("xid", f"b-{b_idx}")
        sid = block.get("sid")
        blk_lang = block.get("lang", "")

        # Nếu block đã được chia nhỏ sẵn từ frontend (chuẩn sid)
        if sid:
            sentences_data.append({
                "original": raw_text,
                "translated": raw_text if (blk_lang == "vi" or req.lang == "vi") else "",
                "xid": xid,
                "sid": sid
            })
            continue

        # Nếu block chưa chia nhỏ: tách theo dấu kết thúc câu (. ! ? … \n hoặc 。！？)
        segs = re.split(r'(?<=[.?!…\n。！？])\s+', raw_text)
        for seg in segs:
            seg_clean = seg.strip()
            if len(seg_clean) > 1:
                # Nếu câu dài hơn 120 ký tự: cắt tiếp theo dấu giữa câu (phẩy, chấm phẩy...)
                sub_parts = split_sub_clauses(seg_clean, max_chars=120)
                for sub_p in sub_parts:
                    sub_clean = sub_p.strip()
                    if len(sub_clean) > 1:
                        new_sid = f"s-{len(sentences_data)}"
                        sentences_data.append({
                            "original": sub_clean,
                            "translated": sub_clean if (blk_lang == "vi" or req.lang == "vi") else "",
                            "xid": xid,
                            "sid": new_sid
                        })

    if not sentences_data:
        raise HTTPException(status_code=400, detail="Không có nội dung văn bản nào để đọc.")

    # Tự động chọn giọng nam cho ngôn ngữ trang nếu chưa chỉ định
    chosen_orig_voice = req.orig_voice_id or get_male_voice_for_lang(req.lang or "en")
    chosen_vi_voice = req.vi_voice_id or req.voice_id

    # Tự động nhận diện profile (truyện vs thông tin tổng hợp/báo chí) qua URL hoặc frontend
    chosen_profile = req.profile or "general"
    if chosen_profile == "general" and req.page_url:
        import re
        story_patterns = r'(truyen|novel|fiction|wattpad|qidian|faloo|biquge|69shu|uukanshu|syosetu|kakuyomu|ao3|archiveofourown|royalroad|wuxiaworld|chivi|wikidich|tangthuvien|metruyenchu|sangtacviet|bachngocsach|truyenfull|\/chuong[-_/]?\d+|\/chap(?:ter)?[-_/]?\d+|\/story\/|\/book\/)'
        if re.search(story_patterns, req.page_url, re.IGNORECASE):
            chosen_profile = "story"

    session = session_manager.create_session(
        session_id=req.session_id,
        raw_items=sentences_data,
        profile=chosen_profile,
        orig_voice_id=chosen_orig_voice,
        vi_voice_id=chosen_vi_voice,
        speed=req.speed,
        model=req.model,
        page_url=req.page_url or "",
        page_lang=req.lang or "en"
    )

    if req.mode == "vi":
        session.switch_mode("vi")

    return {
        "status": "started",
        "session_id": session.session_id,
        "total_sentences": len(session.sentences),
        "orig_voice_id": session.orig_voice_id,
        "vi_voice_id": session.vi_voice_id,
        "current_mode": session.current_mode,
        "page_lang": session.page_lang,
        "sentences": [
            {"index": s.index, "xid": s.xid, "sid": s.sid, "original": s.original, "translated": s.translated}
            for s in session.sentences
        ],
        "status_data": session.get_status()
    }


@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    """Lấy trạng thái tiến độ chuẩn bị âm thanh cả 2 pool, câu đang đọc và danh sách bản dịch mới."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại hoặc đã hết hạn.")
    return session.get_status()


@router.get("/audio/{session_id}/{index}")
async def get_sentence_audio(session_id: str, index: int):
    """Lấy audio theo chế độ hiện tại của session (tương thích ngược)."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại.")

    audio_bytes = await session.get_audio_bytes(index, timeout=6.0)
    if not audio_bytes:
        raise HTTPException(status_code=504, detail="Âm thanh cho câu này chưa sẵn sàng.")

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/audio-orig/{session_id}/{index}")
async def get_sentence_orig_audio(session_id: str, index: int):
    """Lấy trực tiếp audio bản gốc (giọng nam auto-detect)."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại.")

    audio_bytes = await session.get_orig_audio(index, timeout=6.0)
    if not audio_bytes:
        raise HTTPException(status_code=504, detail="Âm thanh bản gốc cho câu này chưa sẵn sàng.")

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/audio-vi/{session_id}/{index}")
async def get_sentence_vi_audio(session_id: str, index: int):
    """Lấy trực tiếp audio bản dịch tiếng Việt."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại.")

    audio_bytes = await session.get_vi_audio(index, timeout=8.0)
    if not audio_bytes:
        raise HTTPException(status_code=504, detail="Âm thanh bản dịch cho câu này chưa sẵn sàng.")

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.post("/switch-mode")
async def switch_mode(req: SwitchModeRequest):
    """
    Chuyển đổi giữa chế độ phát Bản Gốc ('orig') và Bản Dịch ('vi').
    Reset con trỏ về câu số 1 (index 0) cho luồng mới.
    """
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại.")

    session.switch_mode(req.mode)
    session.seek(0)
    return {
        "status": "switched",
        "current_mode": session.current_mode,
        "current_index": 0,
        "status_data": session.get_status()
    }


@router.post("/seek")
async def seek_sentence(req: SeekRequest):
    """Ưu tiên tạo audio cho câu đích và câu tiếp theo."""
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Phiên đọc không tồn tại.")

    session.seek(req.index)
    return session.get_status()


@router.delete("/{session_id}")
async def close_session(session_id: str):
    """Giải phóng hoàn toàn RAM và các worker ngầm khi tắt trang."""
    session_manager.close_session(session_id)
    return {"status": "closed", "session_id": session_id}


@router.post("/clear-cache")
async def clear_cache():
    """Xóa sạch toàn bộ cache JSON tạm thời theo link web và file audio."""
    from app.services.page_cache_manager import page_cache_manager
    page_cache_manager.clear_all()
    return {"status": "cleared", "message": "Đã xóa sạch 100% cache JSON và file tạm thời."}


@router.post("/stop-and-clear")
async def stop_and_clear():
    """Đánh dấu dừng toàn bộ hệ thống và xóa sạch 100% cache JSON theo link web."""
    from app.services.page_cache_manager import page_cache_manager
    session_manager.cleanup_expired(max_idle_seconds=0.0)
    page_cache_manager.clear_all()
    return {
        "status": "stopped",
        "message": "Đã đánh dấu DỪNG toàn bộ chương trình và xóa sạch 100% cache JSON theo link web.",
        "cache_deleted": True
    }


