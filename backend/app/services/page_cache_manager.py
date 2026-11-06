# -*- coding: utf-8 -*-
"""
Hệ thống Bộ Nhớ Đệm Tạm Thời (Fast Ephemeral JSON Cache)
Quản lý cache theo link web (URL) cho bản dịch & audio TTS:
1. Lưu trữ có cấu trúc JSON cực nhanh theo URL hash.
2. Hỗ trợ đa tab độc lập: Mở nhiều tab hoặc mở 2 tab cùng 1 URL không bị xung đột,
   dùng chung cache dịch và âm thanh mà không tốn request Gemini / TTS.
3. Tự động xóa sạch 100% toàn bộ file cache trên ổ cứng và RAM khi tắt chương trình.
"""

import os
import re
import json
import shutil
import atexit
import hashlib
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from app.core.config import settings

# Thư mục cache tạm thời trong backend/cache
CACHE_DIR = settings.BASE_DIR / "cache"
PAGES_DIR = CACHE_DIR / "pages"
AUDIO_DIR = CACHE_DIR / "audio"

_CACHE_LOCK = threading.Lock()


def normalize_url(raw_url: str) -> str:
    """
    Chuẩn hóa URL để gom các link trùng nhau:
    - Bỏ fragment (#anchor)
    - Bỏ các query params quảng cáo / theo dõi (utm_*, fbclid, ref...)
    - Chuẩn hóa chữ thường domain, bỏ dấu gạch chéo cuối
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        # Loại bỏ tracking params
        tracking_prefixes = ("utm_", "fbclid", "gclid", "ref", "mc_eid", "mc_cid")
        query_dict = parse_qs(parsed.query, keep_blank_values=True)
        filtered_query = {
            k: v for k, v in query_dict.items()
            if not any(k.lower().startswith(p) for p in tracking_prefixes)
        }
        # Sắp xếp params để tạo hash nhất quán
        clean_query = urlencode(filtered_query, doseq=True)

        clean_path = parsed.path.rstrip("/")
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            parsed.params,
            clean_query,
            ""  # Bỏ fragment
        ))
        return normalized
    except Exception:
        return raw_url.strip().lower()


def get_url_hash(url: str) -> str:
    norm = normalize_url(url)
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


class PageCacheManager:
    _instance: Optional['PageCacheManager'] = None

    def __init__(self):
        self._ensure_dirs()
        # In-memory mapping URL hash -> cache data để đọc siêu tốc
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> 'PageCacheManager':
        if cls._instance is None:
            cls._instance = PageCacheManager()
        return cls._instance

    def get_url_hash(self, url: str) -> str:
        return get_url_hash(url)

    def _ensure_dirs(self):
        """Khởi tạo các thư mục lưu trữ cache tạm."""
        PAGES_DIR.mkdir(parents=True, exist_ok=True)
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    def get_page_cache(self, url: str) -> Optional[Dict[str, Any]]:
        """Lấy dữ liệu bản dịch đã lưu theo link web."""
        if not url:
            return None
        url_hash = get_url_hash(url)

        with _CACHE_LOCK:
            # 1. Thử từ RAM trước
            if url_hash in self._memory_cache:
                return self._memory_cache[url_hash]

            # 2. Thử từ file JSON trên ổ cứng
            json_file = PAGES_DIR / f"{url_hash}.json"
            if json_file.exists():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._memory_cache[url_hash] = data
                        return data
                except Exception:
                    return None
        return None

    def save_page_cache(
        self,
        url: str,
        profile: str = "general",
        lang: str = "en",
        sentences: Optional[List[Dict[str, Any]]] = None,
        title: str = "",
        orig_voice_id: str = "",
        vi_voice_id: str = ""
    ):
        """
        Lưu hoặc cập nhật trạng thái trang web theo link URL vào JSON tạm thời.
        Phân tách rõ ràng 2 trạng thái 'orig' (bản gốc) và 'vi' (bản dịch tiếng Việt)
        cho cả nội dung văn bản (original / translated) và đường dẫn file MP3 tương ứng.
        """
        if not url or not sentences:
            return
        url_hash = get_url_hash(url)
        norm_url = normalize_url(url)

        with _CACHE_LOCK:
            current = self._memory_cache.get(url_hash) or {}
            existing_sentences = {s.get("sid"): s for s in current.get("sentences", []) if s.get("sid")}
            existing_states = current.get("states", {
                "orig": {"voice_id": orig_voice_id, "audio_files": {}},
                "vi": {"voice_id": vi_voice_id, "audio_files": {}}
            })
            if orig_voice_id:
                existing_states.setdefault("orig", {"audio_files": {}})["voice_id"] = orig_voice_id
            if vi_voice_id:
                existing_states.setdefault("vi", {"audio_files": {}})["voice_id"] = vi_voice_id

            orig_audio_map = existing_states.get("orig", {}).get("audio_files", {})
            vi_audio_map = existing_states.get("vi", {}).get("audio_files", {})

            for s in sentences:
                sid = s.get("sid")
                if sid:
                    prev = existing_sentences.get(sid, {})
                    orig_text = s.get("original") or prev.get("original", "")
                    trans_text = s.get("translated") or prev.get("translated", "")
                    existing_sentences[sid] = {
                        "sid": sid,
                        "xid": s.get("xid") or prev.get("xid", ""),
                        "original": orig_text,
                        "translated": trans_text,
                        "orig_audio_file": orig_audio_map.get(sid, prev.get("orig_audio_file", "")),
                        "vi_audio_file": vi_audio_map.get(sid, prev.get("vi_audio_file", ""))
                    }

            sentence_list = list(existing_sentences.values())
            translated_count = sum(1 for item in sentence_list if item.get("translated"))
            existing_states.setdefault("orig", {})["ready_audio_count"] = len(orig_audio_map)
            existing_states.setdefault("vi", {})["translated_count"] = translated_count
            existing_states.setdefault("vi", {})["ready_audio_count"] = len(vi_audio_map)

            cache_data = {
                "url": norm_url,
                "url_hash": url_hash,
                "title": title or current.get("title", ""),
                "profile": profile,
                "lang": lang,
                "orig_voice_id": orig_voice_id or current.get("orig_voice_id", ""),
                "vi_voice_id": vi_voice_id or current.get("vi_voice_id", ""),
                "total_sentences": len(sentence_list),
                "states": existing_states,
                "sentences": sentence_list
            }

            self._memory_cache[url_hash] = cache_data
            self._write_json_unlocked(url_hash, cache_data)

    def _write_json_unlocked(self, url_hash: str, cache_data: Dict[str, Any]):
        """Ghi an toàn dữ liệu JSON của URL ra đĩa (gọi khi đã giữ _CACHE_LOCK)."""
        json_file = PAGES_DIR / f"{url_hash}.json"
        try:
            temp_file = PAGES_DIR / f"{url_hash}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            if temp_file.exists():
                temp_file.replace(json_file)
        except Exception:
            pass

    def get_audio_cache(self, url: str, sid: str, mode: str, voice_id: str) -> Optional[bytes]:
        """Lấy âm thanh MP3 đã tổng hợp theo URL, câu, chế độ ('orig' | 'vi') và giọng đọc."""
        if not url or not sid or mode not in ("orig", "vi"):
            return None
        url_hash = get_url_hash(url)
        safe_voice = re.sub(r'[^a-zA-Z0-9_-]', '_', voice_id)
        audio_file = AUDIO_DIR / f"{url_hash}_{sid}_{mode}_{safe_voice}.mp3"
        if audio_file.exists():
            try:
                content = audio_file.read_bytes()
                if len(content) > 100:
                    return content
            except Exception:
                return None
        return None

    def save_audio_cache(self, url: str, sid: str, mode: str, voice_id: str, audio: bytes):
        """
        Lưu âm thanh MP3 vào cache tạm thời tách biệt rõ theo mode ('orig' hoặc 'vi')
        và cập nhật ngay chỉ mục file MP3 vào JSON của trang web tương ứng.
        """
        if not url or not sid or mode not in ("orig", "vi") or not audio or len(audio) < 100:
            return
        url_hash = get_url_hash(url)
        safe_voice = re.sub(r'[^a-zA-Z0-9_-]', '_', voice_id)
        filename = f"{url_hash}_{sid}_{mode}_{safe_voice}.mp3"
        audio_file = AUDIO_DIR / filename
        try:
            audio_file.write_bytes(audio)
        except Exception:
            return

        with _CACHE_LOCK:
            current = self._memory_cache.get(url_hash)
            if current:
                states = current.setdefault("states", {
                    "orig": {"voice_id": "", "audio_files": {}},
                    "vi": {"voice_id": "", "audio_files": {}}
                })
                mode_state = states.setdefault(mode, {"voice_id": voice_id, "audio_files": {}})
                mode_state["voice_id"] = voice_id
                audio_files = mode_state.setdefault("audio_files", {})
                audio_files[sid] = filename
                mode_state["ready_audio_count"] = len(audio_files)

                field_name = "orig_audio_file" if mode == "orig" else "vi_audio_file"
                for s in current.get("sentences", []):
                    if s.get("sid") == sid:
                        s[field_name] = filename
                        break

                self._write_json_unlocked(url_hash, current)

    def clear_audio_cache(self):
        """Xóa toàn bộ file audio MP3 cũ khi đổi giọng đọc để tổng hợp lại từ đầu theo giọng mới."""
        with _CACHE_LOCK:
            if AUDIO_DIR.exists():
                for p in AUDIO_DIR.glob("*.mp3"):
                    try:
                        p.unlink()
                    except Exception:
                        pass

    def clear_all(self):
        """Xóa sạch 100% dữ liệu cache tạm (JSON và MP3) khi tắt chương trình."""
        with _CACHE_LOCK:
            self._memory_cache.clear()
            if CACHE_DIR.exists():
                try:
                    shutil.rmtree(CACHE_DIR, ignore_errors=True)
                except Exception:
                    pass
            self._ensure_dirs()


page_cache_manager = PageCacheManager.get_instance()

# Đăng ký tự động dọn dẹp khi tiến trình Python kết thúc
atexit.register(page_cache_manager.clear_all)
