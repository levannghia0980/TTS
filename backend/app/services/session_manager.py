# -*- coding: utf-8 -*-
"""
Session Manager - Dual Audio Pool
==================================
Mỗi ReaderSession quản lý 2 pool âm thanh song song:
  • orig_audio: TTS bản gốc (không dịch) - bắt đầu tạo NGAY KHI phiên khởi động
  • vi_audio  : TTS bản dịch VI (Gemini) - chỉ bắt đầu khi người dùng bật chế độ dịch

Logic ưu tiên:
1. Câu 0 & 1 bản gốc sẵn sàng trong < 0.5s (zero-wait startup)
2. Worker pool 4 luồng song song tạo orig_audio liên tục
3. Khi switch sang VI: pipeline dịch + vi_audio chạy song song
4. Hover bất kỳ câu nào → audio sẵn sàng ngay (đã cache) hoặc tổng hợp khẩn cấp

Page Cache (LRU max 5 trang):
  • Lưu URL + title + (câu đầu orig_audio + vi_audio) theo URL trang
  • Tắt chương trình → giải phóng toàn bộ
"""
import time
import asyncio
import logging
from collections import OrderedDict
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.constants.voices import get_male_voice_for_lang
from app.services.translate_service import TranslateService, clean_tts_text, is_valid_vietnamese_translation
from app.services.tts_service import TTSService
from app.services.page_cache_manager import page_cache_manager

logger = logging.getLogger(__name__)


class SentenceItem:
    """Đơn vị câu/vế câu: giữ cả bản gốc lẫn bản dịch, 2 pool audio riêng biệt."""

    def __init__(self, index: int, original: str, translated: str = "", xid: str = "", sid: str = ""):
        self.index = index
        self.xid = xid
        self.sid = sid or f"s-{index}"
        self.original = original.strip()
        self.translated = clean_tts_text(translated)

        # Pool âm thanh
        self.orig_audio: Optional[bytes] = None
        self.vi_audio: Optional[bytes] = None

        # Events để chờ async
        self.orig_event: asyncio.Event = asyncio.Event()
        self.vi_event: asyncio.Event = asyncio.Event()

        # Trạng thái
        self.orig_status: str = "pending"   # pending | synthesizing | ready | error
        self.vi_status: str = "pending"     # pending | translating | translated | synthesizing | ready | error

        # Nếu câu đã có bản dịch sẵn từ trước (tiếng Việt)
        if self.translated:
            self.vi_status = "translated"

    def set_translated(self, text: str):
        self.translated = clean_tts_text(text)
        if self.vi_status in ("pending", "translating"):
            self.vi_status = "translated"

    def set_orig_audio(self, audio: bytes):
        self.orig_audio = audio
        self.orig_status = "ready"
        self.orig_event.set()

    def set_vi_audio(self, audio: bytes):
        self.vi_audio = audio
        self.vi_status = "ready"
        self.vi_event.set()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "sid": self.sid,
            "xid": self.xid,
            "original": self.original,
            "translated": self.translated,
        }


class ReaderSession:
    def __init__(
        self,
        session_id: str,
        raw_items: List[Dict[str, Any]],
        profile: str = "general",
        orig_voice_id: Optional[str] = None,
        vi_voice_id: Optional[str] = None,
        speed: float = 1.0,
        model: Optional[str] = None,
        page_url: str = "",
        page_lang: str = "en",
    ):
        self.session_id = session_id
        self.profile = profile
        self.page_url = page_url
        self.page_lang = page_lang

        # orig_voice: giọng nam auto-detect theo ngôn ngữ trang
        self.orig_voice_id = orig_voice_id or get_male_voice_for_lang(page_lang)
        # vi_voice: giọng do người dùng chọn trong settings (mặc định giọng Việt)
        self.vi_voice_id = vi_voice_id or settings.SELECTED_VOICE or "BV074_streaming"

        self.speed = speed
        self.model = model or settings.GEMINI_MODEL or "gemini-2.0-flash-lite"
        self.created_at = time.time()
        self.last_active = time.time()
        self.current_index = 0
        self.is_closed = False

        # Chế độ hiện tại: 'orig' (bản gốc) hoặc 'vi' (bản dịch Việt)
        self.current_mode: str = "orig"
        self._vi_pipeline_started = False

        self.sentences: List[SentenceItem] = []
        for idx, it in enumerate(raw_items):
            orig = it.get("text") or it.get("original") or ""
            trans = it.get("translated") or ""
            xid = it.get("xid") or f"xid-{idx}"
            sid = it.get("sid") or f"s-{idx}"
            self.sentences.append(SentenceItem(index=idx, original=orig, translated=trans, xid=xid, sid=sid))

        # 3. Tự động nạp nhanh các câu đã dịch và MP3 đã tạo từ cache link web nếu có (zero-wait)
        self._load_from_page_cache()
        self._save_to_page_cache()

        # Priority queues cho từng pool
        self.orig_priority_queue: asyncio.Queue[int] = asyncio.Queue()
        self.vi_priority_queue: asyncio.Queue[int] = asyncio.Queue()

        # Task handles
        self.orig_pipeline_task: Optional[asyncio.Task] = None
        self.vi_pipeline_task: Optional[asyncio.Task] = None
        self.orig_worker_tasks: List[asyncio.Task] = []
        self.vi_worker_tasks: List[asyncio.Task] = []

    def _load_from_page_cache(self):
        """
        Nạp nhanh các câu đã được dịch và các file MP3 đã tổng hợp (cho cả 'orig' và 'vi')
        từ cache JSON & đĩa theo link web (tránh gọi lại Gemini / TTS khi chuyển qua lại).
        """
        if not self.page_url:
            return
        cached = page_cache_manager.get_page_cache(self.page_url)
        sid_map: Dict[str, str] = {}
        orig_map: Dict[str, str] = {}
        if cached:
            cached_sentences = cached.get("sentences", [])
            sid_map = {s["sid"]: s.get("translated", "") for s in cached_sentences if s.get("sid")}
            orig_map = {s.get("original", "").strip(): s.get("translated", "") for s in cached_sentences if s.get("original")}

        trans_hit = 0
        orig_audio_hit = 0
        vi_audio_hit = 0

        for s in self.sentences:
            if not s.translated:
                trans = sid_map.get(s.sid) or orig_map.get(s.original)
                if trans:
                    trans = clean_tts_text(trans)
                if trans and is_valid_vietnamese_translation(trans, original=s.original, src_lang=self.page_lang):
                    s.set_translated(trans)
                    trans_hit += 1

            # Nạp sẵn MP3 bản gốc ('orig') nếu đã có trong cache đĩa
            if not s.orig_audio:
                cached_orig_mp3 = page_cache_manager.get_audio_cache(
                    self.page_url, s.sid, "orig", self.orig_voice_id
                )
                if cached_orig_mp3:
                    s.set_orig_audio(cached_orig_mp3)
                    orig_audio_hit += 1

            # Nạp sẵn MP3 bản dịch ('vi') nếu đã có trong cache đĩa
            if not s.vi_audio and s.translated:
                cached_vi_mp3 = page_cache_manager.get_audio_cache(
                    self.page_url, s.sid, "vi", self.vi_voice_id
                )
                if cached_vi_mp3:
                    s.set_vi_audio(cached_vi_mp3)
                    vi_audio_hit += 1

        if trans_hit > 0 or orig_audio_hit > 0 or vi_audio_hit > 0:
            logger.info(
                f"[Page Cache Hit] URL={self.page_url} | Trans={trans_hit}/{len(self.sentences)} | "
                f"OrigMP3={orig_audio_hit} | ViMP3={vi_audio_hit}"
            )

    def _save_to_page_cache(self):
        """Lưu lại tiến độ dịch và cấu trúc 2 trạng thái ('orig' / 'vi') vào cache JSON theo link web."""
        if not self.page_url:
            return
        page_cache_manager.save_page_cache(
            url=self.page_url,
            profile=self.profile,
            lang=self.page_lang,
            sentences=[s.to_dict() for s in self.sentences],
            orig_voice_id=self.orig_voice_id,
            vi_voice_id=self.vi_voice_id
        )

    def touch(self):
        self.last_active = time.time()

    # ─── KHỞI ĐỘNG ──────────────────────────────────────────────────────────

    def start(self):
        """Khởi động đồng thời cả 2 pipeline (Bản gốc + Bản dịch Chunk 1) ngay khi mở trang!"""
        if self.orig_pipeline_task is None or self.orig_pipeline_task.done():
            self.orig_pipeline_task = asyncio.create_task(self._run_orig_pipeline())
        if self.vi_pipeline_task is None or self.vi_pipeline_task.done():
            self.vi_pipeline_task = asyncio.create_task(self._run_vi_pipeline())

    def start_vi_pipeline(self):
        """Kích hoạt dịch toàn bộ nội dung còn lại (Chunk 2) khi người dùng bật chế độ Dịch."""
        if self.vi_pipeline_task is None or self.vi_pipeline_task.done():
            self.vi_pipeline_task = asyncio.create_task(self._run_vi_pipeline())

    # ─── PIPELINE BẢN GỐC ───────────────────────────────────────────────────

    async def _run_orig_pipeline(self):
        """
        Pipeline bản gốc (KHÔNG dịch):
        1. Tạo ngay TTS cho 4 câu đầu tiên (Câu 0, 1, 2, 3) SONG SONG bằng asyncio.gather.
        2. Khởi động 4 TTS worker chạy ngầm gối đầu liên tục cho toàn bộ các câu tiếp theo.
        """
        total = len(self.sentences)
        if total == 0 or self.is_closed:
            return

        INIT_SIZE = min(4, total)

        async def synth_orig(idx: int):
            if self.is_closed:
                return
            item = self.sentences[idx]
            if not item.orig_audio:
                # 1. Thử lấy từ cache audio theo link web
                cached_audio = page_cache_manager.get_audio_cache(
                    self.page_url, item.sid, "orig", self.orig_voice_id
                )
                if cached_audio:
                    item.set_orig_audio(cached_audio)
                    return

                item.orig_status = "synthesizing"
                audio = await TTSService.synthesize_bytes(
                    item.original, voice_id=self.orig_voice_id, speed=self.speed
                )
                if audio and not self.is_closed:
                    item.set_orig_audio(audio)
                    page_cache_manager.save_audio_cache(
                        self.page_url, item.sid, "orig", self.orig_voice_id, audio
                    )
                else:
                    item.orig_status = "error"

        # Tạo song song cả 4 câu đầu tiên
        await asyncio.gather(*[synth_orig(i) for i in range(INIT_SIZE)])

        # Khởi động 4 worker TTS bản gốc gối đầu liên tục
        for _ in range(4):
            task = asyncio.create_task(self._orig_tts_worker())
            self.orig_worker_tasks.append(task)

    async def _orig_tts_worker(self):
        """Worker tạo audio bản gốc liên tục, tự động gối đầu các câu phía trước."""
        total = len(self.sentences)
        while not self.is_closed:
            target_idx = None

            # Kiểm tra priority queue (từ hover/seek)
            try:
                target_idx = self.orig_priority_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

            # Tìm câu chưa có orig_audio gần nhất phía trước current_index
            if target_idx is None:
                cur = self.current_index
                for offset in range(total):
                    candidate = (cur + offset) % total
                    s = self.sentences[candidate]
                    if not s.orig_audio and s.orig_status not in ("synthesizing", "ready", "error"):
                        target_idx = candidate
                        s.orig_status = "synthesizing"
                        break

            if target_idx is None or target_idx >= total:
                await asyncio.sleep(0.25)
                continue

            item = self.sentences[target_idx]
            if item.orig_audio:
                continue

            item.orig_status = "synthesizing"
            try:
                # 1. Thử lấy từ cache audio theo link web
                cached_audio = page_cache_manager.get_audio_cache(
                    self.page_url, item.sid, "orig", self.orig_voice_id
                )
                if cached_audio:
                    item.set_orig_audio(cached_audio)
                    continue

                audio = await TTSService.synthesize_bytes(
                    item.original, voice_id=self.orig_voice_id, speed=self.speed
                )
                if audio and not self.is_closed:
                    item.set_orig_audio(audio)
                    page_cache_manager.save_audio_cache(
                        self.page_url, item.sid, "orig", self.orig_voice_id, audio
                    )
                else:
                    item.orig_status = "error"
            except Exception as e:
                logger.warning(f"[Orig TTS Worker] Lỗi câu {target_idx}: {e}")
                item.orig_status = "error"

    # ─── PIPELINE TIẾNG VIỆT ────────────────────────────────────────────────

    async def _run_vi_pipeline(self):
        """
        Pipeline dịch thuật & TTS Tiếng Việt:
        1. Tự động dịch toàn bộ trang web trong nền (Chunk 1 theo hết đoạn văn <1.5s, Chunk 2 tiếp nối ngay).
        2. Tạo ngay TTS cho 4 câu đầu tiên tiếng Việt song song mà không làm nghẽn tiến độ dịch.
        3. Khởi động 4 worker TTS VI chạy gối đầu liên tục.
        """
        total = len(self.sentences)
        if total == 0 or self.is_closed:
            return

        # 1. Khởi chạy luồng dịch toàn bộ trang độc lập trong nền
        asyncio.create_task(self._translate_all_chunks())

        # 2. Khởi chạy luồng TTS VI song song
        asyncio.create_task(self._run_vi_tts_init())

    async def _translate_all_chunks(self):
        """Dịch toàn bộ bài viết: Chunk 1 (căn hết đoạn văn ~45 câu), Chunk 2 (toàn bộ phần còn lại)."""
        total = len(self.sentences)
        if total == 0 or self.is_closed:
            return

        # Căn chỉnh Chunk 1 theo ranh giới đoạn văn (xid) để TUYỆT ĐỐI KHÔNG cắt ngang giữa một đoạn
        target_end = min(45, total)
        if target_end < total:
            target_xid = self.sentences[target_end - 1].xid
            while target_end < total and self.sentences[target_end].xid == target_xid:
                target_end += 1
        CHUNK_1_SIZE = target_end

        # --- CHUNK 1 (Dịch siêu tốc các đoạn đầu < 1.5s) ---
        chunk1 = [s for s in self.sentences[:CHUNK_1_SIZE] if not s.translated]
        if chunk1 and not self.is_closed:
            try:
                texts = [s.original for s in chunk1]
                results = await TranslateService.translate_batch(
                    texts, profile=self.profile, model=self.model
                )
                for res, item in zip(results, chunk1):
                    trans = clean_tts_text(res.get("translated") or "")
                    if trans and is_valid_vietnamese_translation(trans, original=item.original, src_lang=self.page_lang):
                        item.set_translated(trans)
                # Lưu ngay Chunk 1 vào cache JSON theo URL
                self._save_to_page_cache()
            except Exception as e:
                logger.warning(f"[VI Pipeline] Lỗi dịch Chunk 1 ({self.session_id}): {e}")

        # --- CHUNK 2: Tự động dịch tiếp TOÀN BỘ PHẦN CÒN LẠI ngay lập tức trong nền ---
        if total > CHUNK_1_SIZE and not self.is_closed:
            chunk2 = [s for s in self.sentences[CHUNK_1_SIZE:] if not s.translated]
            MAX_BATCH = 100
            for start_i in range(0, len(chunk2), MAX_BATCH):
                if self.is_closed:
                    break
                batch = chunk2[start_i:start_i + MAX_BATCH]
                try:
                    texts = [s.original for s in batch]
                    results = await TranslateService.translate_batch(
                        texts, profile=self.profile, model=self.model
                    )
                    for res, item in zip(results, batch):
                        trans = clean_tts_text(res.get("translated") or "")
                        if trans and is_valid_vietnamese_translation(trans, original=item.original, src_lang=self.page_lang):
                            item.set_translated(trans)
                    # Cập nhật cache JSON theo URL sau mỗi batch dịch
                    self._save_to_page_cache()
                except Exception as e:
                    logger.warning(f"[VI Pipeline] Lỗi dịch Chunk 2 ({self.session_id}): {e}")

    async def _run_vi_tts_init(self):
        """Chờ câu 0..3 có bản dịch rồi tạo ngay TTS 4 câu đầu song song, sau đó bật worker."""
        total = len(self.sentences)
        INIT_SIZE = min(4, total)

        # Chờ tối đa 15 giây để Chunk 1 dịch xong bản dịch tiếng Việt
        for _ in range(75):
            if self.is_closed:
                return
            if all(self.sentences[i].translated for i in range(INIT_SIZE)):
                break
            await asyncio.sleep(0.2)

        async def synth_vi(idx: int):
            if self.is_closed:
                return
            item = self.sentences[idx]
            if not item.vi_audio:
                # 1. Thử lấy từ cache audio theo link web
                cached_audio = page_cache_manager.get_audio_cache(
                    self.page_url, item.sid, "vi", self.vi_voice_id
                )
                if cached_audio:
                    item.set_vi_audio(cached_audio)
                    return

                # TUYỆT ĐỐI KHÔNG fallback sang item.original khi ở chế độ VI!
                if not item.translated:
                    return

                text_to_speak = item.translated
                item.vi_status = "synthesizing"
                audio = await TTSService.synthesize_bytes(
                    text_to_speak, voice_id=self.vi_voice_id, speed=self.speed
                )
                if audio and not self.is_closed:
                    item.set_vi_audio(audio)
                    page_cache_manager.save_audio_cache(
                        self.page_url, item.sid, "vi", self.vi_voice_id, audio
                    )
                else:
                    item.vi_status = "error"

        # Tạo song song 4 câu đầu TTS VI
        await asyncio.gather(*[synth_vi(i) for i in range(INIT_SIZE)])

        # Khởi động 4 worker TTS VI chạy gối đầu liên tục
        for _ in range(4):
            task = asyncio.create_task(self._vi_tts_worker())
            self.vi_worker_tasks.append(task)

    async def _vi_tts_worker(self):
        """Worker tạo audio VI (đã dịch) liên tục."""
        total = len(self.sentences)
        while not self.is_closed:
            target_idx = None

            try:
                target_idx = self.vi_priority_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

            if target_idx is None:
                cur = self.current_index
                for offset in range(total):
                    candidate = (cur + offset) % total
                    s = self.sentences[candidate]
                    if s.translated and not s.vi_audio and s.vi_status not in ("synthesizing", "ready", "error"):
                        target_idx = candidate
                        s.vi_status = "synthesizing"
                        break

            if target_idx is None or target_idx >= total:
                await asyncio.sleep(0.25)
                continue

            item = self.sentences[target_idx]
            if item.vi_audio:
                continue
            if not item.translated:
                await asyncio.sleep(0.2)
                continue

            item.vi_status = "synthesizing"
            try:
                # 1. Thử lấy từ cache audio theo link web
                cached_audio = page_cache_manager.get_audio_cache(
                    self.page_url, item.sid, "vi", self.vi_voice_id
                )
                if cached_audio:
                    item.set_vi_audio(cached_audio)
                    continue

                audio = await TTSService.synthesize_bytes(
                    item.translated, voice_id=self.vi_voice_id, speed=self.speed
                )
                if audio and not self.is_closed:
                    item.set_vi_audio(audio)
                    page_cache_manager.save_audio_cache(
                        self.page_url, item.sid, "vi", self.vi_voice_id, audio
                    )
                else:
                    item.vi_status = "error"
            except Exception as e:
                logger.warning(f"[VI TTS Worker] Lỗi câu {target_idx}: {e}")
                item.vi_status = "error"

    # ─── SEEK & MODE SWITCH ──────────────────────────────────────────────────

    def _drain_priority_queue(self, q: asyncio.Queue):
        """Xóa các yêu cầu ưu tiên tồn đọng cũ trong queue khi chuyển trạng thái/seek."""
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

    def seek(self, index: int):
        """Cập nhật con trỏ đọc, ưu tiên audio cho câu đích và 3 câu tiếp theo (bộ đệm 4 câu)."""
        self.touch()
        if not (0 <= index < len(self.sentences)):
            return
        self.current_index = index

        # Ưu tiên tạo trước 4 câu gối đầu liên tục cho pool đang hoạt động
        for offset in range(4):
            idx = index + offset
            if 0 <= idx < len(self.sentences):
                s = self.sentences[idx]
                if self.current_mode == "orig":
                    if not s.orig_audio:
                        self.orig_priority_queue.put_nowait(idx)
                else:
                    if not s.vi_audio:
                        self.vi_priority_queue.put_nowait(idx)

    def switch_mode(self, to: str):
        """
        Chuyển giữa 'orig' và 'vi':
        - Giữ nguyên toàn bộ cache JSON & MP3 của cả hai trạng thái ('orig' và 'vi') để tái sử dụng tức thì.
        - Dọn sạch hàng đợi ưu tiên tạm thời của trạng thái cũ.
        - Đưa con trỏ đọc về câu đầu tiên (index 0) của trạng thái mới.
        """
        if to not in ("orig", "vi"):
            return
        self.current_mode = to
        self._drain_priority_queue(self.orig_priority_queue)
        self._drain_priority_queue(self.vi_priority_queue)
        if to == "vi":
            self.start_vi_pipeline()
        # Luôn reset về câu số 1 (index 0) của trạng thái vừa chọn
        self.current_index = 0
        self.seek(0)

    def change_voice(self, new_vi_voice_id: str):
        """
        Đổi sang giọng đọc tiếng Việt mới:
        1. Xóa toàn bộ audio vi_audio trong RAM.
        2. Hủy các worker tạo audio của giọng cũ.
        3. Cập nhật vi_voice_id = new_vi_voice_id.
        4. Reset con trỏ đọc về câu số 1 (index 0).
        5. Tạo lại audio mới từ câu số 1 theo đúng giọng mới!
        """
        if not new_vi_voice_id or new_vi_voice_id == self.vi_voice_id:
            return
        logger.info(f"[{self.session_id}] Cập nhật giọng đọc mới: {self.vi_voice_id} -> {new_vi_voice_id}")
        self.vi_voice_id = new_vi_voice_id

        # Hủy worker cũ
        for task in self.vi_worker_tasks:
            if not task.done():
                task.cancel()
        self.vi_worker_tasks.clear()
        if self.vi_pipeline_task and not self.vi_pipeline_task.done():
            self.vi_pipeline_task.cancel()

        # Xóa toàn bộ audio vi cũ trong RAM
        for s in self.sentences:
            s.vi_audio = None
            s.vi_status = "idle"
            s.vi_event.clear()

        # Reset về câu số 1
        self.current_index = 0
        self._save_to_page_cache()

        # Khởi động lại pipeline tạo audio giọng mới từ câu đầu
        self.vi_pipeline_task = asyncio.create_task(self._run_vi_tts_init())

    # ─── LẤY AUDIO ──────────────────────────────────────────────────────────

    async def get_orig_audio(self, index: int, timeout: float = 6.0) -> Optional[bytes]:
        """Lấy audio bản gốc ('orig'). Tái sử dụng ngay nếu đã có trong RAM hoặc cache đĩa."""
        self.touch()
        if not (0 <= index < len(self.sentences)):
            return None

        item = self.sentences[index]
        if item.orig_audio:
            return item.orig_audio

        cached_audio = page_cache_manager.get_audio_cache(
            self.page_url, item.sid, "orig", self.orig_voice_id
        )
        if cached_audio:
            item.set_orig_audio(cached_audio)
            return cached_audio

        self.orig_priority_queue.put_nowait(index)

        try:
            await asyncio.wait_for(item.orig_event.wait(), timeout=timeout)
            return item.orig_audio
        except asyncio.TimeoutError:
            # Khẩn cấp: tổng hợp trực tiếp
            audio = await TTSService.synthesize_bytes(
                item.original, voice_id=self.orig_voice_id, speed=self.speed
            )
            if audio:
                item.set_orig_audio(audio)
                page_cache_manager.save_audio_cache(
                    self.page_url, item.sid, "orig", self.orig_voice_id, audio
                )
                return audio
            return None

    async def get_vi_audio(self, index: int, timeout: float = 8.0) -> Optional[bytes]:
        """Lấy audio bản dịch tiếng Việt ('vi'). Tái sử dụng ngay nếu đã có trong RAM hoặc cache đĩa."""
        self.touch()
        if not (0 <= index < len(self.sentences)):
            return None

        item = self.sentences[index]
        if item.vi_audio:
            return item.vi_audio

        cached_audio = page_cache_manager.get_audio_cache(
            self.page_url, item.sid, "vi", self.vi_voice_id
        )
        if cached_audio:
            item.set_vi_audio(cached_audio)
            return cached_audio

        # Đảm bảo pipeline VI đã chạy
        self.start_vi_pipeline()
        self.vi_priority_queue.put_nowait(index)

        # Nếu câu chưa được dịch: dịch khẩn cấp
        if not item.translated:
            try:
                trans = await TranslateService.translate_single(
                    item.original, profile=self.profile, model=self.model
                )
                if trans:
                    trans = clean_tts_text(trans)
                if trans and is_valid_vietnamese_translation(trans, original=item.original, src_lang=self.page_lang):
                    item.set_translated(trans)
                    self._save_to_page_cache()
            except Exception as e:
                logger.warning(f"[On-demand translate] câu {index}: {e}")

        try:
            await asyncio.wait_for(item.vi_event.wait(), timeout=timeout)
            return item.vi_audio
        except asyncio.TimeoutError:
            # Khẩn cấp
            if item.translated:
                audio = await TTSService.synthesize_bytes(
                    item.translated, voice_id=self.vi_voice_id, speed=self.speed
                )
                if audio:
                    item.set_vi_audio(audio)
                    page_cache_manager.save_audio_cache(
                        self.page_url, item.sid, "vi", self.vi_voice_id, audio
                    )
                    return audio
            return None

    # ─── Backward compat (cũ dùng get_audio_bytes) ───────────────────────────
    async def get_audio_bytes(self, index: int, timeout: float = 6.0) -> Optional[bytes]:
        """Tương thích ngược: lấy audio theo chế độ hiện tại."""
        if self.current_mode == "vi":
            return await self.get_vi_audio(index, timeout)
        return await self.get_orig_audio(index, timeout)

    # ─── STATUS ─────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        self.touch()
        total = len(self.sentences)
        orig_ready = sum(1 for s in self.sentences if s.orig_audio is not None)
        vi_ready = sum(1 for s in self.sentences if s.vi_audio is not None)
        translated_count = sum(1 for s in self.sentences if s.translated)

        current = self.sentences[self.current_index] if (0 <= self.current_index < total) else None
        next_s = self.sentences[self.current_index + 1] if (0 <= self.current_index + 1 < total) else None

        translated_list = [
            {"index": s.index, "xid": s.xid, "sid": s.sid, "translated": s.translated}
            for s in self.sentences if s.translated
        ]

        return {
            "session_id": self.session_id,
            "total_sentences": total,
            "current_mode": self.current_mode,
            "orig_ready_count": orig_ready,
            "vi_ready_count": vi_ready,
            "ready_audio_count": vi_ready if self.current_mode == "vi" else orig_ready,
            "translated_count": translated_count,
            "current_index": self.current_index,
            "orig_voice_id": self.orig_voice_id,
            "vi_voice_id": self.vi_voice_id,
            "current_sentence": {
                "index": self.current_index,
                "xid": current.xid if current else "",
                "sid": current.sid if current else "",
                "original": current.original if current else "",
                "translated": current.translated if current else "",
                "has_orig_audio": bool(current and current.orig_audio),
                "has_vi_audio": bool(current and current.vi_audio),
            } if current else None,
            "next_sentence": {
                "index": self.current_index + 1,
                "xid": next_s.xid if next_s else "",
                "sid": next_s.sid if next_s else "",
                "original": next_s.original if next_s else "",
                "translated": next_s.translated if next_s else "",
                "has_orig_audio": bool(next_s and next_s.orig_audio),
                "has_vi_audio": bool(next_s and next_s.vi_audio),
            } if next_s else None,
            "translated_items": translated_list,
            "is_complete": orig_ready == total and total > 0,
            "is_vi_complete": vi_ready == total and total > 0,
        }

    # ─── ĐÓNG PHIÊN ─────────────────────────────────────────────────────────

    def close(self):
        self.is_closed = True
        for task in [self.orig_pipeline_task, self.vi_pipeline_task]:
            if task and not task.done():
                task.cancel()
        for task in self.orig_worker_tasks + self.vi_worker_tasks:
            if not task.done():
                task.cancel()
        # Giải phóng RAM
        for s in self.sentences:
            s.orig_audio = None
            s.vi_audio = None
        self.sentences.clear()


# ─── SESSION MANAGER ────────────────────────────────────────────────────────

class SessionManager:
    _instance: Optional['SessionManager'] = None

    def __init__(self):
        self.sessions: Dict[str, ReaderSession] = {}

    @classmethod
    def get_instance(cls) -> 'SessionManager':
        if cls._instance is None:
            cls._instance = SessionManager()
        return cls._instance

    def create_session(
        self,
        session_id: str,
        raw_items: List[Dict[str, Any]],
        profile: str = "general",
        orig_voice_id: Optional[str] = None,
        vi_voice_id: Optional[str] = None,
        speed: float = 1.0,
        model: Optional[str] = None,
        page_url: str = "",
        page_lang: str = "en",
        lang: Optional[str] = None,
        # backward compat
        voice_id: Optional[str] = None,
    ) -> ReaderSession:
        # Tương thích ngược: nếu truyền voice_id cũ thì dùng làm vi_voice_id
        _vi_voice = vi_voice_id or voice_id
        _lang = lang or page_lang or "en"
        _orig_voice = orig_voice_id or get_male_voice_for_lang(_lang)

        if session_id in self.sessions:
            self.sessions[session_id].close()
            del self.sessions[session_id]

        self.cleanup_expired()

        session = ReaderSession(
            session_id=session_id,
            raw_items=raw_items,
            profile=profile,
            orig_voice_id=_orig_voice,
            vi_voice_id=_vi_voice,
            speed=speed,
            model=model,
            page_url=page_url,
            page_lang=_lang,
        )
        self.sessions[session_id] = session
        session.start()
        return session

    def get_session(self, session_id: str) -> Optional[ReaderSession]:
        return self.sessions.get(session_id)

    def close_session(self, session_id: str):
        if session_id in self.sessions:
            self.sessions[session_id].close()
            del self.sessions[session_id]

    def update_all_sessions_voice(self, new_voice: str):
        """Cập nhật giọng đọc tiếng Việt mới cho tất cả các session đang mở."""
        for s in list(self.sessions.values()):
            s.change_voice(new_voice)

    def cleanup_expired(self, max_idle_seconds: float = 3600.0):
        now = time.time()
        expired_ids = [
            sid for sid, s in self.sessions.items()
            if (now - s.last_active) > max_idle_seconds
        ]
        for sid in expired_ids:
            self.close_session(sid)


session_manager = SessionManager.get_instance()
