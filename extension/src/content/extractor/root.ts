// Tìm vùng chứa bài chính: cấu hình riêng → Readability → chấm điểm mật độ chữ
import { Readability } from '@mozilla/readability';
import { EXCLUDE_SELECTOR, cleanText, directTextLen, measure } from './filters';

interface Adapter {
  test: (host: string) => boolean;
  root: string;
}

// Cấu hình riêng cho trang hay gặp (thêm dần)
const ADAPTERS: Adapter[] = [
  { test: (h) => /(^|\.)wikipedia\.org$/.test(h), root: '#mw-content-text .mw-parser-output' },
  { test: (h) => /(^|\.)fandom\.com$/.test(h), root: '#mw-content-text .mw-parser-output' },
  { test: (h) => /(^|\.)medium\.com$/.test(h), root: 'article' }
];

function textLen(el: Element): number {
  return cleanText(measure([el]).text).length;
}

function depth(el: Element): number {
  let d = 0;
  for (let p: Element | null = el; p; p = p.parentElement) d++;
  return d;
}

function readabilityRoot(): HTMLElement | null {
  const ATTR = 'data-tts-rid';
  const marked = Array.from(
    document.body.querySelectorAll<HTMLElement>('p, li, blockquote, pre, h2, h3, h4, h5, h6, div')
  );
  marked.forEach((el, i) => el.setAttribute(ATTR, String(i)));
  try {
    const clone = document.cloneNode(true) as Document;
    const article = new Readability(clone).parse();
    if (!article?.content) return null;

    const doc = new DOMParser().parseFromString(article.content, 'text/html');
    const survivors = Array.from(doc.querySelectorAll(`[${ATTR}]`))
      .map((e) => marked[Number(e.getAttribute(ATTR))])
      .filter(Boolean);

    let holders = survivors.filter((el) => /^(P|LI|BLOCKQUOTE|PRE|H[2-6])$/.test(el.tagName));
    if (holders.length < 3) {
      // Trang truyện: chữ nằm thẳng trong <div>, ngắt bằng <br>
      holders = survivors.filter((el) => el.tagName === 'DIV' && directTextLen(el) >= 80);
    }
    if (!holders.length) return null;

    // Vùng sâu nhất chứa ≥ 80% lượng chữ Readability giữ lại
    const sum = new Map<HTMLElement, number>();
    const count = new Map<HTMLElement, number>();
    let total = 0;
    for (const h of holders) {
      const len = (h.textContent || '').length;
      total += len;
      for (let p: HTMLElement | null = h; p && p !== document.documentElement; p = p.parentElement) {
        sum.set(p, (sum.get(p) || 0) + len);
        count.set(p, (count.get(p) || 0) + 1);
      }
    }
    const minCount = Math.min(2, holders.length);
    let best: HTMLElement | null = null;
    let bestDepth = -1;
    sum.forEach((v, el) => {
      if (v >= 0.8 * total && (count.get(el) || 0) >= minCount) {
        const d = depth(el);
        if (d > bestDepth) {
          bestDepth = d;
          best = el;
        }
      }
    });
    return best;
  } catch (e) {
    console.warn('[TTS] Readability lỗi:', e);
    return null;
  } finally {
    marked.forEach((el) => el.removeAttribute(ATTR));
  }
}

export function scoringRoot(): HTMLElement | null {
  const scores = new Map<HTMLElement, number>();
  const add = (el: HTMLElement | null | undefined, v: number) => {
    if (el && el !== document.documentElement) scores.set(el, (scores.get(el) || 0) + v);
  };
  const skipSel = `nav, header, footer, aside, form, ${EXCLUDE_SELECTOR}`;

  document.body
    .querySelectorAll<HTMLElement>('p, pre, blockquote, div, td, section, article')
    .forEach((el) => {
      if (el.closest(skipSel)) return;
      const isP = el.tagName === 'P' || el.tagName === 'BLOCKQUOTE' || el.tagName === 'PRE';
      const text = isP ? cleanText(measure([el]).text) : '';
      const len = isP ? text.length : directTextLen(el);
      if (len < 25) return;
      const commas = isP ? (text.match(/[,，、]/g) || []).length : Math.floor(len / 80);
      const score = 1 + commas + Math.min(Math.floor(len / 100), 3);
      if (!isP) add(el, score); // div chứa chữ trực tiếp (trang truyện)
      add(el.parentElement, score);
      add(el.parentElement?.parentElement, score / 2);
    });

  let best: HTMLElement | null = null;
  let bestScore = 0;
  scores.forEach((s, el) => {
    const f = s * (1 - measure([el]).linkDensity);
    if (f > bestScore) {
      bestScore = f;
      best = el;
    }
  });
  return best;
}

const COMMON_ARTICLE_SELECTORS = [
  '#chapter-c', '.chapter-c',
  '#chapter-content', '.chapter-content',
  '.box-chap', '.reading-content',
  '.content-story', '.truyen-content',
  '#vung-doc', '.vung-doc',
  '#readcontent', '.readcontent',
  '#content-truyen', '.story-content',
  '#js-read__content',
  '.entry-content', '.post-content'
];

export function findRoot(): { root: HTMLElement; method: string } {
  const adapter = ADAPTERS.find((a) => a.test(location.hostname));
  if (adapter) {
    const el = document.querySelector<HTMLElement>(adapter.root);
    if (el && textLen(el) > 200) return { root: el, method: 'adapter' };
  }

  // Nhận diện tức thì cho các web truyện/tiểu thuyết/báo phổ biến
  for (const sel of COMMON_ARTICLE_SELECTORS) {
    const el = document.querySelector<HTMLElement>(sel);
    if (el && textLen(el) > 250) {
      return { root: el, method: 'novel-selector' };
    }
  }

  const r = readabilityRoot();
  if (r && textLen(r) >= 250) return { root: r, method: 'readability' };

  const s = scoringRoot();
  if (s) return { root: s, method: 'scoring' };

  return { root: document.body, method: 'body' };
}

