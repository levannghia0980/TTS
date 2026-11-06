# -*- coding: utf-8 -*-
import os
import re
import time
import json
import asyncio
import threading
import httpx
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.translation_profiles import get_system_prompt_for_profile

_PACING_LOCK = threading.Lock()
_LAST_GEMINI_REQUEST_TIME = 0.0

DEFAULT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"}
]


VI_DIACRITICS_REGEX = re.compile(
    r"[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹý]",
    re.IGNORECASE
)
ENGLISH_COMMON_WORDS_REGEX = re.compile(
    r"\b(the|and|or|of|in|to|with|is|are|was|were|have|has|for|from|by|at|this|that|these|those|which|their|they|male|males|female|females)\b",
    re.IGNORECASE
)
CJK_CHARS_REGEX = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def is_valid_vietnamese_translation(translated: str, original: str = "", src_lang: str = "en") -> bool:
    """
    Kiểm tra tính hợp lệ của bản dịch tiếng Việt:
    TUYỆT ĐỐI không cho phép văn bản tiếng Anh, chữ Hán/Nhật/Hàn chưa dịch hay số thứ tự rác lọt vào làm bản dịch!
    """
    if not translated or not translated.strip():
        return False
    t = translated.strip()
    o = original.strip() if original else ""

    if src_lang == "vi":
        return True

    # 1. Trùng y hệt bản gốc (ngoại trừ từ quá ngắn <= 4 ký tự)
    if o and t.lower() == o.lower() and len(o) > 4:
        return False

    # 2. Xóa tiền tố số nếu LLM để sót (ví dụ "13 ")
    t_clean = re.sub(r'^\d+\s*\|*\|*\s*', '', t).strip()
    if not t_clean:
        return False

    # 3. Nếu còn chứa ký tự chữ Hán / Nhật / Hàn (CJK) chưa dịch -> Loại bỏ ngay để không đọc tiếng Trung ở luồng VI!
    if CJK_CHARS_REGEX.search(t_clean):
        return False

    has_vi_diacritic = bool(VI_DIACRITICS_REGEX.search(t_clean))
    eng_words = ENGLISH_COMMON_WORDS_REGEX.findall(t_clean)

    # 4. Nếu không có dấu tiếng Việt nào và có từ tiếng Anh phổ biến -> 100% tiếng Anh chưa dịch!
    if not has_vi_diacritic and len(eng_words) >= 1 and len(t_clean) > 12:
        return False

    # 5. Nếu không có dấu tiếng Việt và dài hơn 25 ký tự toàn ký tự ASCII -> tiếng Anh!
    if not has_vi_diacritic and len(t_clean) > 25 and t_clean.isascii():
        return False

    return True


def clean_tts_text(text: str) -> str:
    """Làm sạch văn bản triệt để trước khi đưa vào TTS."""
    if not text:
        return ""
    t = text.strip()
    # 0. Gỡ bỏ tiền tố số hoặc phân cách thừa [ID]||| nếu LLM để sót
    t = re.sub(r'^\d+\s*\|*\|*\s*', '', t).strip()
    # 1. Bóc các số chú thích tham chiếu và nút biên tập dạng [1], [12], [note 1], [citation needed], [edit], [sửa]
    t = re.sub(
        r'\[\s*(?:\d+|note\s*\d+|citation\s*needed|cần\s*dẫn\s*nguồn|edit|sửa(?:\s*\|\s*sửa\s*mã\s*nguồn)?)\s*\]',
        '',
        t,
        flags=re.IGNORECASE
    )
    # 2. Xóa các ký hiệu markdown **, ##, ``, ~~
    t = re.sub(r'[*_~`#]', '', t)
    # 3. Chuẩn hóa khoảng trắng thừa
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def get_pacing_delay(min_interval: float = 4.1) -> float:
    """Điều tiết giãn cách request tối thiểu 4.1s để không chạm ngưỡng 15 RPM của Gemini Free Tier."""
    global _LAST_GEMINI_REQUEST_TIME
    with _PACING_LOCK:
        now = time.time()
        elapsed = now - _LAST_GEMINI_REQUEST_TIME
        if elapsed < min_interval:
            delay = min_interval - elapsed
            _LAST_GEMINI_REQUEST_TIME = now + delay
            return delay
        else:
            _LAST_GEMINI_REQUEST_TIME = now
            return 0.0


class TranslateService:
    @classmethod
    async def translate_single(
        cls,
        text: str,
        profile: str = "general",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        max_retries: int = 2
    ) -> str:
        if not text or not text.strip():
            return ""

        key = (api_key or settings.GEMINI_API_KEY or "").strip()
        if not key:
            raise ValueError("Chưa cấu hình Google Gemini API Key! Vui lòng cài đặt key trong Settings.")

        chosen_model = model or settings.GEMINI_MODEL or "gemini-3.1-flash-lite"
        if chosen_model not in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"):
            chosen_model = "gemini-3.1-flash-lite"

        system_instruction = get_system_prompt_for_profile(profile)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{chosen_model}:generateContent?key={key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\nNội dung cần dịch sang tiếng Việt:\n{text.strip()}"}
                    ]
                }
            ],
            "safetySettings": DEFAULT_SAFETY_SETTINGS,
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.95,
                "maxOutputTokens": 8192
            }
        }

        last_error = None
        for attempt in range(1, max_retries + 1):
            delay = get_pacing_delay(min_interval=4.1)
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                async with httpx.AsyncClient(timeout=40.0) as client:
                    resp = await client.post(url, json=payload)

                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return clean_tts_text(parts[0].get("text", "").strip())
                        return ""

                    if resp.status_code == 429:
                        await asyncio.sleep(10.0 * attempt)
                        continue

                    if resp.status_code == 503:
                        await asyncio.sleep(10.0 * attempt)
                        continue

                    err_msg = resp.text
                    try:
                        err_json = resp.json()
                        err_msg = err_json.get("error", {}).get("message", err_msg)
                    except Exception:
                        pass
                    raise RuntimeError(f"Lỗi Gemini API ({resp.status_code}): {err_msg}")

            except httpx.RequestError as exc:
                last_error = exc
                if attempt < max_retries:
                    await asyncio.sleep(4.0 * attempt)
                    continue
                raise RuntimeError(f"Lỗi kết nối Gemini API sau {max_retries} lần thử: {str(exc)}") from exc

        if last_error:
            raise last_error
        return ""

    @classmethod
    async def translate_batch(
        cls,
        texts: List[str],
        profile: str = "general",
        model: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Dịch gộp cả batch nhiều câu trong DUY NHẤT 1 request Gemini.
        Sử dụng định dạng phân dòng [ID]|||[Bản dịch] chống vỡ cú pháp 100%.
        TUYỆT ĐỐI KHÔNG rơi vào vòng lặp gọi đơn lẻ để tránh spam request.
        """
        if not texts:
            return []

        # Chuẩn bị danh sách theo dòng đánh số
        lines = [f"{idx}|||{t.strip()}" for idx, t in enumerate(texts)]
        input_text = "\n".join(lines)

        system_instruction = get_system_prompt_for_profile(profile)
        prompt = f"""{system_instruction}

NHIỆM VỤ: Dịch danh sách các câu sau sang tiếng Việt tự nhiên và trôi chảy.
QUY TẮC ĐỊNH DẠNG BẮT BUỘC:
1. Trả về kết quả theo định dạng phân dòng: [Chỉ_số]|||[Bản_dịch_tiếng_Việt]
   Ví dụ:
   0|||Chim chích mộc lan là một loài chim...
   1|||Loài này được mô tả lần đầu vào năm 1811...
2. Bảo toàn 100% tất cả các chỉ số số nguyên ở đầu dòng (từ 0 đến {len(texts) - 1}), không gộp câu, không bỏ sót câu nào.
3. Mỗi câu nằm trên đúng một dòng riêng biệt.
4. KHÔNG bọc markdown ```, KHÔNG thêm bất kỳ lời dẫn hay giải thích nào.

Danh sách các câu cần dịch:
{input_text}"""

        mapping: Dict[int, str] = {}
        try:
            raw_output = await cls.translate_single(prompt, profile=profile, model=model, api_key=api_key)
            if raw_output:
                # Bóc tách bằng re.split để bắt trọn vẹn kể cả khi LLM không xuống dòng
                tokens = re.split(r'(\d+)\s*\|\|\|\s*', raw_output)
                for i in range(1, len(tokens), 2):
                    try:
                        line_idx = int(tokens[i])
                        trans_text = clean_tts_text(tokens[i + 1])
                        if trans_text:
                            mapping[line_idx] = trans_text
                    except Exception:
                        pass
        except Exception:
            pass

        results = []
        for idx, orig in enumerate(texts):
            trans = (mapping.get(idx) or "").strip()
            # Làm sạch và loại bỏ tiền tố số rác nếu LLM để sót
            trans = clean_tts_text(trans)
            # Kiểm tra nghiêm ngặt tính hợp lệ của tiếng Việt
            if not is_valid_vietnamese_translation(trans, original=orig, src_lang="en"):
                trans = ""
            results.append({
                "index": idx,
                "original": orig,
                "translated": trans
            })
        return results
