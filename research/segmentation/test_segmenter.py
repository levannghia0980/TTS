# -*- coding: utf-8 -*-
"""
Unit Tests & Stress Tests cho Prosody-aware Text Segmenter (PTS)
và tích hợp với FastAPI Backend.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.services.text_segmenter import (
    SegmenterConfig,
    detect_tts_engine,
    is_cjk,
    is_space,
    resolve_segmenter_config,
    segment_spans,
    split_into_chunks,
    split_sentences,
)
from app.services.tts_service import split_sub_chunks


def eff_len(s: str, cjk_weight: float = 3.0) -> float:
    return sum(cjk_weight if is_cjk(ch) else 1.0 for ch in s)


def strip_all_ws(s: str) -> str:
    return "".join(ch for ch in s if not is_space(ch))


class TestPTSSentenceBoundary(unittest.TestCase):
    def test_vietnamese_titles_numbers_urls(self):
        text = (
            "PGS. TS. Nguyễn Văn A tại TP. HCM công bố báo cáo phiên bản 3.14 "
            "trên https://nlp.lab.vn/paper.pdf?id=42 lúc 10:30 ngày 21/11/2026. "
            "Kinh phí dự án khoảng 1.250.000.000 đồng."
        )
        sents = split_sentences(text)
        self.assertEqual(len(sents), 2)
        self.assertTrue(sents[0].startswith("PGS. TS. Nguyễn Văn A"))
        self.assertTrue(sents[1].startswith("Kinh phí"))

    def test_dialogue_lowercase_continuation(self):
        text = '"Đi thôi!" hắn nói khẽ rồi quay lưng đi. Ngoài trời vẫn mưa.'
        sents = split_sentences(text)
        self.assertEqual(len(sents), 2)
        self.assertIn('"Đi thôi!" hắn nói khẽ', sents[0])

    def test_english_abbreviations_initials_and_files(self):
        text = (
            "Dr. J. K. Rowling met Prof. Smith at 10:30 a.m. in Washington, e.g. near the U.S. Capitol. "
            "Node.js v20.18.0 works well."
        )
        sents = split_sentences(text)
        self.assertEqual(len(sents), 2)
        self.assertIn("U.S. Capitol.", sents[0])
        self.assertTrue(sents[1].startswith("Node.js"))

    def test_chinese_unspaced_terminals_and_quotes(self):
        text = "自从2004年提出了构想。今天下午我们在图书馆讨论最新论文。"
        sents = split_sentences(text)
        self.assertEqual(len(sents), 2)
        self.assertEqual(sents[0], "自从2004年提出了构想。")
        self.assertEqual(sents[1], "今天下午我们在图书馆讨论最新论文。")
        # Hội thoại tiếng Trung có ngoặc đóng
        qtext = "他说：“我们走吧！”他转身离开了。"
        qsents = split_sentences(qtext)
        self.assertEqual(qsents, ["他说：“我们走吧！”", "他转身离开了。"])

    def test_list_item_prefix_not_orphaned(self):
        text = "1. Khái niệm cơ bản về phân đoạn văn bản.\n2. Thuật toán quy hoạch động."
        sents = split_sentences(text)
        self.assertEqual(len(sents), 2)
        self.assertTrue(sents[0].startswith("1. Khái niệm"))
        self.assertTrue(sents[1].startswith("2. Thuật toán"))


class TestPTSProsodicChunkingAndLossless(unittest.TestCase):
    def test_lossless_and_hard_length_constraint(self):
        samples = [
            "Trong hệ thống tổng hợp tiếng nói hiện đại, việc phân tách một đoạn văn bản dài thành các cụm ngữ điệu tự nhiên — không cắt ngang tên riêng như Nguyễn Văn An hay từ ghép — là yếu tố then chốt để giữ nhịp đọc ổn định cho người nghe.",
            "The magnolia warbler breeds across northern coniferous forests; however, during autumn migration, individuals travel thousands of kilometers southward while relying on celestial cues and geomagnetic orientation.",
            "国际北极研究中心的主要伙伴是日本和美国，参与会务的还有来自加拿大、中国、丹麦、德国、日本、挪威、俄罗斯、英国和美国的代表，共同推动极地生态系统的长期监测。",
            "1. " + " ".join(["từ"] * 60) + ".",
            "X" * 165 + " cuối câu.",
        ]
        for max_c in (80, 120):
            for text in samples:
                chunks = split_into_chunks(text, max_chars=max_c)
                self.assertEqual(strip_all_ws("".join(chunks)), strip_all_ws(text))
                for ch in chunks:
                    self.assertLessEqual(eff_len(ch), max_c + 1e-9, f"Exceeded L_max={max_c}: {ch}")

    def test_protected_entities_never_split(self):
        text = (
            "Người dùng có thể truy cập địa chỉ tài liệu chính thức https://sub.domain.example.org/docs/v2.0/api?lang=vi "
            "hoặc liên hệ với ban quản trị qua hộp thư contact.research@university.edu.vn trước hạn cuối."
        )
        chunks = split_into_chunks(text, max_chars=120)
        joined_ws = " | ".join(chunks)
        self.assertIn("https://sub.domain.example.org/docs/v2.0/api?lang=vi", joined_ws)
        self.assertIn("contact.research@university.edu.vn", joined_ws)

    def test_dp_avoids_stranded_function_word_and_prefers_clause_boundary(self):
        sent = (
            "Các nghiên cứu thực nghiệm về mô hình ngôn ngữ cỡ nhỏ đã chỉ ra nhiều hạn chế đáng kể, "
            "tuy nhiên phương pháp mới lại đạt hiệu năng ổn định trên tập kiểm thử."
        )
        chunks = split_into_chunks(sent, max_chars=120)
        self.assertEqual(len(chunks), 2)
        # Phải ngắt ngay sau dấu phẩy, trước "tuy nhiên"
        self.assertTrue(chunks[0].endswith(","))
        self.assertTrue(chunks[1].startswith("tuy nhiên"))

    def test_dp_protects_listnum_and_titles_from_splitting(self):
        text = (
            "1. Đây là một câu liệt kê rất dài trong tài liệu chuyên ngành để đảm bảo số thứ tự đầu dòng luôn đi liền với phần mở đầu của câu."
        )
        chunks = split_into_chunks(text, max_chars=120)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertNotEqual(chunks[0].strip(), "1.")
        self.assertTrue(chunks[0].startswith("1. Đây"))

    def test_chinese_particle_left_attachment_and_prep_right_attachment(self):
        # Không được cắt ngay trước trợ từ hậu trí '的' hay ngay sau giới từ '在'
        sent = "研究人员在北极地区长期观测气候变化规律的科学报告引起了广泛关注和深入讨论。"
        chunks = split_into_chunks(sent, max_chars=80)  # <= ~26 chữ Hán mỗi chunk
        self.assertGreaterEqual(len(chunks), 2)
        for ch in chunks[1:]:
            self.assertFalse(ch.startswith("的"), f"Chunk started with enclitic 的: {chunks}")
        for ch in chunks[:-1]:
            self.assertFalse(ch.endswith("在"), f"Chunk ended with proclitic 在: {chunks}")

    def test_never_forces_artificial_65_60_split_over_real_comma(self):
        # Câu 125 ký tự chỉ có duy nhất 1 dấu phẩy tự nhiên ở cuối (~114 ký tự + 11 ký tự)
        sent = (
            "Tôi đã đi đến siêu thị mua rất nhiều thực phẩm tươi sống cho bữa tiệc sinh nhật "
            "tối nay cùng tất cả gia đình bạn bè, rất vui."
        )
        chunks = split_into_chunks(sent, max_chars=120)
        self.assertEqual(len(chunks), 2)
        # BẮT BUỘC ngắt tại dấu phẩy thật, KHÔNG được cắt giả kiểu 65+60 vào giữa cụm từ!
        self.assertTrue(chunks[0].endswith(","), f"Broke artificially mid-clause instead of real comma: {chunks}")
        self.assertEqual(chunks[1], "rất vui.")

    def test_orphan_shifts_only_to_earlier_real_clause_boundary(self):
        # Khi CÓ một dấu phẩy/liên từ sớm hơn (~78 ký tự), DP đẩy lùi về đó để tránh mẩu vụn 8 ký tự
        sent = (
            "Phương pháp thử nghiệm đạt kết quả khá tốt trên nhiều tập dữ liệu mở rộng, "
            "tuy nhiên tốc độ xử lý vẫn cần tối ưu hóa thêm nữa."
        )
        chunks = split_into_chunks(sent, max_chars=120)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith(","))
        self.assertTrue(chunks[1].startswith("tuy nhiên"))

    def test_story_vs_general_adaptive_chunking_and_engines(self):
        # 1. Story giữ thoại ngắn liền hơi thay vì băm vụn 3-4 ký tự
        dialogue = '"Hả?" "Thật sao?!" Anh ta nhìn sững vào tờ giấy trên bàn.'
        story_cfg = resolve_segmenter_config(profile="story", voice_id="BV074_streaming")
        gen_cfg = resolve_segmenter_config(profile="general", voice_id="BV074_streaming")
        story_chunks = split_into_chunks(dialogue, cfg=story_cfg)
        gen_chunks = split_into_chunks(dialogue, cfg=gen_cfg)
        self.assertEqual(story_chunks[0], '"Hả?" "Thật sao?!"')
        self.assertEqual(gen_chunks[0], '"Hả?"')

        # 2. Thích ứng theo TTS Engine: câu 155 ký tự bị chia 2 ở CapCut (120) nhưng giữ nguyên 1 khối ở Edge (220) & Local (160)
        medium_sent = (
            "Hệ thống xử lý ngôn ngữ tự nhiên thế hệ mới có thể chuyển đổi toàn bộ bài báo khoa học "
            "sang giọng đọc truyền cảm mượt mà với độ trễ cực thấp trên trình duyệt."
        )
        self.assertEqual(detect_tts_engine("vi-VN-HoaiMyNeural"), "edge")
        self.assertEqual(detect_tts_engine("local_ngoc_huyen_new"), "local")
        self.assertEqual(detect_tts_engine("BV074_streaming"), "capcut")
        self.assertEqual(len(split_into_chunks(medium_sent, cfg=resolve_segmenter_config("general", "vi-VN-HoaiMyNeural"))), 1)
        self.assertEqual(len(split_into_chunks(medium_sent, cfg=resolve_segmenter_config("general", "local_ngoc_huyen_new"))), 1)
        self.assertGreaterEqual(len(split_into_chunks(medium_sent, cfg=resolve_segmenter_config("general", "BV074_streaming"))), 2)

    def test_backend_integration_tts_and_session(self):
        sub = split_sub_chunks(
            "PGS. TS. Trần Văn B tại TP. HCM đã trình bày hệ thống xử lý ngôn ngữ mới; kết quả thực nghiệm cho thấy độ trễ giảm rõ rệt.",
            max_chars=100,
        )
        self.assertEqual(len(sub), 2)
        self.assertTrue(sub[0].endswith(";"))

        client = TestClient(app)
        resp = client.post(
            "/api/v1/session/start",
            json={
                "session_id": "test_pts_integration",
                "blocks": [
                    {
                        "xid": "b-0",
                        "text": "PGS. TS. Trần Văn B đến từ TP. HCM. Ông công bố bản 3.14 tại https://a.b/c, và đồng thời chia sẻ dữ liệu mở cho cộng đồng.",
                    }
                ],
                "lang": "vi",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        sents = [s["original"] for s in data["sentences"]]
        self.assertGreaterEqual(len(sents), 2)
        # Không bị cắt bậy tại PGS. hay TP. hay 3.14
        self.assertTrue(sents[0].startswith("PGS. TS. Trần Văn B đến từ TP. HCM."))
        # Dọn phiên test
        client.delete("/api/v1/session/test_pts_integration")


if __name__ == "__main__":
    unittest.main(verbosity=2)
