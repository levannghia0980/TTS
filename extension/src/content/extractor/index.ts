import { anchors, resetAnchors } from './registry';
import { findRoot, scoringRoot } from './root';
import { RawBlock, collectBlocks, keepBlock } from './walker';
import { cleanText, detectLang, detectPageLanguage, detectContentProfile } from './filters';

export interface ExtractedBlock {
  xid: string;
  text: string;
  kind: 'heading' | 'para';
  lang: 'vi' | 'other';
}

export interface ExtractResult {
  blocks: ExtractedBlock[];
  method: string;
  totalChars: number;
  viCount: number;
  detectedLang: string;
  detectedProfile: 'story' | 'general';
}

export { detectPageLanguage, detectContentProfile };

function finalize(raw: RawBlock[]): RawBlock[] {
  const kept = raw.filter(keepBlock);
  // Bỏ đoạn trùng liên tiếp
  const out: RawBlock[] = [];
  for (const b of kept) {
    if (out.length && out[out.length - 1].text === b.text) continue;
    out.push(b);
  }
  // Bỏ tiêu đề treo ở cuối
  while (out.length && out[out.length - 1].kind === 'heading') out.pop();
  return out;
}

function fromSelection(): ExtractResult | null {
  const sel = window.getSelection();
  const raw = sel?.toString() || '';
  if (raw.trim().length <= 20) return null;
  const blocks: ExtractedBlock[] = raw
    .split(/\n+/)
    .map(cleanText)
    .filter((t) => t.length > 1)
    .map((text, i) => ({ xid: `sel-${i}`, text, kind: 'para', lang: detectLang(text) }));
  return summarize(blocks, 'selection');
}

function summarize(blocks: ExtractedBlock[], method: string): ExtractResult {
  const allSample = blocks.slice(0, 15).map((b) => b.text).join(' ');
  const pageLang = detectPageLanguage(allSample);
  const pageProfile = detectContentProfile(
    typeof window !== 'undefined' ? window.location.href : '',
    typeof document !== 'undefined' ? document.title : '',
    allSample
  );
  return {
    blocks,
    method,
    totalChars: blocks.reduce((s, b) => s + b.text.length, 0),
    viCount: blocks.filter((b) => b.lang === 'vi').length,
    detectedLang: pageLang,
    detectedProfile: pageProfile
  };
}

export function extractContent(forcedRoot?: HTMLElement): ExtractResult {
  resetAnchors();

  if (!forcedRoot) {
    const sel = fromSelection();
    if (sel) return sel;
  }

  let method = 'picked';
  let blocks: RawBlock[];
  if (forcedRoot) {
    blocks = finalize(collectBlocks(forcedRoot));
  } else {
    const found = findRoot();
    method = found.method;
    blocks = finalize(collectBlocks(found.root));
    if (blocks.length === 0 && method !== 'scoring') {
      const s = scoringRoot();
      if (s) {
        method = 'scoring';
        blocks = finalize(collectBlocks(s));
      }
    }
  }

  const result: ExtractedBlock[] = blocks.map((b, i) => {
    const xid = `b-${i}`;
    anchors.set(xid, b.anchor);
    return { xid, text: b.text, kind: b.kind, lang: detectLang(b.text) };
  });
  return summarize(result, method);
}

