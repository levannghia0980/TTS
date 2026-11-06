import os
import re
import io
import time
import base64
import random
import asyncio
import httpx
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.capcut_api.client import CapCutClient
from app.services.capcut_api.models import DeviceConfig


def strip_leading_numbering(text: str) -> str:
    """
    Xóa sạch 100% số thứ tự đầu câu (ví dụ: '1. ', '02. ', '3: ', '4 - ', '[5] ', '(6) ', 'Câu 7: ', '1/100 '):
    Đảm bảo khi gửi sang CapCut/Edge TTS, giọng đọc KHÔNG đọc 'Một chấm...', 'Hai chấm...'.
    """
    if not text:
        return ""
    t = text.strip()
    # 1. Bóc ngoặc vuông / ngoặc tròn / ngoặc nhọn chứa số ở đầu: [1], (1), {1}, 【1】
    t = re.sub(r'^(?:\[\s*\d+\s*\]|\(\s*\d+\s*\)|\{\s*\d+\s*\}|【\s*\d+\s*】)\s*[\.\:\-\–\—\s]*', '', t)
    # 2. Bóc các tiền tố dạng: Câu 1:, Thoại 1:, Đoạn 1:, STT 1:, Line 1:
    t = re.sub(r'^(?:câu|thoại|đoạn|stt|dòng|line)\s*\d+\s*[\.\:\-\–\—\)\/\]\s]*\s*', '', t, flags=re.IGNORECASE)
    # 3. Bóc dạng phân số/tổng số câu: 1/100 
    t = re.sub(r'^\d+\/\d+\s*[\.\:\-\–\—\s]*', '', t)
    # 4. Bóc số thứ tự đầu câu kèm dấu phân cách: 1. , 12. , 1: , 1 - , 1) 
    t = re.sub(r'^\d+\s*[\.\:\-\–\—\)\/\]]+\s*', '', t)
    # 5. Dọn dẹp dấu câu thừa còn sót lại ở đầu chuỗi sau khi bóc số
    t = re.sub(r'^[^\w\s\(\[\{]+', '', t).strip()
    # 6. Xóa các thẻ HTML/XML nếu có (vd: <s>, </s>, <p>...)
    t = re.sub(r'<[^>]+>', '', t).strip()
    return t


def split_sub_chunks(text: str, max_chars: int = 120) -> List[str]:
    """
    Cắt các câu dài theo dấu câu ở giữa câu (phẩy, chấm phẩy, gạch ngang, liên từ)
    để đảm bảo CapCut TTS không bao giờ bị quá tải hoặc từ chối request.
    """
    if not text or len(text) <= max_chars:
        return [text] if text else []

    # Cắt theo dấu phẩy, chấm phẩy, hai chấm, gạch ngang hoặc liên từ
    parts = re.split(r'([,;:—–\-]|\s+(?:và|nhưng|mà|cùng|hoặc)\s+)', text)
    chunks = []
    current = ""
    for p in parts:
        if not p:
            continue
        if len(current) + len(p) <= max_chars:
            current += p
        else:
            if current.strip():
                chunks.append(current.strip())
            current = p
    if current.strip():
        chunks.append(current.strip())

    # Nếu vẫn còn mẩu nào dài hơn max_chars (câu dài không có dấu câu), cắt theo từ
    final_chunks = []
    for c in chunks:
        if len(c) <= max_chars:
            final_chunks.append(c)
        else:
            words = c.split()
            w_buf = ""
            for w in words:
                if len(w_buf) + len(w) + 1 <= max_chars:
                    w_buf = f"{w_buf} {w}".strip()
                else:
                    if w_buf:
                        final_chunks.append(w_buf)
                    w_buf = w
            if w_buf:
                final_chunks.append(w_buf)

    return final_chunks if final_chunks else [text]


_LOCAL_PIPER_VOICE = None

def get_local_piper_voice():
    """Nạp và cache mô hình Piper Ngọc Huyền New vào RAM duy nhất 1 lần."""
    global _LOCAL_PIPER_VOICE
    if _LOCAL_PIPER_VOICE is not None:
        return _LOCAL_PIPER_VOICE
    model_path = settings.LOCAL_PIPER_MODEL_PATH
    config_path = settings.LOCAL_PIPER_CONFIG_PATH
    if os.path.exists(model_path):
        try:
            from piper.voice import PiperVoice
            _LOCAL_PIPER_VOICE = PiperVoice.load(
                model_path,
                config_path=config_path if os.path.exists(config_path) else None
            )
            return _LOCAL_PIPER_VOICE
        except Exception:
            return None
    return None


class TTSService:
    @classmethod
    def synthesize_local_piper(cls, text: str, speed: float = 1.0) -> Optional[bytes]:
        """Tổng hợp âm thanh offline bằng mô hình Ngọc Huyền New (AIRead Piper VITS)."""
        voice = get_local_piper_voice()
        if not voice:
            return None
        import io, wave, numpy as np
        from piper.config import SynthesisConfig
        syn_config = SynthesisConfig(
            length_scale=1.0 / speed if speed > 0 else 1.0,
            noise_scale=0.667,
            noise_w_scale=0.8,
            normalize_audio=True
        )
        buffer = io.BytesIO()
        try:
            with wave.open(buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(voice.config.sample_rate)
                for chunk in voice.synthesize(text, syn_config=syn_config):
                    audio_int16 = (chunk.audio_float_array * 32767).astype(np.int16)
                    wav_file.writeframes(audio_int16.tobytes())
            res = buffer.getvalue()
            return res if len(res) > 100 else None
        except Exception:
            return None

    @classmethod
    async def synthesize_edge_tts(cls, text: str, voice: str = "vi-VN-HoaiMyNeural", speed: float = 1.0) -> Optional[bytes]:
        """Đọc bằng Edge-TTS (Microsoft Neural)."""
        import edge_tts
        try:
            rate_str = "+0%"
            if speed > 1.0:
                rate_str = f"+{int((speed - 1.0) * 100)}%"
            elif speed < 1.0:
                rate_str = f"-{int((1.0 - speed) * 100)}%"

            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            audio_buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])
            if len(audio_buffer) > 100:
                return bytes(audio_buffer)
        except Exception:
            pass
        return None

    @classmethod
    async def synthesize_capcut_sami(cls, text: str, voice_code: str = "BV074_streaming", max_retries: int = 2) -> Optional[bytes]:
        """Đọc bằng CapCut Global SAMI API (Singapore Akamai CDN)."""
        cookie = settings.CAPCUT_COOKIE or settings.TIKTOK_SESSION_ID or ""
        dev = DeviceConfig.create_random()
        client = CapCutClient(device=dev, cookie=cookie)

        for attempt in range(1, max_retries + 1):
            try:
                url, headers, body_text = client.build_tts_new_request([text], voice=voice_code)
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    res = await http_client.post(url, headers=headers, content=body_text.encode("utf-8"))
                    if res.status_code == 200:
                        data = res.json()
                        tasks = (data.get("data") or {}).get("tasks") or []
                        if tasks:
                            task_id = tasks[0].get("id")
                            token = tasks[0].get("token")
                            if task_id and token:
                                for _ in range(12):
                                    await asyncio.sleep(0.35)
                                    q_url, q_headers, q_body = client.build_query_request(task_id, token, mode="tts")
                                    q_res = await http_client.post(q_url, headers=q_headers, content=q_body.encode("utf-8"))
                                    if q_res.status_code == 200:
                                        q_data = q_res.json()
                                        q_tasks = (q_data.get("data") or {}).get("tasks") or []
                                        if q_tasks:
                                            first_task = q_tasks[0]
                                            status = first_task.get("status")
                                            if status in ("success", "succeed"):
                                                payload_raw = first_task.get("payload") or "{}"
                                                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
                                                subs = payload.get("audio_subtitles") or []
                                                if subs and subs[0].get("speech_url"):
                                                    speech_url = subs[0]["speech_url"]
                                                    async with httpx.AsyncClient(timeout=15.0) as dl_client:
                                                        down_res = await dl_client.get(speech_url, headers={"User-Agent": "Mozilla/5.0"})
                                                        if down_res.status_code == 200 and len(down_res.content) > 100:
                                                            return down_res.content
                                                return None
                                            elif status == "failed":
                                                return None
            except Exception:
                if attempt < max_retries:
                    await asyncio.sleep(0.5)
                    continue
        return None

    @classmethod
    async def synthesize_tiktok_tts(cls, text: str, voice_code: str = "BV074_streaming") -> Optional[bytes]:
        """Tạo âm thanh qua TikTok TTS API siêu tốc chuẩn ReviewMatThon (Tự động xoay AID 1233 & 1180, Fake VN IP)."""
        url = "https://api16-normal-v4.tiktokv.com/media/api/text/speech/invoke/"
        session_id = settings.TIKTOK_SESSION_ID or settings.CAPCUT_COOKIE or "410bfa37bdc185e1c6da82e1afb48409"
        
        # Tạo IP Việt Nam ngụy trang để bypass rate limit
        fake_ip = f"118.69.{random.randint(1, 254)}.{random.randint(1, 254)}"
        headers = {
            "Cookie": f"sessionid={session_id}",
            "User-Agent": "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_ES; SM-G988N; Build/NRD90M;tt-ok/3.12.13.1)",
            "X-Forwarded-For": fake_ip,
            "Client-IP": fake_ip,
            "X-Real-IP": fake_ip,
        }

        # Thử lần 1 với AID 1233, nếu gặp lỗi thử ngay AID 1180
        for aid in ["1233", "1180"]:
            params = {
                "text_speaker": voice_code,
                "req_text": text,
                "speaker_map_type": "0",
                "aid": aid,
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, headers=headers, params=params)
                    if res.status_code == 200:
                        data = res.json()
                        status_code = data.get("status_code", -1)
                        if status_code == 0:
                            v_str = (data.get("data") or {}).get("v_str", "")
                            if v_str:
                                return base64.b64decode(v_str)
            except Exception:
                continue

        return None

    @classmethod
    async def synthesize_bytes(cls, text: str, voice_id: Optional[str] = None, speed: float = 1.0) -> Optional[bytes]:
        """
        Tổng hợp âm thanh trả về bytes nhị phân MP3 hoàn chỉnh.
        Tự động cắt sub-chunk câu dài theo dấu câu và GHÉP NỐI âm thanh,
        KHÓA CỨNG 100% đúng giọng người dùng chọn, tuyệt đối không nhảy giọng bừa bãi.
        """
        clean_text = strip_leading_numbering(text)
        if not clean_text:
            return None

        voice = voice_id or settings.SELECTED_VOICE or "BV074_streaming"

        # 1. Nếu là giọng Local Offline (Ngọc Huyền New)
        if voice == "local_ngoc_huyen_new" or voice.startswith("local_"):
            return cls.synthesize_local_piper(clean_text, speed=speed)

        is_edge = "Neural" in voice or voice.startswith("vi-VN-") or voice in ("hoaimy", "namminh")

        # Cắt sub-chunks nếu câu dài
        sub_chunks = split_sub_chunks(clean_text, max_chars=120)
        audio_parts: List[bytes] = []

        for sub in sub_chunks:
            part_bytes = None
            if is_edge:
                actual_edge_voice = "vi-VN-HoaiMyNeural" if "hoaimy" in voice.lower() else voice
                part_bytes = await cls.synthesize_edge_tts(sub, voice=actual_edge_voice, speed=speed)
            else:
                # 1. Thử TikTok TTS API siêu tốc với giọng CapCut đã chọn
                part_bytes = await cls.synthesize_tiktok_tts(sub, voice_code=voice)
                # 2. Thử lại nếu gặp sự cố mạng
                if not part_bytes:
                    part_bytes = await cls.synthesize_tiktok_tts(sub, voice_code=voice)
                # 3. Nếu TikTok chưa hỗ trợ mã giọng này, dùng CapCut SAMI với đúng mã giọng đó
                if not part_bytes:
                    part_bytes = await cls.synthesize_capcut_sami(sub, voice_code=voice)

            if part_bytes and len(part_bytes) > 50:
                audio_parts.append(part_bytes)

        if audio_parts:
            # Nối các phần âm thanh lại thành 1 file MP3 duy nhất
            return b"".join(audio_parts)

        return None

    @classmethod
    async def synthesize_single(cls, text: str, voice_id: Optional[str] = None, speed: float = 1.0) -> Dict[str, Any]:
        """Tổng hợp âm thanh cho 1 câu văn bản (kèm Base64)."""
        clean_text = strip_leading_numbering(text)
        if not clean_text:
            return {"status": "error", "message": "Văn bản rỗng sau khi làm sạch", "audio_base64": ""}

        voice = voice_id or settings.SELECTED_VOICE or "BV074_streaming"
        audio_bytes = await cls.synthesize_bytes(clean_text, voice_id=voice, speed=speed)

        if audio_bytes and len(audio_bytes) > 100:
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            return {
                "status": "success",
                "voice": voice,
                "clean_text": clean_text,
                "audio_base64": f"data:audio/mp3;base64,{b64_audio}",
                "size_bytes": len(audio_bytes)
            }
        else:
            return {
                "status": "error",
                "message": "Không thể tạo âm thanh từ các nhà cung cấp TTS",
                "audio_base64": ""
            }

    @classmethod
    async def synthesize_batch(
        cls,
        sentences: List[Dict[str, str]],
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        max_workers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        concurrency = max_workers or settings.TTS_MAX_WORKERS or 32
        semaphore = asyncio.Semaphore(concurrency)

        async def worker(item: Dict[str, str]) -> Dict[str, Any]:
            async with semaphore:
                res = await cls.synthesize_single(item.get("text", ""), voice_id=voice_id, speed=speed)
                return {
                    "id": item.get("id"),
                    "text": item.get("text"),
                    **res
                }

        tasks = [worker(item) for item in sentences]
        results = await asyncio.gather(*tasks)
        return list(results)
