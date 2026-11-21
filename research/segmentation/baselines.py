# -*- coding: utf-8 -*-
"""
Các phương pháp Baseline và biến thể Ablation để đối chiếu với PTS
=================================================================

1. `regex_legacy_split`: Thuật toán regex cũ trong `extension/src/content/splitter.ts`
   trước khi nâng cấp (tách bằng regex dấu kết câu -> regex dấu phẩy/liên từ -> cắt từ).
2. `greedy_word_split`: Baseline tham lam tối thiểu hóa số chunk (nhồi tối đa
   ký tự/từ vào mỗi chunk miễn <= max_chars).
3. `greedy_punct_split`: Baseline tách câu cơ bản, nếu vượt max_chars thì tham lam
   lùi về dấu câu gần nhất <= max_chars (nếu không có dấu câu mới lùi về khoảng trắng).
4. Ablation của PTS (dùng `SegmenterConfig`):
   - PTS w/o DP      (`use_dp=False`)
   - PTS w/o Spans   (`use_spans=False`)
   - PTS w/o Lexicon (`use_lexicon=False`)
   - PTS Full        (tất cả thành phần bật)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.text_segmenter import (
    SegmenterConfig,
    is_cjk,
    is_space,
    split_into_chunks,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Legacy Regex Baseline (bản gốc trong splitter.ts trước khi nâng cấp)
# ─────────────────────────────────────────────────────────────────────────────

_LEGACY_SENT_RE = re.compile(r"(?<=[.?!…\n。！？])\s+")
_LEGACY_CLAUSE_RE = re.compile(
    r"([,;:—–\-\,\;\:\，\；\：]+|\s+(?:và|nhưng|mà|cùng|hoặc|and|but|or|while)\s+)"
)


def _eff_len(s: str, cjk_weight: float = 3.0) -> float:
    return sum(cjk_weight if is_cjk(ch) else 1.0 for ch in s)


def regex_legacy_split(raw_text: str, max_chars: int = 120, cjk_weight: float = 3.0) -> List[str]:
    """Tái hiện chính xác logic `splitter.ts` ban đầu (dùng cho bảng so sánh before/after)."""
    if not raw_text or not raw_text.strip():
        return []

    raw_sentences = [s.strip() for s in _LEGACY_SENT_RE.split(raw_text) if s.strip()]
    clause_chunks: List[str] = []

    for sent in raw_sentences:
        if len(sent) <= max_chars:
            clause_chunks.append(sent)
            continue

        parts = _LEGACY_CLAUSE_RE.split(sent)
        current_buf = ""
        for part in parts:
            if not part:
                continue
            if len(current_buf) + len(part) <= max_chars:
                current_buf += part
            else:
                if current_buf.strip():
                    clause_chunks.append(current_buf.strip())
                current_buf = part
        if current_buf.strip():
            clause_chunks.append(current_buf.strip())

    final_chunks: List[str] = []
    for c in clause_chunks:
        if len(c) <= max_chars:
            final_chunks.append(c)
        else:
            words = c.split()
            buf = ""
            for w in words:
                cand = f"{buf} {w}" if buf else w
                if len(cand) <= max_chars:
                    buf = cand
                else:
                    if buf:
                        final_chunks.append(buf)
                    buf = w
            if buf:
                final_chunks.append(buf)

    return [s for s in final_chunks if len(s) > 1]


def regex_legacy_sbd(raw_text: str) -> List[str]:
    """Tách câu theo regex cũ (hoặc tách thêm sau dấu 。！？ khi thiếu space ở CJK)."""
    if not raw_text or not raw_text.strip():
        return []
    return [s.strip() for s in _LEGACY_SENT_RE.split(raw_text) if s.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Greedy Word Baseline (Cắt tham lam cực đại theo từ / chữ Hán)
# ─────────────────────────────────────────────────────────────────────────────

def greedy_word_split(text: str, max_chars: int = 120, cjk_weight: float = 3.0) -> List[str]:
    if not text or not text.strip():
        return []
    n = len(text)
    P = [0.0] * (n + 1)
    for i, ch in enumerate(text):
        P[i + 1] = P[i] + (cjk_weight if is_cjk(ch) else 1.0)

    out: List[str] = []
    i = 0
    while i < n:
        while i < n and is_space(text[i]):
            i += 1
        if i >= n:
            break
        # Tìm vị trí xa nhất sao cho P[j] - P[i] <= max_chars
        j = i
        while j < n and (P[j + 1] - P[i]) <= max_chars:
            j += 1
        if j == i:
            j = i + 1
        if j < n and not is_cjk(text[j]) and not is_space(text[j]):
            k = j
            while k > i and not is_space(text[k]) and not is_cjk(text[k - 1]):
                k -= 1
            if k > i:
                j = k
        end = j
        while end > i and is_space(text[end - 1]):
            end -= 1
        if end > i:
            out.append(text[i:end])
        i = j
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Greedy Punctuation Baseline (Tách câu + lùi về dấu câu gần max_chars nhất)
# ─────────────────────────────────────────────────────────────────────────────

_PUNCT_BREAK = set(".!?…‼⁇⁈⁉。！？;；:：—–,，、")


def greedy_punct_split(text: str, max_chars: int = 120, cjk_weight: float = 3.0) -> List[str]:
    if not text or not text.strip():
        return []
    out: List[str] = []
    for sent in regex_legacy_sbd(text):
        n = len(sent)
        P = [0.0] * (n + 1)
        for i, ch in enumerate(sent):
            P[i + 1] = P[i] + (cjk_weight if is_cjk(ch) else 1.0)
        if P[n] <= max_chars:
            out.append(sent)
            continue
        i = 0
        while i < n:
            while i < n and is_space(sent[i]):
                i += 1
            if i >= n:
                break
            if (P[n] - P[i]) <= max_chars:
                out.append(sent[i:].strip())
                break
            limit = i
            while limit < n and (P[limit + 1] - P[i]) <= max_chars:
                limit += 1
            if limit == i:
                limit = i + 1
            # Tìm dấu câu cuối cùng nằm trọn trong [i, limit)
            cut = -1
            for k in range(limit, i, -1):
                if sent[k - 1] in _PUNCT_BREAK and (k == limit or is_space(sent[k]) or is_cjk(sent[k])):
                    cut = k
                    break
            if cut == -1:
                for k in range(limit, i, -1):
                    if is_space(sent[k]) or is_cjk(sent[k]):
                        cut = k
                        break
            if cut <= i:
                cut = limit
            frag = sent[i:cut].strip()
            if frag:
                out.append(frag)
            i = cut
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 4. Các biến thể PTS (Full + Ablation)
# ─────────────────────────────────────────────────────────────────────────────

def pts_full_split(text: str, max_chars: int = 120) -> List[str]:
    return split_into_chunks(text, cfg=SegmenterConfig(max_chars=max_chars))


def pts_balanced_kp_split(text: str, max_chars: int = 120) -> List[str]:
    """Đối chứng: cân bằng độ dài kiểu Knuth-Plass (alpha=6.0, dễ cắt kiểu 65+60 giữa cụm)."""
    return split_into_chunks(
        text,
        cfg=SegmenterConfig(
            max_chars=max_chars,
            target_ratio=0.6,
            alpha=6.0,
            split_penalty=0.0,
            orphan_penalty=6.0,
        ),
    )


def pts_no_dp_split(text: str, max_chars: int = 120) -> List[str]:
    return split_into_chunks(text, cfg=SegmenterConfig(max_chars=max_chars, use_dp=False))


def pts_no_spans_split(text: str, max_chars: int = 120) -> List[str]:
    return split_into_chunks(text, cfg=SegmenterConfig(max_chars=max_chars, use_spans=False))


def pts_no_lexicon_split(text: str, max_chars: int = 120) -> List[str]:
    return split_into_chunks(text, cfg=SegmenterConfig(max_chars=max_chars, use_lexicon=False))
