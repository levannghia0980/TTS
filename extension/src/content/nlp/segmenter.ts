/**
 * PTS - Prosody-aware Text Segmenter (Bộ phân đoạn văn bản theo ngữ điệu)
 * =======================================================================
 * Bản TypeScript chạy trong trình duyệt, port 1-1 từ bản Python tham chiếu
 * `backend/app/services/text_segmenter.py`. Hai bản được kiểm tra parity tự động
 * (research/segmentation/parity_check.py) để bảo đảm DOM (span câu) và Backend
 * (cắt câu dịch tiếng Việt trước khi gọi TTS) dùng CÙNG một thuật toán.
 *
 * Pipeline 4 tầng:
 *  1. Tokenization có offset theo Unicode category (word / cjk / punct / space).
 *  2. Vùng bảo vệ: cứng (URL, email, số, viết tắt, tên viết tắt) và mềm (ngoặc,
 *     ngoặc kép, chuỗi tên riêng viết hoa).
 *  3. Sentence Boundary Detection dựa luật + ngoại lệ.
 *  4. Chunking tối ưu toàn cục bằng Quy hoạch động trên hàm chi phí
 *       J = Σ_k [ α·((L_k − T)/T)² + β·1(L_k < L_min) ] + Σ_b w(b),  L_k <= L_max
 *     với w(b) theo thang ngữ điệu (dấu câu mạnh < yếu < liên từ < hư từ < từ thường).
 *
 * Mọi offset tính theo CODE POINT (Array.from) để khớp tuyệt đối với Python.
 */

export type SegmenterProfile = 'general' | 'story';
export type TtsEngineKind = 'capcut' | 'edge' | 'local';

export interface SegmenterConfig {
  profile: SegmenterProfile;
  maxChars: number;
  targetRatio: number;
  minChars: number;
  alpha: number;
  splitPenalty: number;
  orphanPenalty: number;
  cjkWeight: number;
  mergeShortTurns: boolean;
  useDp: boolean;
  useSpans: boolean;
  useLexicon: boolean;
}

export const DEFAULT_CONFIG: SegmenterConfig = {
  profile: 'general',
  maxChars: 120,
  targetRatio: 0.72,
  minChars: 16,
  alpha: 0.4,
  splitPenalty: 6.0,
  orphanPenalty: 3.0,
  cjkWeight: 3.0,
  mergeShortTurns: false,
  useDp: true,
  useSpans: true,
  useLexicon: true,
};

export function detectTtsEngine(voiceId?: string): TtsEngineKind {
  if (!voiceId) return 'capcut';
  const v = voiceId.trim();
  if (v === 'local_ngoc_huyen_new' || v.startsWith('local_')) return 'local';
  if (v.includes('Neural') || v.startsWith('vi-VN-') || v.toLowerCase() === 'hoaimy' || v.toLowerCase() === 'namminh') {
    return 'edge';
  }
  return 'capcut';
}

export function resolveSegmenterConfig(opts: {
  profile?: SegmenterProfile | string;
  voiceId?: string;
  engine?: TtsEngineKind;
  maxChars?: number;
} = {}): SegmenterConfig {
  const eng = opts.engine ?? detectTtsEngine(opts.voiceId);
  const resolvedMax = opts.maxChars !== undefined
    ? opts.maxChars
    : eng === 'edge'
      ? 220
      : eng === 'local'
        ? 160
        : 120;
  const prof = (opts.profile || 'general').toLowerCase().trim() === 'story' ? 'story' : 'general';
  if (prof === 'story') {
    return {
      ...DEFAULT_CONFIG,
      profile: 'story',
      maxChars: resolvedMax,
      targetRatio: 0.80,
      splitPenalty: 7.0,
      mergeShortTurns: true,
    };
  }
  return {
    ...DEFAULT_CONFIG,
    profile: 'general',
    maxChars: resolvedMax,
    targetRatio: 0.72,
    splitPenalty: 6.0,
    mergeShortTurns: false,
  };
}

const INF = Number.POSITIVE_INFINITY;

const W_STRONG = 0.5;
const W_DASH = 1.0;
const W_COMMA = 1.5;
const W_TERMINAL = 2.0;
const W_CLOSER = 2.5;
const W_OPENER = 2.5;
const W_CONJ = 3.5;
const W_OTHER_PUNCT = 6.0;
const W_FUNC = 8.0;
const W_WORD = 14.0;
const P_STRAND = 6.0;
const P_POSTPOSED = 6.0;
const P_SOFT_BRACKET = 22.0;
const P_SOFT_QUOTE = 14.0;
const P_SOFT_NAME = 16.0;
const P_RELAXED = 60.0;

const setOf = (s: string) => new Set(Array.from(s));

const SPACE_RE = /^[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]$/;
const TERMINALS = setOf('.!?…‼⁇⁈⁉');
const CJK_TERMINALS = setOf('。！？');
const CLOSERS = setOf('"\'”’»)]}）」』】》〉');
const OPENERS = setOf('“«([{（「『【《〈');
const STRONG_MEDIAL = setOf(';；:：');
const DASHES = setOf('—–');
const COMMAS = setOf(',，、');
const JOINERS = setOf('\'’-‐');
const URL_TRAIL = setOf('.,;:!?)]}"\'”’»」』');

const BRACKET_PAIRS: Record<string, string> = { '(': ')', '[': ']', '{': '}', '（': '）', '【': '】', '《': '》', '〈': '〉' };
const QUOTE_PAIRS: Record<string, string> = { '“': '”', '«': '»', '「': '」', '『': '』' };
const ALL_PAIRS: Record<string, string> = { ...BRACKET_PAIRS, ...QUOTE_PAIRS };
const PAIR_CLOSERS = new Set(Object.values(ALL_PAIRS));

const URL_RE = /(?:https?:\/\/|www\.)\S+/g;
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;
const NUMBER_RE = /[0-9]+(?:[.,:/][0-9]+)+/g;
const ACRONYM_RE = /(?<![A-Za-z])(?:[A-Za-z]\.){2,}/g;

const TITLE_ABBREV = new Set([
  'mr', 'mrs', 'ms', 'dr', 'prof', 'st', 'mt', 'gen', 'col', 'capt', 'lt', 'sgt', 'rev',
  'gov', 'sen', 'rep', 'pres', 'hon', 'vs', 'mme', 'mlle', 'messrs',
  'tp', 'tx', 'ts', 'ths', 'pgs', 'gs', 'bs', 'ks', 'ls', 'q', 'p',
]);
const GENERAL_ABBREV = new Set([
  'etc', 'inc', 'ltd', 'co', 'corp', 'jr', 'sr', 'approx', 'dept', 'est', 'cf', 'al', 'ca',
  'jan', 'feb', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec', 'vv',
]);
const NUM_ABBREV = new Set(['no', 'nos', 'vol', 'vols', 'fig', 'figs', 'pp', 'art', 'sec', 'ch', 'chap', 'tr', 'eq', 'ref']);
const ACRONYM_CAN_END = new Set(['v.v.', 'a.m.', 'p.m.']);

const CONJ = new Set([
  'và', 'nhưng', 'mà', 'hoặc', 'hay', 'nên', 'vì', 'nếu', 'khi', 'để', 'rồi', 'song',
  'còn', 'thì', 'tuy', 'dù', 'nhờ', 'bởi', 'liền', 'bỗng', 'chợt',
  'and', 'but', 'or', 'nor', 'so', 'yet', 'because', 'although', 'though', 'while', 'whereas',
  'if', 'unless', 'since', 'when', 'where', 'which', 'who', 'whom', 'whose', 'that', 'after',
  'before', 'until', 'however', 'therefore', 'moreover', 'meanwhile', 'consequently', 'whether',
  'then', 'suddenly',
]);
const CONJ2 = new Set([
  'trong khi', 'bởi vì', 'vì vậy', 'vì thế', 'do đó', 'tuy nhiên', 'mặc dù', 'thậm chí',
  'ngoài ra', 'sau đó', 'trước khi', 'sau khi', 'cho nên', 'hơn nữa', 'đồng thời', 'cho đến',
  'mặt khác', 'cụ thể là', 'theo đó', 'ngược lại', 'tức thì', 'ngay lập tức', 'thế là', 'lúc này',
  'as well', 'so that', 'even though', 'even if', 'in order', 'such as', 'rather than',
]);
const HEAD_FUNC = new Set([
  'của', 'cho', 'với', 'trong', 'ngoài', 'trên', 'dưới', 'ở', 'tại', 'từ', 'đến', 'tới', 'về',
  'bằng', 'theo', 'như', 'là', 'được', 'bị', 'những', 'các', 'một', 'mọi', 'mỗi', 'từng',
  'vào', 'giữa', 'qua', 'đối', 'thuộc', 'cái', 'chiếc', 'đã', 'đang', 'sẽ', 'vừa', 'mới',
  'không', 'chưa', 'chẳng', 'rất', 'cũng', 'vẫn', 'đều', 'hãy', 'đừng',
  'of', 'in', 'on', 'at', 'to', 'for', 'with', 'from', 'by', 'about', 'into', 'onto', 'over',
  'under', 'between', 'among', 'through', 'during', 'without', 'within', 'across', 'against',
  'the', 'a', 'an', 'these', 'those', 'its', 'his', 'her', 'their', 'our', 'my', 'your',
  'is', 'are', 'was', 'were', 'be', 'been', 'being', 'has', 'have', 'had', 'will', 'would',
  'can', 'could', 'should', 'may', 'might', 'must', 'not', 'very',
]);
const POSTPOSED = new Set(['này', 'đó', 'kia', 'ấy', 'nọ', 'nhé', 'nhỉ', 'à', 'ạ', 'ư', 'chứ', 'đấy', 'thôi', 'lắm', 'nữa']);
const CJK_CONJ = ['但是', '可是', '因为', '所以', '如果', '虽然', '然而', '而且', '并且', '然后', '于是',
  '不过', '因此', '以及', '或者', '但', '而', '并', '或', '和', '与', '及'];
const CJK_POST = setOf('了着过的之吗呢吧啊呀们地得么');
const CJK_PREP = setOf('在把被对从向给于以');

// ─── Phân loại ký tự ───────────────────────────────────────────────────────
const RE_LETTER_MARK_DIGIT = /^[\p{L}\p{M}\p{Nd}]$/u;
const RE_LU = /^\p{Lu}$/u;
const RE_LL = /^\p{Ll}$/u;
const RE_ND = /^\p{Nd}$/u;

export const isSpace = (ch: string) => SPACE_RE.test(ch);
export function isCjk(ch: string): boolean {
  const cp = ch.codePointAt(0) ?? 0;
  return (cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x3400 && cp <= 0x4dbf) || (cp >= 0xf900 && cp <= 0xfaff)
    || (cp >= 0x3040 && cp <= 0x30ff) || (cp >= 0x20000 && cp <= 0x2a6df);
}
export const isWordChar = (ch: string) => RE_LETTER_MARK_DIGIT.test(ch) && !isCjk(ch);
const isUpper = (ch: string) => RE_LU.test(ch);
const isLower = (ch: string) => RE_LL.test(ch);
const isDigit = (ch: string) => RE_ND.test(ch);

// ─── Tầng 1: Tokenization ──────────────────────────────────────────────────
type TokKind = 'space' | 'word' | 'cjk' | 'punct';
interface Token { start: number; end: number; kind: TokKind; }

function tokenize(c: string[]): Token[] {
  const toks: Token[] = [];
  const n = c.length;
  let i = 0;
  while (i < n) {
    const ch = c[i];
    let j: number;
    if (isSpace(ch)) {
      j = i + 1;
      while (j < n && isSpace(c[j])) j++;
      toks.push({ start: i, end: j, kind: 'space' });
    } else if (isCjk(ch)) {
      j = i + 1;
      toks.push({ start: i, end: j, kind: 'cjk' });
    } else if (isWordChar(ch)) {
      j = i + 1;
      while (j < n) {
        const x = c[j];
        if (isWordChar(x)) j++;
        else if (JOINERS.has(x) && j + 1 < n && isWordChar(c[j + 1])) j += 2;
        else break;
      }
      toks.push({ start: i, end: j, kind: 'word' });
    } else {
      j = i + 1;
      toks.push({ start: i, end: j, kind: 'punct' });
    }
    i = j;
  }
  return toks;
}

type HardSpan = [number, number, string];
type SoftSpan = [number, number, number];

class Analysis {
  readonly c: string[];
  readonly text: string;
  readonly n: number;
  readonly cfg: SegmenterConfig;
  readonly toks: Token[];
  readonly P: Float64Array;
  readonly tokAt: Int32Array;
  readonly hard: HardSpan[] = [];
  readonly soft: SoftSpan[] = [];
  readonly hardGap: Uint8Array;
  readonly softGap: Float64Array;
  readonly hardAt: Int32Array;
  private readonly u16ToCp: Int32Array;

  constructor(text: string, cfg: SegmenterConfig) {
    this.text = text;
    this.c = Array.from(text);
    this.n = this.c.length;
    this.cfg = cfg;
    this.toks = tokenize(this.c);
    const n = this.n;

    this.P = new Float64Array(n + 1);
    let acc = 0;
    for (let i = 0; i < n; i++) {
      acc += isCjk(this.c[i]) ? cfg.cjkWeight : 1.0;
      this.P[i + 1] = acc;
    }

    this.tokAt = new Int32Array(n);
    this.toks.forEach((t, idx) => {
      for (let x = t.start; x < t.end; x++) this.tokAt[x] = idx;
    });

    this.u16ToCp = new Int32Array(text.length + 1);
    let cp = 0;
    for (let u = 0; u < text.length;) {
      this.u16ToCp[u] = cp;
      const code = text.codePointAt(u) ?? 0;
      if (code > 0xffff) {
        this.u16ToCp[u + 1] = cp;
        u += 2;
      } else {
        u += 1;
      }
      cp++;
    }
    this.u16ToCp[text.length] = cp;

    this.hardGap = new Uint8Array(n + 1);
    this.softGap = new Float64Array(n + 1);
    this.hardAt = new Int32Array(n).fill(-1);
    if (cfg.useSpans) this.findSpans();
  }

  eff(s: number, e: number): number {
    return this.P[e] - this.P[s];
  }

  nextNonspace(i: number): number | null {
    while (i < this.n) {
      if (!isSpace(this.c[i])) return i;
      i++;
    }
    return null;
  }

  isOpenerAt(i: number): boolean {
    const c = this.c;
    const ch = c[i];
    if (OPENERS.has(ch)) return true;
    if (ch === '"' || ch === "'") {
      const nxtOk = i + 1 < this.n && !isSpace(c[i + 1]);
      const prevOk = i === 0 || isSpace(c[i - 1]) || OPENERS.has(c[i - 1]);
      return nxtOk && prevOk;
    }
    return false;
  }

  slice(s: number, e: number): string {
    return this.c.slice(s, e).join('');
  }

  wordLower(t: Token): string {
    return this.slice(t.start, t.end).toLowerCase();
  }

  private matches(re: RegExp): Array<[number, number, string]> {
    const out: Array<[number, number, string]> = [];
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(this.text)) !== null) {
      out.push([this.u16ToCp[m.index], this.u16ToCp[m.index + m[0].length], m[0]]);
      if (m[0].length === 0) re.lastIndex++;
    }
    return out;
  }

  private findSpans(): void {
    const { c, n, cfg, hard, soft } = this;

    for (const [s0, e0] of this.matches(URL_RE)) {
      let e = e0;
      while (e > s0 && URL_TRAIL.has(c[e - 1])) e--;
      if (e > s0) hard.push([s0, e, 'url']);
    }
    for (const [s, e] of this.matches(EMAIL_RE)) hard.push([s, e, 'email']);
    for (const [s, e] of this.matches(NUMBER_RE)) hard.push([s, e, 'number']);
    for (const [s, e, str] of this.matches(ACRONYM_RE)) {
      hard.push([s, e, ACRONYM_CAN_END.has(str.toLowerCase()) ? 'acronym_end' : 'acronym']);
    }

    for (const t of this.toks) {
      if (t.kind !== 'word' || t.end >= n || c[t.end] !== '.') continue;
      const w = this.wordLower(t);
      const nxt = this.nextNonspace(t.end + 1);
      if (TITLE_ABBREV.has(w)) hard.push([t.start, t.end + 1, 'title']);
      else if (GENERAL_ABBREV.has(w)) hard.push([t.start, t.end + 1, 'abbrev']);
      else if (NUM_ABBREV.has(w) && nxt !== null && isDigit(c[nxt])) hard.push([t.start, t.end + 1, 'numabbrev']);
      else if (t.end - t.start === 1 && isUpper(c[t.start]) && nxt !== null && isUpper(c[nxt])) {
        hard.push([t.start, t.end + 1, 'initial']);
      } else if (t.end - t.start >= 1 && t.end - t.start <= 3 && /^\d+$/.test(w) && nxt !== null) {
        let hasNl = false;
        for (let idx = t.end + 1; idx < nxt; idx++) {
          if (c[idx] === '\n') { hasNl = true; break; }
        }
        if (!hasNl) {
          let lineStart = t.start === 0;
          if (!lineStart) {
            let k = t.start - 1;
            while (k >= 0 && isSpace(c[k]) && c[k] !== '\n') k--;
            lineStart = k >= 0 && c[k] === '\n';
          }
          if (lineStart) hard.push([t.start, t.end + 1, 'listnum']);
        }
      }
    }

    const stack: Array<[string, number]> = [];
    for (let i = 0; i < n; i++) {
      const ch = c[i];
      if (ch in ALL_PAIRS) {
        stack.push([ch, i]);
      } else if (PAIR_CLOSERS.has(ch)) {
        let k = stack.length - 1;
        while (k >= 0 && ALL_PAIRS[stack[k][0]] !== ch) k--;
        if (k >= 0) {
          const [op, s] = stack[k];
          stack.length = k;
          if (this.eff(s, i + 1) <= cfg.maxChars) {
            const pen = op in BRACKET_PAIRS
              ? (cfg.profile === 'general' ? 28.0 : 18.0)
              : (cfg.profile === 'story' ? 20.0 : 12.0);
            soft.push([s, i + 1, pen]);
          }
        }
      } else if (ch === '"') {
        if (stack.length && stack[stack.length - 1][0] === '"' && !this.isOpenerAt(i)) {
          const s = stack.pop()![1];
          if (this.eff(s, i + 1) <= cfg.maxChars) {
            soft.push([s, i + 1, cfg.profile === 'story' ? 20.0 : 12.0]);
          }
        } else if (this.isOpenerAt(i)) {
          stack.push(['"', i]);
        }
      }
    }

    const toks = this.toks;
    let run: number[] = [];
    const flush = () => {
      if (run.length >= 2) soft.push([toks[run[0]].start, toks[run[run.length - 1]].end, P_SOFT_NAME]);
    };
    for (let idx = 0; idx < toks.length; idx++) {
      const t = toks[idx];
      if (t.kind === 'word' && isUpper(c[t.start])) {
        const prev = idx >= 1 ? toks[idx - 1] : null;
        if (run.length && prev !== null && prev.kind === 'space' && prev.end - prev.start === 1
          && c[prev.start] === ' ' && run[run.length - 1] === idx - 2) {
          run.push(idx);
        } else {
          flush();
          run = [idx];
        }
      } else if (t.kind === 'space') {
        continue;
      } else {
        flush();
        run = [];
      }
    }
    flush();

    hard.forEach(([s, e], si) => {
      for (let g = s + 1; g < e; g++) this.hardGap[g] = 1;
      for (let p = s; p < e; p++) if (this.hardAt[p] === -1) this.hardAt[p] = si;
    });
    for (const [s, e, pen] of soft) {
      for (let g = s + 1; g < e; g++) if (pen > this.softGap[g]) this.softGap[g] = pen;
    }
  }

  // ─── Tầng 3: SBD ─────────────────────────────────────────────────────────
  sentenceSpans(): Array<[number, number]> {
    const { c, toks, cfg } = this;
    const T = toks.length;
    const bounds: number[] = [];
    let i = 0;
    while (i < T) {
      const t = toks[i];
      if (t.kind === 'space') {
        if (this.slice(t.start, t.end).includes('\n')) bounds.push(t.start);
        i++;
        continue;
      }
      const ch = c[t.start];
      if (t.kind !== 'punct' || !(TERMINALS.has(ch) || CJK_TERMINALS.has(ch))) {
        i++;
        continue;
      }
      let j = i;
      let hasCjk = false;
      let hasCloser = false;
      let hasDot = false;
      const dots: number[] = [];
      while (j < T && toks[j].kind === 'punct' && (TERMINALS.has(c[toks[j].start]) || CJK_TERMINALS.has(c[toks[j].start]))) {
        const x = c[toks[j].start];
        if (CJK_TERMINALS.has(x)) hasCjk = true;
        if (x === '.') {
          hasDot = true;
          dots.push(toks[j].start);
        }
        j++;
      }
      while (j < T && toks[j].kind === 'punct' && CLOSERS.has(c[toks[j].start])) {
        hasCloser = true;
        j++;
      }
      const k = toks[j - 1].end;
      const nxt = this.nextNonspace(k);

      let ok = true;
      if (cfg.useSpans) {
        for (const p of dots) {
          const si = this.hardAt[p];
          if (si >= 0) {
            const kind = this.hard[si][2];
            if ((kind === 'abbrev' || kind === 'acronym_end') && nxt !== null && isUpper(c[nxt])) continue;
            ok = false;
            break;
          }
        }
      }
      if (ok && nxt !== null && !hasCjk) {
        const nc = c[nxt];
        if (nxt === k && !isCjk(nc) && !OPENERS.has(nc)) ok = false;
        else if (isLower(nc) && (hasDot || hasCloser)) ok = false;
        else if (COMMAS.has(nc) || STRONG_MEDIAL.has(nc)) ok = false;
      }
      if (ok && nxt !== null) bounds.push(k);
      i = j;
    }

    const raw: Array<[number, number]> = [];
    let prev = 0;
    for (const b of [...bounds, this.n]) {
      let s = prev;
      while (s < b && isSpace(c[s])) s++;
      let e = b;
      while (e > s && isSpace(c[e - 1])) e--;
      if (e > s) raw.push([s, e]);
      prev = b;
    }

    const out: Array<[number, number]> = [];
    let pending: number | null = null;
    for (const [s0, e] of raw) {
      let s = s0;
      if (pending !== null) {
        s = pending;
        pending = null;
      }
      if (!this.hasContent(s, e)) {
        if (out.length) out[out.length - 1] = [out[out.length - 1][0], e];
        else pending = s;
        continue;
      }
      out.push([s, e]);
    }
    if (pending !== null && raw.length) out.push([pending, raw[raw.length - 1][1]]);
    if (cfg.mergeShortTurns && out.length > 1) {
      const merged: Array<[number, number]> = [out[0]];
      const mergeCap = Math.min(72.0, cfg.maxChars * 0.68);
      for (let idx = 1; idx < out.length; idx++) {
        const [s, e] = out[idx];
        const [ps, pe] = merged[merged.length - 1];
        if (!this.slice(pe, s).includes('\n')
          && this.eff(ps, pe) <= 32.0
          && this.eff(s, e) <= 32.0
          && this.eff(ps, e) <= mergeCap) {
          merged[merged.length - 1] = [ps, e];
        } else {
          merged.push([s, e]);
        }
      }
      return merged;
    }
    return out;
  }

  private hasContent(s: number, e: number): boolean {
    for (let x = s; x < e; x++) {
      const ch = this.c[x];
      if (isWordChar(ch) || isCjk(ch)) return true;
    }
    return false;
  }

  // ─── Tầng 4: Chunking bằng DP ─────────────────────────────────────────────
  private segCost(L: number): number {
    const cfg = this.cfg;
    if (L > cfg.maxChars) return INF;
    const T = cfg.maxChars * cfg.targetRatio;
    const dev = (L - T) / T;
    let cost = cfg.splitPenalty + cfg.alpha * dev * dev;
    if (L < Math.min(cfg.minChars, cfg.maxChars * 0.3)) cost += cfg.orphanPenalty;
    return cost;
  }

  private breakCost(ns: number[], m: number, relaxed: boolean): number {
    const { c, toks, cfg } = this;
    const ti = ns[m];
    const t = toks[ti];
    const p = toks[ns[m - 1]];
    const g = t.start;
    let extra = 0;

    if (cfg.useSpans && this.hardGap[g]) {
      if (!relaxed) return INF;
      extra += P_RELAXED;
    }
    if (t.kind === 'punct' && !this.isOpenerAt(t.start)) {
      if (!relaxed) return INF;
      extra += P_RELAXED;
    }
    if (p.kind === 'punct' && this.isOpenerAt(p.start)) {
      if (!relaxed) return INF;
      extra += P_RELAXED;
    }
    if (cfg.useSpans && p.kind === 'punct' && c[p.start] === '.') {
      const si = this.hardAt[p.start];
      if (si >= 0) {
        const k = this.hard[si][2];
        if (k === 'title' || k === 'numabbrev' || k === 'initial' || k === 'listnum') {
          if (!relaxed) return INF;
          extra += P_RELAXED;
        }
      }
    }

    let cost: number;
    if (p.kind === 'punct') {
      const x = c[p.start];
      if (STRONG_MEDIAL.has(x)) cost = W_STRONG;
      else if (DASHES.has(x) || x === '-') cost = W_DASH;
      else if (COMMAS.has(x)) cost = W_COMMA;
      else if (TERMINALS.has(x) || CJK_TERMINALS.has(x)) cost = W_TERMINAL;
      else if (CLOSERS.has(x)) cost = W_CLOSER;
      else cost = W_OTHER_PUNCT;
    } else if (t.kind === 'punct') {
      cost = W_OPENER;
    } else {
      cost = W_WORD;
      if (cfg.useLexicon) {
        if (t.kind === 'word') {
          const w = this.wordLower(t);
          let w2 = '';
          if (ti + 2 < toks.length && toks[ti + 1].kind === 'space' && toks[ti + 2].kind === 'word') {
            w2 = w + ' ' + this.wordLower(toks[ti + 2]);
          }
          if ((w2 && CONJ2.has(w2)) || CONJ.has(w)) cost = W_CONJ;
          else if (HEAD_FUNC.has(w)) cost = W_FUNC;
          if (POSTPOSED.has(w)) cost += P_POSTPOSED;
        } else if (t.kind === 'cjk') {
          let matchedConj = false;
          for (const cj of CJK_CONJ) {
            if (this.slice(t.start, t.start + cj.length) === cj) {
              cost = W_CONJ;
              matchedConj = true;
              break;
            }
          }
          if (!matchedConj && CJK_PREP.has(c[t.start])) cost = W_FUNC;
          if (CJK_POST.has(c[t.start])) cost += P_POSTPOSED;
        }
        if (p.kind === 'word') {
          const pw = this.wordLower(p);
          if (HEAD_FUNC.has(pw) || CONJ.has(pw)) cost += P_STRAND;
        }
        if (p.kind === 'cjk' && CJK_PREP.has(c[p.start])) cost += P_STRAND;
      }
    }
    if (cfg.useSpans) cost += this.softGap[g];
    return cost + extra;
  }

  private optimise(ns: number[], relaxed: boolean): number[] | null {
    const { toks, cfg } = this;
    const M = ns.length;
    const brk = new Float64Array(M);
    for (let m = 1; m < M; m++) brk[m] = this.breakCost(ns, m, relaxed);

    if (!cfg.useDp) {
      const starts = [0];
      let i = 0;
      for (;;) {
        const start = toks[ns[i]].start;
        if (this.eff(start, toks[ns[M - 1]].end) <= cfg.maxChars) return starts;
        let bestJ = -1;
        let bestC = INF;
        for (let j = i + 1; j < M; j++) {
          const L = this.eff(start, toks[ns[j - 1]].end);
          if (L > cfg.maxChars) break;
          if (brk[j] === INF) continue;
          const cst = this.segCost(L) + brk[j];
          if (cst < bestC) {
            bestC = cst;
            bestJ = j;
          }
        }
        if (bestJ < 0) return null;
        starts.push(bestJ);
        i = bestJ;
      }
    }

    const dp = new Float64Array(M + 1).fill(INF);
    const back = new Int32Array(M + 1).fill(-1);
    dp[0] = 0;
    for (let j = 1; j <= M; j++) {
      const bj = j < M ? brk[j] : 0;
      if (bj === INF) continue;
      const end = toks[ns[j - 1]].end;
      for (let i = j - 1; i >= 0; i--) {
        const L = this.eff(toks[ns[i]].start, end);
        if (L > cfg.maxChars) break;
        if (dp[i] < INF) {
          const cst = dp[i] + this.segCost(L) + bj;
          if (cst < dp[j]) {
            dp[j] = cst;
            back[j] = i;
          }
        }
      }
    }
    if (dp[M] === INF) return null;
    const starts: number[] = [];
    let j = M;
    while (j > 0) {
      const i = back[j];
      starts.push(i);
      j = i;
    }
    return starts.reverse();
  }

  private hardWrap(s: number, e: number): Array<[number, number]> {
    const { c } = this;
    const maxc = this.cfg.maxChars;
    const out: Array<[number, number]> = [];
    let cs = s;
    while (cs < e) {
      while (cs < e && isSpace(c[cs])) cs++;
      if (cs >= e) break;
      let ce = cs;
      while (ce < e && this.eff(cs, ce + 1) <= maxc) ce++;
      if (ce === cs) ce = cs + 1;
      if (ce < e) {
        let k = ce;
        while (k > cs && !isSpace(c[k])) k--;
        if (k > cs) ce = k;
      }
      let end = ce;
      while (end > cs && isSpace(c[end - 1])) end--;
      out.push([cs, end]);
      cs = ce;
    }
    return out;
  }

  chunkSentence(s: number, e: number): Array<[number, number]> {
    if (this.eff(s, e) <= this.cfg.maxChars) return [[s, e]];
    const a = this.tokAt[s];
    const b = this.tokAt[e - 1];
    const ns: number[] = [];
    for (let idx = a; idx <= b; idx++) if (this.toks[idx].kind !== 'space') ns.push(idx);
    let starts = this.optimise(ns, false);
    if (starts === null) starts = this.optimise(ns, true);
    if (starts === null) return this.hardWrap(s, e);
    const spans: Array<[number, number]> = [];
    for (let k = 0; k < starts.length; k++) {
      const si = starts[k];
      const ej = k + 1 < starts.length ? starts[k + 1] : ns.length;
      spans.push([this.toks[ns[si]].start, this.toks[ns[ej - 1]].end]);
    }
    return spans;
  }

  segment(): Array<[number, number]> {
    const out: Array<[number, number]> = [];
    for (const [s, e] of this.sentenceSpans()) out.push(...this.chunkSentence(s, e));
    return out;
  }
}

// ─── API công khai ──────────────────────────────────────────────────────────
function resolve(maxChars?: number, cfg?: Partial<SegmenterConfig>): SegmenterConfig {
  const merged = { ...DEFAULT_CONFIG, ...(cfg || {}) };
  if (maxChars !== undefined) merged.maxChars = maxChars;
  return merged;
}

export function splitSentences(text: string, cfg?: Partial<SegmenterConfig>): string[] {
  if (!text || !text.trim()) return [];
  const a = new Analysis(text, resolve(undefined, cfg));
  return a.sentenceSpans().map(([s, e]) => a.slice(s, e));
}

/** Trả về offset (theo code point) của từng chunk. */
export function segmentSpans(text: string, maxChars?: number, cfg?: Partial<SegmenterConfig>): Array<[number, number]> {
  if (!text || !text.trim()) return [];
  return new Analysis(text, resolve(maxChars, cfg)).segment();
}

/** Chia văn bản thành các chunk đọc tối ưu (lossless, <= maxChars hiệu dụng). */
export function splitIntoChunks(text: string, maxChars?: number, cfg?: Partial<SegmenterConfig>): string[] {
  if (!text || !text.trim()) return [];
  const a = new Analysis(text, resolve(maxChars, cfg));
  return a.segment().map(([s, e]) => a.slice(s, e));
}
