# -*- coding: utf-8 -*-
"""
PTS - Prosody-aware Text Segmenter (Bộ phân đoạn văn bản theo ngữ điệu)
=======================================================================

Bản Python tham chiếu của thuật toán. Bản TypeScript chạy trong trình duyệt
(extension/src/content/nlp/segmenter.ts) được port 1-1 và được kiểm tra
"parity" tự động: hai bản phải cho ra kết quả giống hệt nhau trên cùng dữ liệu
(xem research/segmentation/parity_check.py).

Bài toán
--------
Cho một đoạn văn bản thô (vi / en / zh ...), chia thành các đơn vị đọc (chunk)
thỏa mãn đồng thời:
  (R1) Ràng buộc cứng: độ dài hiệu dụng mỗi chunk <= L_max (giới hạn API TTS).
  (R2) Không cắt ngang các đơn vị không được phép tách: số thập phân, ngày giờ,
       URL, email, chữ viết tắt (TP., PGS., Dr., e.g., U.S.), tên viết tắt (J. K.).
  (R3) Ranh giới chunk trùng ranh giới ngữ điệu tự nhiên nhất có thể:
       dấu câu mạnh > dấu câu yếu > trước liên từ > trước hư từ > ranh giới từ.
  (R4) Không mất / thêm ký tự (lossless): nối các chunk lại phải khôi phục đúng
       văn bản gốc (bỏ qua khoảng trắng) để đồng bộ 1-1 giữa DOM và âm thanh.

Pipeline 4 tầng
---------------
  1. Tokenization có offset theo Unicode category: word / cjk / punct / space.
  2. Nhận diện vùng bảo vệ (protected spans):
       - Cứng (hard, cấm cắt):  URL, email, số (3.14, 1.000.000, 21/11/2026, 10:30),
         viết tắt danh xưng, viết tắt chung, viết tắt đi kèm số (No. 5), tên viết tắt.
       - Mềm (soft, phạt khi cắt): cụm trong ngoặc / ngoặc kép, chuỗi tên riêng
         viết hoa liên tiếp (Hà Nội, Từ Tiểu Thụ, New York).
  3. Sentence Boundary Detection (SBD) dựa trên luật + ngoại lệ:
       ứng viên = cụm dấu kết câu (. ! ? … 。！？) + dấu đóng ngoặc/nháy;
       loại bỏ nếu dấu chấm thuộc vùng bảo vệ cứng, nếu ký tự kế tiếp là chữ
       thường (câu thoại "Đi thôi!" hắn nói.), hoặc không có khoảng trắng phía sau
       (Node.js). Riêng dấu kết câu CJK luôn là ranh giới (tiếng Trung không có
       khoảng trắng sau 。).
  4. Chunking tối ưu toàn cục bằng Quy hoạch động (DP) cho các câu dài hơn L_max:

        J(c_1..c_K) = Σ_k [ α·((L_k − T)/T)² + β·1(L_k < L_min) ] + Σ_b w(b)
        s.t.  L_k <= L_max  ∀k

     - L_k : độ dài hiệu dụng (ký tự Latin = 1, chữ Hán/Kana = cjk_weight vì
             1 chữ Hán ≈ 1 âm tiết ≈ 3-4 ký tự Latin khi đọc thành tiếng).
     - T   : độ dài mục tiêu = target_ratio · L_max.
     - w(b): chi phí ngắt tại ranh giới b, theo thang ngữ điệu:
             ; :  1.0 | — –  1.5 | , 、 2.0 | trước liên từ 3.0 |
             trước hư từ (chink) 5.0 | ranh giới từ thường 8.0
             +6 nếu để hư từ "treo" cuối chunk (của | ..., the | ...)
             +6 nếu tách hậu tố/tiểu từ khỏi từ trước (… | này, … | 了)
             +12..20 nếu cắt trong vùng bảo vệ mềm; ∞ trong vùng bảo vệ cứng.
     Lời giải tối ưu tìm bằng DP O(n·k) (k = số ứng viên trong cửa sổ L_max),
     cùng tinh thần với thuật toán ngắt dòng Knuth-Plass (1981), còn thang chi phí
     hư từ/thực từ lấy cảm hứng từ "Chinks 'n Chunks" (Liberman & Church, 1992)
     trong dự đoán ranh giới ngữ điệu cho TTS.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

INF = float("inf")


# ─────────────────────────────────────────────────────────────────────────────
# Cấu hình
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SegmenterConfig:
    profile: str = "general"          # "general" (báo chí/kiến thức) | "story" (truyện)
    max_chars: int = 120              # L_max: giới hạn cứng độ dài hiệu dụng
    target_ratio: float = 0.72        # T = target_ratio * L_max (chỉ làm tie-breaker nhẹ)
    min_chars: int = 16               # L_min: dưới ngưỡng này là mẩu vụn
    alpha: float = 0.4                # trọng số cân bằng NHẸ (không bao giờ ép cắt 65+60 vô lý)
    split_penalty: float = 6.0        # λ: phạt cố định mỗi chunk để giảm thiểu số vết cắt giả
    orphan_penalty: float = 3.0       # β: đủ đẩy lùi sang dấu câu/liên từ trước đó (< W_WORD)
    cjk_weight: float = 3.0           # trọng số độ dài 1 chữ Hán/Kana
    merge_short_turns: bool = False   # bật trong 'story' để không xé vụn câu thoại 2-3 từ
    use_dp: bool = True               # False = tham lam cục bộ (ablation)
    use_spans: bool = True            # False = tắt vùng bảo vệ (ablation)
    use_lexicon: bool = True          # False = tắt từ điển liên từ/hư từ (ablation)


DEFAULT_CONFIG = SegmenterConfig()


def detect_tts_engine(voice_id: Optional[str] = None) -> str:
    """Suy ra loại TTS engine ('local' | 'edge' | 'capcut') từ mã giọng đọc."""
    if not voice_id:
        return "capcut"
    v = voice_id.strip()
    if v == "local_ngoc_huyen_new" or v.startswith("local_"):
        return "local"
    if "Neural" in v or v.startswith("vi-VN-") or v.lower() in ("hoaimy", "namminh"):
        return "edge"
    return "capcut"


def resolve_segmenter_config(
    profile: str = "general",
    voice_id: Optional[str] = None,
    max_chars: Optional[int] = None,
    engine: Optional[str] = None,
) -> SegmenterConfig:
    """
    Xây dựng cấu hình phân đoạn thích ứng đa thể loại & đa động cơ TTS:
    - Engine 'capcut': L_max = 120 (giới hạn API & nhịp đọc ngắn gọn)
    - Engine 'local' (Piper VITS ONNX): L_max = 160 (giữ trọn câu vừa trên CPU)
    - Engine 'edge' (Microsoft Neural): L_max = 220 (đọc liền câu dài không chắp vá MP3)
    - Thể loại 'story': bật merge thoại/cảm thán siêu ngắn, giữ trọn trích dẫn thoại, nhịp kể dài
    - Thể loại 'general': tách ranh giới câu rành mạch, bảo vệ tối đa ngoặc thuật ngữ/số liệu
    """
    eng = engine or detect_tts_engine(voice_id)
    if max_chars is not None:
        resolved_max = max_chars
    elif eng == "edge":
        resolved_max = 220
    elif eng == "local":
        resolved_max = 160
    else:
        resolved_max = 120

    prof = (profile or "general").lower().strip()
    if prof == "story":
        return SegmenterConfig(
            profile="story",
            max_chars=resolved_max,
            target_ratio=0.80,
            split_penalty=7.0,
            merge_short_turns=True,
        )
    return SegmenterConfig(
        profile="general",
        max_chars=resolved_max,
        target_ratio=0.72,
        split_penalty=6.0,
        merge_short_turns=False,
    )


# Chi phí ngắt ngữ điệu (Prosody-First Hierarchy:
# W_COMMA + orphan + tiebreak ~ 5.0 << W_FUNC (8.0) << W_WORD (14.0)
# -> Tuyệt đối KHÔNG bỏ dấu câu thật để cắt bậy giữa cụm từ theo kiểu 65+60!)
W_STRONG = 0.5       # ; :
W_DASH = 1.0         # — –
W_COMMA = 1.5        # , ，、
W_TERMINAL = 2.0     # dấu kết câu bị SBD giữ lại trong thoại ("Đi!" hắn nói)
W_CLOSER = 2.5       # sau dấu đóng ngoặc / nháy
W_OPENER = 2.5       # trước dấu mở ngoặc / nháy
W_CONJ = 3.5         # trước liên từ (và, nhưng, tuy nhiên, rồi, suddenly, 但是...)
W_OTHER_PUNCT = 6.0
W_FUNC = 8.0         # trước hư từ / giới từ bám phải (chink)
W_WORD = 14.0        # cắt giữa hai thực từ trong một cụm chưa hết ý
P_STRAND = 6.0       # phạt treo hư từ / liên từ ở cuối chunk
P_POSTPOSED = 6.0    # phạt tách tiểu từ hậu trí khỏi từ đứng trước
P_SOFT_BRACKET = 22.0
P_SOFT_QUOTE = 14.0
P_SOFT_NAME = 16.0
P_RELAXED = 60.0     # chế độ nới lỏng khi không còn nghiệm khả thi

# ─────────────────────────────────────────────────────────────────────────────
# Tập ký tự & từ điển ngôn ngữ
# ─────────────────────────────────────────────────────────────────────────────

SPACE_CHARS = set(" \t\n\r\x0b\x0c\u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff") | {
    chr(c) for c in range(0x2000, 0x200B)
}
TERMINALS = set(".!?…‼⁇⁈⁉")
CJK_TERMINALS = set("。！？")
CLOSERS = set("\"'”’»)]}）」』】》〉")
OPENERS = set("“«([{（「『【《〈")
STRONG_MEDIAL = set(";；:：")
DASHES = set("—–")
COMMAS = set(",，、")
JOINERS = set("'’-‐")
URL_TRAIL = set(".,;:!?)]}\"'”’»」』")

BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}", "（": "）", "【": "】", "《": "》", "〈": "〉"}
QUOTE_PAIRS = {"“": "”", "«": "»", "「": "」", "『": "』"}
ALL_PAIRS = {**BRACKET_PAIRS, **QUOTE_PAIRS}
PAIR_CLOSERS = set(ALL_PAIRS.values())

_WS_CLASS = "\t\n\x0b\x0c\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
URL_RE = re.compile(r"(?:https?://|www\.)[^" + _WS_CLASS + r"]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
NUMBER_RE = re.compile(r"[0-9]+(?:[.,:/][0-9]+)+")
ACRONYM_RE = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}")

# Viết tắt danh xưng / địa danh: không bao giờ kết câu
TITLE_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "st", "mt", "gen", "col", "capt", "lt", "sgt", "rev",
    "gov", "sen", "rep", "pres", "hon", "vs", "mme", "mlle", "messrs",
    "tp", "tx", "ts", "ths", "pgs", "gs", "bs", "ks", "ls", "q", "p",
}
# Viết tắt chung: có thể kết câu nếu từ kế tiếp viết hoa
GENERAL_ABBREV = {
    "etc", "inc", "ltd", "co", "corp", "jr", "sr", "approx", "dept", "est", "cf", "al", "ca",
    "jan", "feb", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "vv",
}
# Viết tắt chỉ có nghĩa khi đi kèm số (No. 5, Fig. 3, tr. 12)
NUM_ABBREV = {"no", "nos", "vol", "vols", "fig", "figs", "pp", "art", "sec", "ch", "chap", "tr", "eq", "ref"}
ACRONYM_CAN_END = {"v.v.", "a.m.", "p.m."}

CONJ = {
    # vi
    "và", "nhưng", "mà", "hoặc", "hay", "nên", "vì", "nếu", "khi", "để", "rồi", "song",
    "còn", "thì", "tuy", "dù", "nhờ", "bởi", "liền", "bỗng", "chợt",
    # en
    "and", "but", "or", "nor", "so", "yet", "because", "although", "though", "while", "whereas",
    "if", "unless", "since", "when", "where", "which", "who", "whom", "whose", "that", "after",
    "before", "until", "however", "therefore", "moreover", "meanwhile", "consequently", "whether",
    "then", "suddenly",
}
CONJ2 = {
    "trong khi", "bởi vì", "vì vậy", "vì thế", "do đó", "tuy nhiên", "mặc dù", "thậm chí",
    "ngoài ra", "sau đó", "trước khi", "sau khi", "cho nên", "hơn nữa", "đồng thời", "cho đến",
    "mặt khác", "cụ thể là", "theo đó", "ngược lại", "tức thì", "ngay lập tức", "thế là", "lúc này",
    "as well", "so that", "even though", "even if", "in order", "such as", "rather than",
}
HEAD_FUNC = {
    # vi: giới từ, lượng từ, loại từ, hệ từ, phó từ tiền động từ
    "của", "cho", "với", "trong", "ngoài", "trên", "dưới", "ở", "tại", "từ", "đến", "tới", "về",
    "bằng", "theo", "như", "là", "được", "bị", "những", "các", "một", "mọi", "mỗi", "từng",
    "vào", "giữa", "qua", "đối", "thuộc", "cái", "chiếc", "đã", "đang", "sẽ", "vừa", "mới",
    "không", "chưa", "chẳng", "rất", "cũng", "vẫn", "đều", "hãy", "đừng",
    # en: preposition, article, determiner, auxiliary
    "of", "in", "on", "at", "to", "for", "with", "from", "by", "about", "into", "onto", "over",
    "under", "between", "among", "through", "during", "without", "within", "across", "against",
    "the", "a", "an", "these", "those", "its", "his", "her", "their", "our", "my", "your",
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "will", "would",
    "can", "could", "should", "may", "might", "must", "not", "very",
}
# Tiểu từ / chỉ định từ đứng SAU từ chính: không được tách khỏi từ trước
POSTPOSED = {"này", "đó", "kia", "ấy", "nọ", "nhé", "nhỉ", "à", "ạ", "ư", "chứ", "đấy", "thôi", "lắm", "nữa"}
CJK_CONJ = ["但是", "可是", "因为", "所以", "如果", "虽然", "然而", "而且", "并且", "然后", "于是",
            "不过", "因此", "以及", "或者", "但", "而", "并", "或", "和", "与", "及"]
CJK_POST = set("了着过的之吗呢吧啊呀们地得么")   # trợ từ hậu trí: bám trái, phạt tách trước chúng
CJK_PREP = set("在把被对从向给于以")           # giới từ / đồng động từ: bám phải (chink), ưu tiên tách trước & phạt treo cuối


# ─────────────────────────────────────────────────────────────────────────────
# Phân loại ký tự (dùng Unicode category để đồng nhất với bản TypeScript)
# ─────────────────────────────────────────────────────────────────────────────

def is_space(ch: str) -> bool:
    return ch in SPACE_CHARS


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF
            or 0x3040 <= cp <= 0x30FF or 0x20000 <= cp <= 0x2A6DF)


def is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return (cat[0] in "LM" or cat == "Nd") and not is_cjk(ch)


def is_upper(ch: str) -> bool:
    return unicodedata.category(ch) == "Lu"


def is_lower(ch: str) -> bool:
    return unicodedata.category(ch) == "Ll"


def is_digit(ch: str) -> bool:
    return unicodedata.category(ch) == "Nd"


# ─────────────────────────────────────────────────────────────────────────────
# Tầng 1: Tokenization
# ─────────────────────────────────────────────────────────────────────────────

class Token:
    __slots__ = ("start", "end", "kind")

    def __init__(self, start: int, end: int, kind: str):
        self.start = start
        self.end = end
        self.kind = kind  # 'space' | 'word' | 'cjk' | 'punct'

    def __repr__(self) -> str:
        return f"Token({self.start},{self.end},{self.kind})"


def tokenize(text: str) -> List[Token]:
    toks: List[Token] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if is_space(ch):
            j = i + 1
            while j < n and is_space(text[j]):
                j += 1
            toks.append(Token(i, j, "space"))
        elif is_cjk(ch):
            j = i + 1
            toks.append(Token(i, j, "cjk"))
        elif is_word_char(ch):
            j = i + 1
            while j < n:
                c = text[j]
                if is_word_char(c):
                    j += 1
                elif c in JOINERS and j + 1 < n and is_word_char(text[j + 1]):
                    j += 2
                else:
                    break
            toks.append(Token(i, j, "word"))
        else:
            j = i + 1
            toks.append(Token(i, j, "punct"))
        i = j
    return toks


# ─────────────────────────────────────────────────────────────────────────────
# Bộ phân đoạn
# ─────────────────────────────────────────────────────────────────────────────

class _Analysis:
    """Kết quả phân tích dùng chung cho SBD và chunking trên một văn bản."""

    def __init__(self, text: str, cfg: SegmenterConfig):
        self.text = text
        self.cfg = cfg
        self.n = len(text)
        self.toks = tokenize(text)
        n = self.n

        # Prefix sum độ dài hiệu dụng
        self.P = [0.0] * (n + 1)
        acc = 0.0
        for i, ch in enumerate(text):
            acc += cfg.cjk_weight if is_cjk(ch) else 1.0
            self.P[i + 1] = acc

        # Ánh xạ ký tự -> token
        self.tok_at = [0] * n
        for idx, t in enumerate(self.toks):
            for c in range(t.start, t.end):
                self.tok_at[c] = idx

        self.hard: List[Tuple[int, int, str]] = []
        self.soft: List[Tuple[int, int, float]] = []
        self.hard_gap = [False] * (n + 1)
        self.soft_gap = [0.0] * (n + 1)
        self.hard_at = [-1] * n
        if cfg.use_spans:
            self._find_spans()

    # ---- tiện ích -------------------------------------------------------
    def eff(self, s: int, e: int) -> float:
        return self.P[e] - self.P[s]

    def next_nonspace(self, i: int) -> Optional[int]:
        while i < self.n:
            if not is_space(self.text[i]):
                return i
            i += 1
        return None

    def is_opener_at(self, i: int) -> bool:
        t = self.text
        ch = t[i]
        if ch in OPENERS:
            return True
        if ch == '"' or ch == "'":
            nxt_ok = i + 1 < self.n and not is_space(t[i + 1])
            prev_ok = i == 0 or is_space(t[i - 1]) or t[i - 1] in OPENERS
            return nxt_ok and prev_ok
        return False

    def word_lower(self, tok: Token) -> str:
        return self.text[tok.start:tok.end].lower()

    # ---- Tầng 2: vùng bảo vệ --------------------------------------------
    def _find_spans(self) -> None:
        text, n, cfg = self.text, self.n, self.cfg
        hard = self.hard
        soft = self.soft

        for m in URL_RE.finditer(text):
            s, e = m.start(), m.end()
            while e > s and text[e - 1] in URL_TRAIL:
                e -= 1
            if e > s:
                hard.append((s, e, "url"))
        for m in EMAIL_RE.finditer(text):
            hard.append((m.start(), m.end(), "email"))
        for m in NUMBER_RE.finditer(text):
            hard.append((m.start(), m.end(), "number"))
        for m in ACRONYM_RE.finditer(text):
            kind = "acronym_end" if m.group(0).lower() in ACRONYM_CAN_END else "acronym"
            hard.append((m.start(), m.end(), kind))

        for t in self.toks:
            if t.kind != "word" or t.end >= n or text[t.end] != ".":
                continue
            w = text[t.start:t.end].lower()
            nxt = self.next_nonspace(t.end + 1)
            if w in TITLE_ABBREV:
                hard.append((t.start, t.end + 1, "title"))
            elif w in GENERAL_ABBREV:
                hard.append((t.start, t.end + 1, "abbrev"))
            elif w in NUM_ABBREV and nxt is not None and is_digit(text[nxt]):
                hard.append((t.start, t.end + 1, "numabbrev"))
            elif t.end - t.start == 1 and is_upper(text[t.start]) and nxt is not None and is_upper(text[nxt]):
                hard.append((t.start, t.end + 1, "initial"))
            elif 1 <= t.end - t.start <= 3 and w.isdigit() and nxt is not None and "\n" not in text[t.end + 1:nxt]:
                # Chỉ số đầu dòng danh sách (1. , 2. , 12. ): không tách thành chunk rỗng chỉ có số
                line_start = t.start == 0
                if not line_start:
                    k = t.start - 1
                    while k >= 0 and is_space(text[k]) and text[k] != "\n":
                        k -= 1
                    line_start = k >= 0 and text[k] == "\n"
                if line_start:
                    hard.append((t.start, t.end + 1, "listnum"))

        # Ngoặc / ngoặc kép (vùng mềm)
        stack: List[Tuple[str, int]] = []
        for i, ch in enumerate(text):
            if ch in ALL_PAIRS:
                stack.append((ch, i))
            elif ch in PAIR_CLOSERS:
                k = len(stack) - 1
                while k >= 0 and ALL_PAIRS.get(stack[k][0]) != ch:
                    k -= 1
                if k >= 0:
                    op, s = stack[k]
                    del stack[k:]
                    if self.eff(s, i + 1) <= cfg.max_chars:
                        if op in BRACKET_PAIRS:
                            pen = 28.0 if cfg.profile == "general" else 18.0
                        else:
                            pen = 20.0 if cfg.profile == "story" else 12.0
                        soft.append((s, i + 1, pen))
            elif ch == '"':
                if stack and stack[-1][0] == '"' and not self.is_opener_at(i):
                    s = stack.pop()[1]
                    if self.eff(s, i + 1) <= cfg.max_chars:
                        qpen = 20.0 if cfg.profile == "story" else 12.0
                        soft.append((s, i + 1, qpen))
                elif self.is_opener_at(i):
                    stack.append(('"', i))

        # Chuỗi tên riêng viết hoa liên tiếp (vùng mềm)
        toks = self.toks
        run: List[int] = []

        def flush() -> None:
            if len(run) >= 2:
                soft.append((toks[run[0]].start, toks[run[-1]].end, P_SOFT_NAME))

        for idx, t in enumerate(toks):
            if t.kind == "word" and is_upper(text[t.start]):
                prev = toks[idx - 1] if idx >= 1 else None
                if (run and prev is not None and prev.kind == "space" and prev.end - prev.start == 1
                        and text[prev.start] == " " and run[-1] == idx - 2):
                    run.append(idx)
                else:
                    flush()
                    run = [idx]
            elif t.kind == "space":
                continue
            else:
                flush()
                run = []
        flush()

        for si, (s, e, _k) in enumerate(hard):
            for g in range(s + 1, e):
                self.hard_gap[g] = True
            for p in range(s, e):
                if self.hard_at[p] == -1:
                    self.hard_at[p] = si
        for (s, e, pen) in soft:
            for g in range(s + 1, e):
                if pen > self.soft_gap[g]:
                    self.soft_gap[g] = pen

    # ---- Tầng 3: SBD -----------------------------------------------------
    def sentence_spans(self) -> List[Tuple[int, int]]:
        text, toks, cfg = self.text, self.toks, self.cfg
        T = len(toks)
        bounds: List[int] = []
        i = 0
        while i < T:
            t = toks[i]
            if t.kind == "space":
                if "\n" in text[t.start:t.end]:
                    bounds.append(t.start)
                i += 1
                continue
            ch = text[t.start]
            if t.kind != "punct" or not (ch in TERMINALS or ch in CJK_TERMINALS):
                i += 1
                continue

            j = i
            has_cjk = False
            has_closer = False
            has_dot = False
            dots: List[int] = []
            while j < T and toks[j].kind == "punct" and (text[toks[j].start] in TERMINALS
                                                          or text[toks[j].start] in CJK_TERMINALS):
                c = text[toks[j].start]
                if c in CJK_TERMINALS:
                    has_cjk = True
                if c == ".":
                    has_dot = True
                    dots.append(toks[j].start)
                j += 1
            while j < T and toks[j].kind == "punct" and text[toks[j].start] in CLOSERS:
                has_closer = True
                j += 1
            k = toks[j - 1].end
            nxt = self.next_nonspace(k)

            ok = True
            if cfg.use_spans:
                for p in dots:
                    si = self.hard_at[p]
                    if si >= 0:
                        kind = self.hard[si][2]
                        if kind in ("abbrev", "acronym_end") and nxt is not None and is_upper(text[nxt]):
                            continue
                        ok = False
                        break
            if ok and nxt is not None and not has_cjk:
                nc = text[nxt]
                if nxt == k and not is_cjk(nc) and nc not in OPENERS:
                    ok = False
                elif is_lower(nc) and (has_dot or has_closer):
                    ok = False
                elif nc in COMMAS or nc in STRONG_MEDIAL:
                    ok = False
            if ok and nxt is not None:
                bounds.append(k)
            i = j

        raw: List[Tuple[int, int]] = []
        prev = 0
        for b in bounds + [self.n]:
            s = prev
            while s < b and is_space(text[s]):
                s += 1
            e = b
            while e > s and is_space(text[e - 1]):
                e -= 1
            if e > s:
                raw.append((s, e))
            prev = b

        # Gộp mẩu chỉ toàn dấu câu vào câu liền trước (hoặc liền sau)
        out: List[Tuple[int, int]] = []
        pending: Optional[int] = None
        for (s, e) in raw:
            if pending is not None:
                s = pending
                pending = None
            if not self._has_content(s, e):
                if out:
                    out[-1] = (out[-1][0], e)
                else:
                    pending = s
                continue
            out.append((s, e))
        if pending is not None and raw:
            out.append((pending, raw[-1][1]))

        # Chế độ Truyện ('story'): gom các câu thoại/cảm thán siêu ngắn liền kề trên cùng dòng
        # để tránh giọng đọc bị rời rạc khi thoại dồn dập ("Hả?" "Sao thế?")
        if cfg.merge_short_turns and len(out) > 1:
            merged: List[Tuple[int, int]] = [out[0]]
            merge_cap = min(72.0, cfg.max_chars * 0.68)
            for (s, e) in out[1:]:
                ps, pe = merged[-1]
                if ("\n" not in text[pe:s]
                        and self.eff(ps, pe) <= 32.0
                        and self.eff(s, e) <= 32.0
                        and self.eff(ps, e) <= merge_cap):
                    merged[-1] = (ps, e)
                else:
                    merged.append((s, e))
            return merged
        return out

    def _has_content(self, s: int, e: int) -> bool:
        for c in range(s, e):
            ch = self.text[c]
            if is_word_char(ch) or is_cjk(ch):
                return True
        return False

    # ---- Tầng 4: chunking bằng DP -----------------------------------------
    def _seg_cost(self, L: float) -> float:
        cfg = self.cfg
        if L > cfg.max_chars:
            return INF
        T = cfg.max_chars * cfg.target_ratio
        dev = (L - T) / T
        cost = cfg.split_penalty + cfg.alpha * dev * dev
        if L < min(cfg.min_chars, cfg.max_chars * 0.3):
            cost += cfg.orphan_penalty
        return cost

    def _break_cost(self, ns: List[int], m: int, relaxed: bool) -> float:
        text, toks, cfg = self.text, self.toks, self.cfg
        ti = ns[m]
        t = toks[ti]
        p = toks[ns[m - 1]]
        g = t.start
        extra = 0.0

        if cfg.use_spans and self.hard_gap[g]:
            if not relaxed:
                return INF
            extra += P_RELAXED
        if t.kind == "punct" and not self.is_opener_at(t.start):
            if not relaxed:
                return INF
            extra += P_RELAXED
        if p.kind == "punct" and self.is_opener_at(p.start):
            if not relaxed:
                return INF
            extra += P_RELAXED
        if cfg.use_spans and p.kind == "punct" and text[p.start] == ".":
            si = self.hard_at[p.start]
            if si >= 0 and self.hard[si][2] in ("title", "numabbrev", "initial", "listnum"):
                if not relaxed:
                    return INF
                extra += P_RELAXED

        if p.kind == "punct":
            c = text[p.start]
            if c in STRONG_MEDIAL:
                cost = W_STRONG
            elif c in DASHES or c == "-":
                cost = W_DASH
            elif c in COMMAS:
                cost = W_COMMA
            elif c in TERMINALS or c in CJK_TERMINALS:
                cost = W_TERMINAL
            elif c in CLOSERS:
                cost = W_CLOSER
            else:
                cost = W_OTHER_PUNCT
        elif t.kind == "punct":
            cost = W_OPENER
        else:
            cost = W_WORD
            if cfg.use_lexicon:
                if t.kind == "word":
                    w = self.word_lower(t)
                    w2 = ""
                    if ti + 2 < len(toks) and toks[ti + 1].kind == "space" and toks[ti + 2].kind == "word":
                        w2 = w + " " + self.word_lower(toks[ti + 2])
                    if (w2 and w2 in CONJ2) or w in CONJ:
                        cost = W_CONJ
                    elif w in HEAD_FUNC:
                        cost = W_FUNC
                    if w in POSTPOSED:
                        cost += P_POSTPOSED
                elif t.kind == "cjk":
                    matched_conj = False
                    for cj in CJK_CONJ:
                        if text.startswith(cj, t.start):
                            cost = W_CONJ
                            matched_conj = True
                            break
                    if not matched_conj and text[t.start] in CJK_PREP:
                        cost = W_FUNC
                    if text[t.start] in CJK_POST:
                        cost += P_POSTPOSED
                if p.kind == "word":
                    pw = self.word_lower(p)
                    if pw in HEAD_FUNC or pw in CONJ:
                        cost += P_STRAND
                if p.kind == "cjk" and text[p.start] in CJK_PREP:
                    cost += P_STRAND

        if cfg.use_spans:
            cost += self.soft_gap[g]
        return cost + extra

    def _optimise(self, ns: List[int], relaxed: bool) -> Optional[List[int]]:
        """Trả về danh sách chỉ số ứng viên bắt đầu chunk (luôn gồm 0), hoặc None nếu vô nghiệm."""
        toks, cfg = self.toks, self.cfg
        M = len(ns)
        brk = [0.0] * M
        for m in range(1, M):
            brk[m] = self._break_cost(ns, m, relaxed)

        if not cfg.use_dp:
            starts = [0]
            i = 0
            while True:
                start = toks[ns[i]].start
                if self.eff(start, toks[ns[M - 1]].end) <= cfg.max_chars:
                    return starts
                best_j, best_c = -1, INF
                for j in range(i + 1, M):
                    L = self.eff(start, toks[ns[j - 1]].end)
                    if L > cfg.max_chars:
                        break
                    if brk[j] == INF:
                        continue
                    c = self._seg_cost(L) + brk[j]
                    if c < best_c:
                        best_c, best_j = c, j
                if best_j < 0:
                    return None
                starts.append(best_j)
                i = best_j

        dp = [INF] * (M + 1)
        back = [-1] * (M + 1)
        dp[0] = 0.0
        for j in range(1, M + 1):
            bj = brk[j] if j < M else 0.0
            if bj == INF:
                continue
            end = toks[ns[j - 1]].end
            i = j - 1
            while i >= 0:
                L = self.eff(toks[ns[i]].start, end)
                if L > cfg.max_chars:
                    break
                if dp[i] < INF:
                    c = dp[i] + self._seg_cost(L) + bj
                    if c < dp[j]:
                        dp[j] = c
                        back[j] = i
                i -= 1
        if dp[M] == INF:
            return None
        starts: List[int] = []
        j = M
        while j > 0:
            i = back[j]
            starts.append(i)
            j = i
        starts.reverse()
        return starts

    def _hard_wrap(self, s: int, e: int) -> List[Tuple[int, int]]:
        """Phương án cuối cùng: cắt theo ký tự khi một token đơn lẻ dài hơn L_max."""
        text, maxc = self.text, self.cfg.max_chars
        out: List[Tuple[int, int]] = []
        cs = s
        while cs < e:
            while cs < e and is_space(text[cs]):
                cs += 1
            if cs >= e:
                break
            ce = cs
            while ce < e and self.eff(cs, ce + 1) <= maxc:
                ce += 1
            if ce == cs:
                ce = cs + 1
            if ce < e:
                k = ce
                while k > cs and not is_space(text[k]):
                    k -= 1
                if k > cs:
                    ce = k
            end = ce
            while end > cs and is_space(text[end - 1]):
                end -= 1
            out.append((cs, end))
            cs = ce
        return out

    def chunk_sentence(self, s: int, e: int) -> List[Tuple[int, int]]:
        if self.eff(s, e) <= self.cfg.max_chars:
            return [(s, e)]
        a, b = self.tok_at[s], self.tok_at[e - 1]
        ns = [idx for idx in range(a, b + 1) if self.toks[idx].kind != "space"]
        starts = self._optimise(ns, relaxed=False)
        if starts is None:
            starts = self._optimise(ns, relaxed=True)
        if starts is None:
            return self._hard_wrap(s, e)
        spans: List[Tuple[int, int]] = []
        for k, si in enumerate(starts):
            ej = starts[k + 1] if k + 1 < len(starts) else len(ns)
            spans.append((self.toks[ns[si]].start, self.toks[ns[ej - 1]].end))
        return spans

    def segment(self) -> List[Tuple[int, int]]:
        out: List[Tuple[int, int]] = []
        for (s, e) in self.sentence_spans():
            out.extend(self.chunk_sentence(s, e))
        return out


# ─────────────────────────────────────────────────────────────────────────────
# API công khai
# ─────────────────────────────────────────────────────────────────────────────

def _resolve(max_chars: Optional[int], cfg: Optional[SegmenterConfig]) -> SegmenterConfig:
    cfg = cfg or DEFAULT_CONFIG
    if max_chars is not None and max_chars != cfg.max_chars:
        cfg = replace(cfg, max_chars=max_chars)
    return cfg


def sentence_spans(text: str, cfg: Optional[SegmenterConfig] = None) -> List[Tuple[int, int]]:
    if not text or not text.strip():
        return []
    return _Analysis(text, _resolve(None, cfg)).sentence_spans()


def split_sentences(text: str, cfg: Optional[SegmenterConfig] = None) -> List[str]:
    return [text[s:e] for s, e in sentence_spans(text, cfg)]


def segment_spans(text: str, max_chars: Optional[int] = None,
                  cfg: Optional[SegmenterConfig] = None) -> List[Tuple[int, int]]:
    if not text or not text.strip():
        return []
    return _Analysis(text, _resolve(max_chars, cfg)).segment()


def split_into_chunks(text: str, max_chars: Optional[int] = None,
                      cfg: Optional[SegmenterConfig] = None) -> List[str]:
    """Chia văn bản thành các chunk đọc tối ưu (lossless, <= max_chars hiệu dụng)."""
    return [text[s:e] for s, e in segment_spans(text, max_chars, cfg)]
