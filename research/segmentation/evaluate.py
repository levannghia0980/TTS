# -*- coding: utf-8 -*-
"""
Đánh giá thực nghiệm (Empirical Evaluation) cho Prosody-aware Text Segmenter (PTS)
=================================================================================

Ba bộ thí nghiệm chuẩn NLP + Web/TTS:
  1. Benchmark A — Sentence Boundary Detection (SBD) đa ngôn ngữ:
     - UD English-EWT (đoạn văn gốc đa câu `# newpar`)
     - UD Vietnamese-VTB (đoạn hội thoại/bài viết liên tiếp chuẩn hóa khoảng trắng dấu câu)
     - UD Chinese-GSDSimp (đoạn 5 câu liên tiếp)
     - Bộ Stress Web/TTS đa ngôn ngữ (viết tắt, số thập phân, URL, email, hội thoại, danh sách)
     So sánh: Regex (cũ), underthesea (cho tiếng Việt), PTS w/o Spans, PTS (Full).

  2. Benchmark B — Phân đoạn câu dài dưới ngưỡng Ràng buộc Độ dài (L_max = 80 & 120)
     đánh giá trực tiếp trên Cây Cú pháp Phụ thuộc Vàng (Universal Dependencies Trees):
     - Intra-Token / MWT Split Rate (%): Cắt ngang giữa từ đơn / từ ghép tiếng Việt!
     - Tight-Dependency Violation Rate (%): Cắt đứt quan hệ phụ thuộc chặt
       (case, det, mark, aux, cop, clf, compound, flat, fixed, nummod, goeswith).
     - Clause / Punctuation Alignment Rate (%): Điểm cắt trùng dấu câu / ranh giới mệnh đề
       (punct, conj, parataxis, advcl, ccomp, acl, cc, appos).
     - Mean Crossed Dependency Arcs: Độ sâu cắt cú pháp trung bình (càng thấp = càng giữ trọn cụm).
     - Length Balance CV(L) & Orphan Fragment Rate (< 16 ký tự hiệu dụng).
     So sánh 7 phương pháp: Regex (Legacy), Greedy-Word, Greedy-Punct,
     PTS w/o DP, PTS w/o Spans, PTS w/o Lexicon, PTS (Full).

  3. Benchmark C — Bảo toàn Thực thể & Độ trễ (Protected Entity Integrity & Runtime Latency).
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research" / "segmentation"))

from app.services.text_segmenter import is_cjk, resolve_segmenter_config, split_into_chunks, split_sentences
from baselines import (
    greedy_punct_split,
    greedy_word_split,
    pts_balanced_kp_split,
    pts_full_split,
    pts_no_dp_split,
    pts_no_lexicon_split,
    pts_no_spans_split,
    regex_legacy_sbd,
    regex_legacy_split,
)

UD_DIR = ROOT / "research" / "segmentation" / "data" / "ud"
OUT_JSON = ROOT / "research" / "segmentation" / "results.json"
OUT_MD = ROOT / "research" / "segmentation" / "REPORT.md"

TIGHT_RELS = {
    "case", "det", "mark", "aux", "cop", "clf", "compound", "flat", "fixed",
    "nummod", "goeswith", "reparandum",
}
CLAUSE_RELS = {
    "conj", "parataxis", "advcl", "ccomp", "acl", "cc", "appos", "list",
    "discourse", "vocative", "dislocated",
}
CLOSE_PUNCT_SET = set(".,;:!?)]}\"'”’»」』…、，；：！？）】》〉")
OPEN_PUNCT_SET = set("([{\"'“‘«「『（【《〈")


def eff_len(s: str, cjk_weight: float = 3.0) -> float:
    return sum(cjk_weight if is_cjk(ch) else 1.0 for ch in s)


# ─────────────────────────────────────────────────────────────────────────────
# Đọc & ánh xạ cây phụ thuộc Universal Dependencies (CoNLL-U)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UDToken:
    tid: int
    form: str
    upos: str
    head: int
    deprel: str
    base_rel: str
    start: int
    end: int


@dataclass
class UDSentence:
    sent_id: str
    newdoc: bool
    newpar: bool
    text: str
    tokens: List[UDToken]


def align_tokens_to_text(text: str, raw_tokens: List[Tuple[int, str, str, int, str]]) -> Optional[List[UDToken]]:
    """Ánh xạ chính xác từng token CoNLL-U vào offset ký tự [start, end) trong `text`."""
    aligned: List[UDToken] = []
    pos = 0
    n = len(text)
    for tid, form, upos, head, deprel in raw_tokens:
        while pos < n and text[pos].isspace():
            pos += 1
        # Thử tìm chính xác chuỗi token (kể cả từ ghép tiếng Việt có khoảng trắng bên trong)
        idx = text.find(form, pos)
        if idx == -1 or idx - pos > 6:
            # Thử chuẩn hóa khoảng trắng bên trong (MWT)
            form_ns = "".join(ch for ch in form if not ch.isspace())
            if not form_ns:
                return None
            # Quét tới khi khớp hết form_ns
            cur = pos
            while cur < n and text[cur].isspace():
                cur += 1
            start = cur
            collected = []
            while cur < n and len("".join(collected)) < len(form_ns):
                if not text[cur].isspace():
                    collected.append(text[cur])
                cur += 1
            if "".join(collected) != form_ns:
                return None
            end = cur
        else:
            start, end = idx, idx + len(form)
            pos = end
        pos = end
        aligned.append(UDToken(tid, form, upos, head, deprel, deprel.split(":")[0], start, end))
    return aligned


def parse_conllu(path: Path) -> List[UDSentence]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    blocks = [b.strip() for b in raw.strip().split("\n\n") if b.strip()]
    out: List[UDSentence] = []
    for b in blocks:
        sent_id = ""
        text = ""
        newdoc = False
        newpar = False
        raw_toks: List[Tuple[int, str, str, int, str]] = []
        for line in b.splitlines():
            if line.startswith("# newdoc"):
                newdoc = True
            elif line.startswith("# newpar"):
                newpar = True
            elif line.startswith("# sent_id ="):
                sent_id = line[len("# sent_id ="):].strip()
            elif line.startswith("# text ="):
                text = line[len("# text ="):].strip()
            elif not line.startswith("#"):
                cols = line.split("\t")
                if len(cols) >= 8 and "-" not in cols[0] and "." not in cols[0]:
                    raw_toks.append((int(cols[0]), cols[1], cols[3], int(cols[6]), cols[7]))
        aligned = align_tokens_to_text(text, raw_toks)
        if aligned is not None:
            out.append(UDSentence(sent_id, newdoc, newpar, text, aligned))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark A: Đánh giá Sentence Boundary Detection (SBD)
# ─────────────────────────────────────────────────────────────────────────────

def detokenize_vi_vtb(text: str) -> str:
    """Chuẩn hóa khoảng trắng dấu câu kiểu VTB về văn bản web tự nhiên (xóa space trước . , ? ! : ; ” ))."""
    out = re.sub(r'\s+([.,;:!?…\)\]])', r'\1', text)
    out = re.sub(r'([\(\[])\s+', r'\1', out)
    # Ghép dấu ngoặc kép thông minh theo cặp
    chars = []
    in_q = False
    i = 0
    while i < len(out):
        if out[i] == '"':
            if not in_q:
                # mở ngoặc kép: bỏ space sau "
                chars.append('"')
                if i + 1 < len(out) and out[i + 1] == " ":
                    i += 1
                in_q = True
            else:
                # đóng ngoặc kép: bỏ space trước "
                if chars and chars[-1] == " ":
                    chars.pop()
                chars.append('"')
                in_q = False
        else:
            chars.append(out[i])
        i += 1
    return "".join(chars)


def non_ws_end_positions(sentences: Sequence[str], full_text: str) -> Optional[set]:
    """Chuyển danh sách câu đầu ra thành tập vị trí kết thúc câu theo ký tự phi-khoảng-trắng."""
    cursor = 0
    ends = set()
    ns_total = 0
    ns_map: List[int] = []
    for idx, ch in enumerate(full_text):
        if not ch.isspace():
            ns_map.append(ns_total)
            ns_total += 1
        else:
            ns_map.append(ns_total)
    ns_map.append(ns_total)

    pos = 0
    for s in sentences[:-1]:
        s_ns = "".join(ch for ch in s if not ch.isspace())
        if not s_ns:
            continue
        # Khớp lần lượt từng ký tự non-ws trong full_text từ pos
        cur = pos
        matched = 0
        while cur < len(full_text) and matched < len(s_ns):
            if not full_text[cur].isspace():
                if full_text[cur] != s_ns[matched]:
                    return None
                matched += 1
            cur += 1
        if matched < len(s_ns):
            return None
        ends.add(ns_map[cur])
        pos = cur
    return ends


def eval_sbd_docs(docs: List[List[str]], sbd_fn: Callable[[str], List[str]], joiner: str = " ") -> Dict[str, float]:
    tp = fp = fn = 0
    for sents in docs:
        if len(sents) < 2:
            continue
        full = joiner.join(sents)
        gold_ends = non_ws_end_positions(sents, full)
        pred_sents = sbd_fn(full)
        pred_ends = non_ws_end_positions(pred_sents, full)
        if gold_ends is None or pred_ends is None:
            continue
        tp += len(gold_ends & pred_ends)
        fp += len(pred_ends - gold_ends)
        fn += len(gold_ends - pred_ends)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "precision": round(prec * 100, 2),
        "recall": round(rec * 100, 2),
        "f1": round(f1 * 100, 2),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def build_ud_sbd_datasets(en_sents: List[UDSentence], vi_sents: List[UDSentence], zh_sents: List[UDSentence]):
    # 1. EN-EWT: nhóm theo # newpar thực tế trong dữ liệu gốc
    en_docs: List[List[str]] = []
    cur: List[str] = []
    for s in en_sents:
        if (s.newdoc or s.newpar) and cur:
            en_docs.append(cur)
            cur = []
        cur.append(s.text)
    if cur:
        en_docs.append(cur)
    en_docs = [d for d in en_docs if len(d) >= 2]

    # 2. VI-VTB: nhóm các câu liên tiếp cùng nhóm `text-s*` hoặc khối 4 câu, detokenize tự nhiên
    vi_clean = [detokenize_vi_vtb(s.text) for s in vi_sents]
    vi_docs = [vi_clean[i:i + 4] for i in range(0, len(vi_clean) - 3, 4)]

    # 3. ZH-GSDSimp: nhóm 4 câu liên tiếp không có khoảng trắng giữa câu
    zh_clean = [s.text for s in zh_sents]
    zh_docs = [zh_clean[i:i + 4] for i in range(0, len(zh_clean) - 3, 4)]
    return en_docs, vi_docs, zh_docs


ADVERSARIAL_SBD_PASSAGES: List[List[str]] = [
    # Vietnamese web/news/fiction
    ["PGS. TS. Nguyễn Văn A công tác tại TP. HCM từ năm 2018.", "Ông vừa công bố mô hình mới v2.1 trên arXiv."],
    ["Giá cổ phiếu tăng 12,5% lên 145.000 đồng vào lúc 10:30 ngày 21/11/2026.", "Tuy nhiên, thanh khoản vẫn thấp."],
    ["Tài liệu gốc được lưu tại https://nlp.lab.edu.vn/docs/v1.0/readme.html?id=12.", "Bạn có thể tải về miễn phí."],
    ["Mọi góp ý xin gửi về hòm thư support.team@ai-research.vn trước thứ Sáu.", "Ban tổ chức sẽ phản hồi sớm."],
    ['"Đi thôi!" hắn nói khẽ rồi bước nhanh ra ngoài cửa.', "Trời bên ngoài đã tối sầm."],
    ["1. Mở đầu nghiên cứu về xử lý ngôn ngữ tự nhiên cho tiếng nói.", "Phần này trình bày động lực của đề tài."],
    ["Các kỹ thuật gồm tách câu, cân bằng độ dài, v.v. đều rất quan trọng.", "Ngoài ra còn cần kiểm thử tốc độ."],
    # English
    ["Dr. J. K. Rowling met Prof. Smith at 9:30 a.m. in Washington.", "They discussed e.g. transformers and TTS."],
    ["See Fig. 3 and No. 12 on pp. 45-48 of the Jan. 2025 issue.", "The proofs are straightforward."],
    ["The U.S. inflation rate dropped to 2.4% in Dec. 2025.", "Markets rallied immediately afterward."],
    ["Node.js v20.18.0 runs TypeScript bundles smoothly via esbuild.", "Latency stays under one millisecond."],
    ['"Wait a second!" she whispered nervously.', "Someone was knocking at the front door."],
    # Chinese
    ["自从2004年提出了兴建人文大楼的构想。", "企业界陆续有人提供捐款。"],
    ["他说：“我们明天上午9:30在北京大学见面！”", "随后他便转身离开了办公室。"],
    ["参考论文 https://arxiv.org/abs/2401.00001 中的方法。", "实验表明新算法准确率更高。"],
]


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark B: Đánh giá Cắt Chunk Cú pháp & Ngữ điệu trên cây UD
# ─────────────────────────────────────────────────────────────────────────────

def map_chunk_splits(sent: UDSentence, chunks: List[str]) -> Optional[List[int]]:
    """Tìm tất cả vị trí cắt nội bộ (theo char index trong sent.text) giữa chunks[k] và chunks[k+1]."""
    text = sent.text
    splits: List[int] = []
    pos = 0
    for k, ch in enumerate(chunks):
        c_ns = "".join(x for x in ch if not x.isspace())
        if not c_ns:
            continue
        cur = pos
        matched = 0
        while cur < len(text) and matched < len(c_ns):
            if not text[cur].isspace():
                if text[cur] != c_ns[matched]:
                    return None
                matched += 1
            cur += 1
        if matched < len(c_ns):
            return None
        if k + 1 < len(chunks):
            splits.append(cur)
        pos = cur
    return splits


def eval_ud_chunking(
    sents: List[UDSentence],
    chunker: Callable[[str], List[str]],
    max_chars: int,
) -> Dict[str, float]:
    """Đánh giá chi tiết chất lượng cắt câu dài trên cây phụ thuộc UD."""
    total_multi_sents = 0
    total_chunks = 0
    compliant_chunks = 0
    orphan_chunks = 0
    cvs: List[float] = []

    total_splits = 0
    intra_token_splits = 0
    tight_dep_violations = 0
    clause_punct_hits = 0
    mid_clause_unforced = 0
    avoidable_total = 0
    crossed_arcs_sum = 0
    lossless_ok = 0

    t0 = time.perf_counter()
    total_chars = 0

    for s in sents:
        if eff_len(s.text) <= max_chars:
            continue
        total_multi_sents += 1
        total_chars += len(s.text)
        chunks = chunker(s.text)
        if not chunks:
            continue

        # Lossless & length metrics
        reconstructed = "".join(x for ch in chunks for x in ch if not x.isspace())
        orig_ns = "".join(x for x in s.text if not x.isspace())
        if reconstructed == orig_ns:
            lossless_ok += 1

        effs = [eff_len(ch) for ch in chunks]
        total_chunks += len(chunks)
        compliant_chunks += sum(1 for L in effs if L <= max_chars + 1e-9)
        orphan_chunks += sum(1 for L in effs if L < min(16.0, max_chars * 0.3))
        if len(effs) >= 2 and statistics.mean(effs) > 0:
            cvs.append(statistics.pstdev(effs) / statistics.mean(effs))

        splits = map_chunk_splits(s, chunks)
        if not splits:
            continue

        toks = s.tokens
        id_to_idx = {t.tid: idx for idx, t in enumerate(toks)}
        has_internal_natural_pause = any(
            (tok.upos == "PUNCT" and tok.start > 0 and tok.end < len(s.text) and tok.form not in OPEN_PUNCT_SET)
            or (tok.base_rel == "cc" and tok.start > 0)
            for tok in toks
        )

        for b in splits:
            total_splits += 1
            # 1. Kiểm tra cắt bên trong một UD token (ví dụ từ ghép 'điện thoại' hay số '3.14')
            inside_tok = any(tok.start < b < tok.end for tok in toks)
            if inside_tok:
                intra_token_splits += 1
                tight_dep_violations += 1
                if has_internal_natural_pause:
                    avoidable_total += 1
                    mid_clause_unforced += 1
                continue

            # Xác định token ngay trước và ngay sau ranh giới b
            left_idx = -1
            for idx, tok in enumerate(toks):
                if tok.end <= b:
                    left_idx = idx
                else:
                    break
            right_idx = left_idx + 1
            if left_idx < 0 or right_idx >= len(toks):
                continue

            tl = toks[left_idx]
            tr = toks[right_idx]

            # 2. Đếm cung phụ thuộc (edges) bắc qua ranh giới b (loại bỏ root và punct)
            crossed = 0
            crossed_tight = False
            crossed_clause = False
            for tok in toks:
                if tok.head == 0 or tok.base_rel == "punct":
                    continue
                h_idx = id_to_idx.get(tok.head, -1)
                if h_idx < 0:
                    continue
                u = id_to_idx[tok.tid]
                lo, hi = min(u, h_idx), max(u, h_idx)
                if lo <= left_idx and hi >= right_idx:
                    crossed += 1
                    if tok.base_rel in TIGHT_RELS:
                        crossed_tight = True
                    if tok.base_rel in CLAUSE_RELS:
                        crossed_clause = True

            crossed_arcs_sum += crossed

            # Vi phạm quan hệ chặt trực tiếp giữa 2 token kề (left, right) hoặc cung tight bắc qua b
            direct_tight = (
                (tl.head == tr.tid and tl.base_rel in TIGHT_RELS)
                or (tr.head == tl.tid and tr.base_rel in TIGHT_RELS)
                or crossed_tight
            )
            if direct_tight:
                tight_dep_violations += 1

            # Cắt trùng ranh giới dấu câu ngắt ngữ điệu hoặc ranh giới mệnh đề
            is_punct_hit = (
                (tl.upos == "PUNCT" and tl.form not in OPEN_PUNCT_SET)
                or (tr.upos == "PUNCT" and tr.form in OPEN_PUNCT_SET)
            )
            is_clause_hit = (
                crossed_clause
                or tr.base_rel in ("conj", "cc", "advcl", "parataxis", "ccomp", "acl")
                or (tl.head == tr.tid and tl.base_rel in CLAUSE_RELS)
                or (tr.head == tl.tid and tl.base_rel in CLAUSE_RELS)
            )
            if is_punct_hit or is_clause_hit:
                clause_punct_hits += 1
            if has_internal_natural_pause:
                avoidable_total += 1
                if not (is_punct_hit or is_clause_hit):
                    mid_clause_unforced += 1

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    ms_per_kchar = elapsed_ms / (total_chars / 1000.0) if total_chars else 0.0

    return {
        "multi_chunk_sents": total_multi_sents,
        "total_chunks": total_chunks,
        "total_splits": total_splits,
        "compliance_pct": round(100.0 * compliant_chunks / max(1, total_chunks), 2),
        "lossless_pct": round(100.0 * lossless_ok / max(1, total_multi_sents), 2),
        "orphan_pct": round(100.0 * orphan_chunks / max(1, total_chunks), 2),
        "mean_cv": round(statistics.mean(cvs), 3) if cvs else 0.0,
        "intra_word_split_pct": round(100.0 * intra_token_splits / max(1, total_splits), 2),
        "tight_dep_violation_pct": round(100.0 * tight_dep_violations / max(1, total_splits), 2),
        "clause_punct_hit_pct": round(100.0 * clause_punct_hits / max(1, total_splits), 2),
        "unforced_mid_clause_pct": round(100.0 * mid_clause_unforced / max(1, avoidable_total), 2),
        "mean_crossed_arcs": round(crossed_arcs_sum / max(1, total_splits), 2),
        "ms_per_1k_chars": round(ms_per_kchar, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark C: Bảo toàn Thực thể & Cụm Bảo vệ trên Web/TTS Stress Suite
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_STRESS_CASES = [
    ("URL & Decimal", "Bạn có thể xem toàn bộ tài liệu kỹ thuật chi tiết tại https://nlp-lab.org/v1.0/segmenter.pdf?format=raw để đối chiếu số liệu phiên bản 3.14159 trong thực nghiệm.", ["https://nlp-lab.org/v1.0/segmenter.pdf?format=raw", "3.14159"]),
    ("Email & Date & Time", "Mọi báo cáo nghiệm thu đề tài nghiên cứu xin vui lòng gửi qua địa chỉ thư điện tử khoa học research.team@university.edu.vn trước thời điểm 14:30 ngày 21/11/2026.", ["research.team@university.edu.vn", "14:30", "21/11/2026"]),
    ("Titles & Initials", "Trong hội nghị khoa học lần này, PGS. TS. Nguyễn Văn An cùng với TS. Trần Thị Bình đã thuyết trình về phương pháp học sâu trên cụm máy tính hiệu năng cao.", ["PGS. TS. Nguyễn Văn An", "TS. Trần Thị Bình"]),
    ("English Initials & Figs", "According to the detailed historical analysis presented in Fig. 3 and No. 12 on page 48, Dr. J. K. Rowling published the updated edition at 10:30 a.m. in New York.", ["Fig. 3", "No. 12", "Dr. J. K. Rowling", "10:30", "a.m.", "New York"]),
    ("Large Currency & Version", "Tổng mức đầu tư nâng cấp hạ tầng mạng cho phòng thí nghiệm trí tuệ nhân tạo là 1.250.000.000 đồng nhằm vận hành ổn định phiên bản Node.js v20.18.0 và Python 3.11.", ["1.250.000.000", "Node.js", "v20.18.0", "3.11"]),
    ("Parenthetical & Quoted", "Thuật toán quy hoạch động tìm điểm ngắt tối ưu dựa trên thang chi phí ngữ điệu (bao gồm dấu câu mạnh, dấu câu yếu, liên từ và hệ thống hư từ bảo vệ) cho văn bản dài.", ["(bao gồm dấu câu mạnh, dấu câu yếu, liên từ và hệ thống hư từ bảo vệ)"]),
    ("Chinese Name & Time & Mixed", "国际北极研究中心主任张伟明教授在2026年11月21日下午15:30通过电子邮箱 zhang@arctic.org 发布了最新极地气候监测数据集。", ["2026", "15:30", "zhang@arctic.org"]),
]


def eval_entity_integrity(chunker: Callable[[str], List[str]], max_chars: int = 80) -> Dict[str, float]:
    total_ents = 0
    preserved = 0
    lossless = 0
    compliant = 0
    for _name, text, entities in ENTITY_STRESS_CASES:
        chunks = chunker(text)
        if "".join(c for ch in chunks for c in ch if not c.isspace()) == "".join(c for c in text if not c.isspace()):
            lossless += 1
        if all(eff_len(ch) <= max_chars + 1e-9 for ch in chunks):
            compliant += 1
        for ent in entities:
            total_ents += 1
            if any(ent in ch for ch in chunks):
                preserved += 1
    n = len(ENTITY_STRESS_CASES)
    return {
        "entity_preserved_pct": round(100.0 * preserved / max(1, total_ents), 2),
        "preserved": preserved,
        "total_entities": total_ents,
        "lossless_pct": round(100.0 * lossless / n, 2),
        "compliance_pct": round(100.0 * compliant / n, 2),
    }


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("1/4 Loading Universal Dependencies treebanks (vi_vtb, en_ewt, zh_gsdsimp)...")
    vi_sents = parse_conllu(UD_DIR / "vi_vtb-ud-test.conllu")
    en_sents = parse_conllu(UD_DIR / "en_ewt-ud-test.conllu")
    zh_sents = parse_conllu(UD_DIR / "zh_gsdsimp-ud-test.conllu")
    print(f"    Loaded: vi={len(vi_sents)}, en={len(en_sents)}, zh={len(zh_sents)}")

    print("2/4 Running Benchmark A: Sentence Boundary Detection (SBD)...")
    en_docs, vi_docs, zh_docs = build_ud_sbd_datasets(en_sents, vi_sents, zh_sents)
    from app.services.text_segmenter import SegmenterConfig

    def sbd_no_spans(t: str) -> List[str]:
        return split_sentences(t, cfg=SegmenterConfig(use_spans=False))

    def sbd_zh_regex(t: str) -> List[str]:
        # Kể cả biến thể regex CJK thêm (?<=[。！？]) vì bản legacy gốc cần \s+
        return regex_legacy_sbd(t)

    try:
        import underthesea
        def sbd_underthesea(t: str) -> List[str]:
            return underthesea.sent_tokenize(t)
    except Exception:
        sbd_underthesea = None

    sbd_methods = {
        "Regex (Legacy)": sbd_zh_regex,
        "PTS w/o Spans": sbd_no_spans,
        "PTS (Full)": lambda t: split_sentences(t),
    }

    sbd_results = {
        "UD_English-EWT (854+ pars)": {name: eval_sbd_docs(en_docs, fn, " ") for name, fn in sbd_methods.items()},
        "UD_Vietnamese-VTB (detok)": {
            **{name: eval_sbd_docs(vi_docs, fn, " ") for name, fn in sbd_methods.items()},
            **({"underthesea": eval_sbd_docs(vi_docs, sbd_underthesea, " ")} if sbd_underthesea else {}),
        },
        "UD_Chinese-GSDSimp": {name: eval_sbd_docs(zh_docs, fn, "") for name, fn in sbd_methods.items()},
        "Adversarial_Web_TTS": {
            **{name: eval_sbd_docs(ADVERSARIAL_SBD_PASSAGES, fn, " ") for name, fn in sbd_methods.items()},
            **({"underthesea": eval_sbd_docs(ADVERSARIAL_SBD_PASSAGES, sbd_underthesea, " ")} if sbd_underthesea else {}),
        },
    }

    print("3/5 Running Benchmark B: UD Syntactic & Prosodic Sub-sentence Chunking (L_max = 80 & 120)...")
    chunking_results: Dict[str, Dict[str, Dict[str, float]]] = {}
    for L_max in (120, 80):
        methods = {
            "Regex (Legacy)": lambda t, m=L_max: regex_legacy_split(t, m),
            "Greedy-Word": lambda t, m=L_max: greedy_word_split(t, m),
            "Greedy-Punct": lambda t, m=L_max: greedy_punct_split(t, m),
            "KP-Balanced (alpha=6)": lambda t, m=L_max: pts_balanced_kp_split(t, m),
            "PTS w/o DP": lambda t, m=L_max: pts_no_dp_split(t, m),
            "PTS w/o Spans": lambda t, m=L_max: pts_no_spans_split(t, m),
            "PTS w/o Lexicon": lambda t, m=L_max: pts_no_lexicon_split(t, m),
            "PTS (Prosody-First)": lambda t, m=L_max: pts_full_split(t, m),
        }
        ds_map = {
            "vi_vtb": vi_sents,
            "en_ewt": en_sents,
            "zh_gsdsimp": zh_sents,
            "ALL_3_LANGS": vi_sents + en_sents + zh_sents,
        }
        chunking_results[f"Lmax_{L_max}"] = {}
        for dname, ds in ds_map.items():
            chunking_results[f"Lmax_{L_max}"][dname] = {
                mname: eval_ud_chunking(ds, mfn, L_max) for mname, mfn in methods.items()
            }

    print("4/5 Running Benchmark C: Entity Integrity Stress Suite (L_max = 80)...")
    entity_methods = {
        "Regex (Legacy)": lambda t: regex_legacy_split(t, 80),
        "Greedy-Word": lambda t: greedy_word_split(t, 80),
        "Greedy-Punct": lambda t: greedy_punct_split(t, 80),
        "PTS w/o Spans": lambda t: pts_no_spans_split(t, 80),
        "PTS (Prosody-First)": lambda t: pts_full_split(t, 80),
    }
    entity_results = {mname: eval_entity_integrity(mfn, 80) for mname, mfn in entity_methods.items()}

    print("5/5 Running Benchmark D: Adaptive Multi-Genre & Multi-Engine TTS Quality...")
    STORY_PASSAGES = [
        '"Hả?" "Thật sao?!" Hắn giật mình quay phắt lại nhìn tờ mật thư trên bàn gỗ, tim đập thình thịch không ngừng.',
        '"Đi thôi!" Từ Tiểu Thụ khẽ phất tay áo rồi bước vội qua cánh cổng đá phủ rêu phong, trong khi cơn mưa đêm vẫn trút xuống xối xả không dứt.',
        '"Không thể nào!" "Chờ đã!" Nàng cắn môi nhìn theo bóng lưng đang khuất dần trong màn sương trắng xóa ngoài sơn cốc.',
        'Lão giả khẽ vuốt chòm râu bạc trắng rồi bật cười ha hả giữa đại điện tĩnh mịch; ngay lập tức luồng khí tức cuồn cuộn quanh thân đột ngột thu liễm lại, rất im ắng.',
    ]
    GENERAL_PASSAGES = [
        'Chim chích mộc lan (Setophaga magnolia) là một loài chim thuộc họ Chích rừng sinh sống phổ biến ở Bắc Mỹ; vào mùa đông, quần thể này thường di cư xuống vùng Trung Mỹ và biển Caribe.',
        'Theo báo cáo công bố tại https://nlp-lab.org/v2.0/stats.pdf lúc 14:30 ngày 21/11/2026 bởi PGS. TS. Nguyễn Văn An tại TP. HCM, tỉ lệ giữ nguyên cụm từ chuyên ngành đạt mức ổn định qua nhiều vòng thử nghiệm độc lập.',
        'Việc kết hợp phân đoạn theo ranh giới mệnh đề với mô hình Piper VITS ngoại tuyến giúp hệ thống duy trì khả năng đọc tài liệu khoa học ngay cả khi thiết bị mất kết nối mạng, đặc biệt hữu ích với các bài báo dài.',
        'Chi phí tổng hợp âm thanh phụ thuộc đáng kể vào số lần tách mảnh văn bản, do đó thuật toán cần cực tiểu hóa số vết ngắt thừa đối với các động cơ đọc hỗ trợ ngữ điệu câu dài như Microsoft Edge Neural.',
    ]

    def eval_adaptive(passages: List[str], chunker: Callable[[str], List[str]], is_story: bool) -> Dict[str, float]:
        all_chunks: List[str] = []
        for p in passages:
            all_chunks.extend(chunker(p))
        n_sents = sum(len(split_sentences(p)) for p in passages)
        avg_len = round(statistics.mean(eff_len(c) for c in all_chunks), 1)
        short_turns = sum(1 for c in all_chunks if eff_len(c) <= 24)
        extra_splits = max(0, len(all_chunks) - n_sents)
        return {
            "total_chunks": len(all_chunks),
            "extra_mid_splits": extra_splits,
            "avg_eff_len": avg_len,
            "short_fragment_pct": round(100.0 * short_turns / max(1, len(all_chunks)), 2),
        }

    adaptive_results = {
        "Story_Dialogue": {
            "Fixed General (120)": eval_adaptive(STORY_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("general", "BV074_streaming")), True),
            "Adaptive Story + CapCut (120)": eval_adaptive(STORY_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("story", "BV074_streaming")), True),
            "Adaptive Story + Piper (160)": eval_adaptive(STORY_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("story", "local_ngoc_huyen_new")), True),
            "Adaptive Story + Edge (220)": eval_adaptive(STORY_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("story", "vi-VN-HoaiMyNeural")), True),
        },
        "General_Wiki_News": {
            "Fixed (120)": eval_adaptive(GENERAL_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("general", "BV074_streaming")), False),
            "Adaptive General + Piper (160)": eval_adaptive(GENERAL_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("general", "local_ngoc_huyen_new")), False),
            "Adaptive General + Edge (220)": eval_adaptive(GENERAL_PASSAGES, lambda t: split_into_chunks(t, cfg=resolve_segmenter_config("general", "vi-VN-HoaiMyNeural")), False),
        },
    }

    all_results = {
        "sbd": sbd_results,
        "chunking": chunking_results,
        "entity_integrity": entity_results,
        "adaptive_modes": adaptive_results,
    }
    OUT_JSON.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Sinh báo cáo Markdown tóm tắt kết quả thực nghiệm
    lines: List[str] = [
        "# Kết quả thực nghiệm — Prosody-aware Text Segmenter (PTS)",
        "",
        "Tài liệu này tổng hợp kết quả định lượng trên **3 bộ dữ liệu Universal Dependencies chuẩn quốc tế** "
        "(`UD_Vietnamese-VTB` 800 câu, `UD_English-EWT` 2.077 câu, `UD_Chinese-GSDSimp` 500 câu) cùng bộ kiểm thử áp lực Web/TTS.",
        "",
        "## 1. Benchmark A — Phát hiện ranh giới câu (Sentence Boundary Detection)",
        "",
    ]
    for ds_name, m_dict in sbd_results.items():
        lines.append(f"### {ds_name}")
        lines.append("| Phương pháp | Precision (%) | Recall (%) | F1 (%) | FP | FN |")
        lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
        for mname, r in m_dict.items():
            lines.append(f"| {mname} | {r['precision']:.2f} | {r['recall']:.2f} | **{r['f1']:.2f}** | {r['fp']} | {r['fn']} |")
        lines.append("")

    for key_label, ds_dict in chunking_results.items():
        lines.append(f"## 2. Benchmark B — Phân đoạn câu dài dưới ràng buộc độ dài ({key_label})")
        lines.append("")
        for ds_name in ("ALL_3_LANGS", "vi_vtb", "en_ewt", "zh_gsdsimp"):
            lines.append(f"### Tập {ds_name} ({ds_dict[ds_name]['PTS (Prosody-First)']['multi_chunk_sents']} câu dài)")
            lines.append(
                "| Phương pháp | ≤ L_max (%) | Lossless (%) | Cắt giữa từ (%) ↓ | Vi phạm cú pháp chặt (%) ↓ | Đúng mệnh đề/dấu câu (%) ↑ | Ngắt vô lý giữa vế (%) ↓ | Cung cắt TB ↓ | Lệch độ dài CV | Mẩu vụn (%) ↓ | Tốc độ (ms/1k chars) |"
            )
            lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            for mname, r in ds_dict[ds_name].items():
                lines.append(
                    f"| {mname} | {r['compliance_pct']:.1f} | {r['lossless_pct']:.1f} | "
                    f"{r['intra_word_split_pct']:.2f} | {r['tight_dep_violation_pct']:.2f} | "
                    f"{r['clause_punct_hit_pct']:.2f} | {r['unforced_mid_clause_pct']:.2f} | {r['mean_crossed_arcs']:.2f} | "
                    f"{r['mean_cv']:.3f} | {r['orphan_pct']:.2f} | {r['ms_per_1k_chars']:.2f} |"
                )
            lines.append("")

    lines.extend([
        "## 3. Benchmark C — Bảo toàn thực thể (URL, Email, Số, Chữ viết tắt, Tên riêng) tại L_max = 80",
        "",
        "| Phương pháp | Bảo toàn thực thể (%) ↑ | Bảo toàn / Tổng | Lossless (%) | ≤ L_max (%) |",
        "| :--- | ---: | :---: | ---: | ---: |",
    ])
    for mname, r in entity_results.items():
        lines.append(
            f"| {mname} | **{r['entity_preserved_pct']:.2f}** | {r['preserved']}/{r['total_entities']} | "
            f"{r['lossless_pct']:.1f} | {r['compliance_pct']:.1f} |"
        )
    lines.append("")
    lines.append("## 4. Benchmark D — Thích ứng đa thể loại (Story vs General) & Động cơ TTS (CapCut / Piper / Edge)")
    lines.append("")
    for grp, gdict in adaptive_results.items():
        lines.append(f"### {grp}")
        lines.append("| Chế độ | Tổng chunks | Số lần ngắt bổ sung giữa câu ↓ | Độ dài TB | Mảnh vụn ≤ 24 ký tự (%) ↓ |")
        lines.append("| :--- | ---: | ---: | ---: | ---: |")
        for mname, r in gdict.items():
            lines.append(
                f"| {mname} | {r['total_chunks']} | {r['extra_mid_splits']} | {r['avg_eff_len']:.1f} | {r['short_fragment_pct']:.2f} |"
            )
        lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nDone! Wrote:\n  - {OUT_JSON}\n  - {OUT_MD}")


if __name__ == "__main__":
    main()
