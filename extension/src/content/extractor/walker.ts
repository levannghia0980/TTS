// Đi theo thứ tự trên trang, cắt vùng bài chính thành các đoạn đọc
import { Anchor } from './registry';
import { STOP_HEADING_RE, cleanText, isBlockEl, measure, shouldSkip } from './filters';

export interface RawBlock {
  anchor: Anchor;
  text: string;
  kind: 'heading' | 'para';
  linkDensity: number;
}

interface Ctx {
  root: HTMLElement;
  stopped: boolean;
  out: RawBlock[];
}

function isWhitespaceNode(n: Node): boolean {
  return n.nodeType === 3 && !(n.nodeValue || '').trim();
}

function emitRun(nodes: Node[], parent: HTMLElement, ctx: Ctx, wholeElement: boolean) {
  // Cắt theo <br>
  const segs: Node[][] = [];
  let cur: Node[] = [];
  for (const n of nodes) {
    if (n.nodeType === 1 && (n as Element).tagName.toUpperCase() === 'BR') {
      if (cur.length) segs.push(cur);
      cur = [];
    } else {
      cur.push(n);
    }
  }
  if (cur.length) segs.push(cur);

  const measured = segs
    .map((s) => {
      // Bỏ khoảng trắng thừa ở hai đầu để vị trí chèn chính xác
      let a = 0;
      let b = s.length - 1;
      while (a <= b && isWhitespaceNode(s[a])) a++;
      while (b >= a && isWhitespaceNode(s[b])) b--;
      const trimmed = s.slice(a, b + 1);
      const m = measure(trimmed);
      return { nodes: trimmed, text: cleanText(m.text), linkDensity: m.linkDensity };
    })
    .filter((m) => m.nodes.length && m.text);

  if (!measured.length) return;

  if (wholeElement && measured.length === 1) {
    ctx.out.push({
      anchor: { kind: 'element', el: parent },
      text: measured[0].text,
      kind: 'para',
      linkDensity: measured[0].linkDensity
    });
    return;
  }
  for (const m of measured) {
    ctx.out.push({
      anchor: { kind: 'segment', nodes: m.nodes },
      text: m.text,
      kind: 'para',
      linkDensity: m.linkDensity
    });
  }
}

function walk(el: HTMLElement, ctx: Ctx) {
  if (ctx.stopped) return;
  if (el !== ctx.root && shouldSkip(el)) return;

  const tag = el.tagName.toUpperCase();
  if (/^H[1-6]$/.test(tag)) {
    const m = measure([el]);
    const text = cleanText(m.text);
    if (!text) return;
    const level = Number(tag[1]);
    if (level <= 3 && STOP_HEADING_RE.test(text) && ctx.out.some((b) => b.kind === 'para')) {
      ctx.stopped = true; // Hết bài chính (References, Xem thêm...)
      return;
    }
    ctx.out.push({ anchor: { kind: 'element', el }, text, kind: 'heading', linkDensity: m.linkDensity });
    return;
  }

  const kids = Array.from(el.childNodes);
  if (!kids.some(isBlockEl)) {
    emitRun(kids, el, ctx, true);
    return;
  }

  // Khối hỗn hợp: vừa có chữ trực tiếp vừa có khối con
  let run: Node[] = [];
  for (const c of kids) {
    if (isBlockEl(c)) {
      emitRun(run, el, ctx, false);
      run = [];
      walk(c, ctx);
      if (ctx.stopped) return;
    } else {
      run.push(c);
    }
  }
  emitRun(run, el, ctx, false);
}

export function collectBlocks(root: HTMLElement): RawBlock[] {
  const ctx: Ctx = { root, stopped: false, out: [] };
  walk(root, ctx);
  return ctx.out;
}

/** Giữ đoạn có nghĩa, bỏ nhãn vụn, link, số liệu rời */
export function keepBlock(b: RawBlock): boolean {
  const t = b.text.trim();
  if (!t) return false;
  if (b.kind === 'heading') return t.length >= 2 && t.length <= 250 && b.linkDensity < 0.6;
  if (b.linkDensity > 0.6) return false;

  // Đếm số ký tự chữ cái/chữ Hán/chữ số
  const wordChars = (t.match(/[\p{L}\p{N}]/gu) || []).length;
  if (wordChars < 1) return false;

  // Nếu đoạn có độ dài từ 15 ký tự trở lên thì giữ
  if (t.length >= 15) return true;

  // Câu thoại ngắn trong truyện ("Ừ.", "Hả?", "Không thể nào!", "是的。") vẫn giữ nếu có dấu câu
  return /[.!?…:;"'”»)\]~]$/.test(t) || wordChars >= 2;
}

