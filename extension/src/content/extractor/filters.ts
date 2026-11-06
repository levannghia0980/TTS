// Bộ lọc dùng chung: thẻ cần bỏ, vùng rác, đo chữ, nhận diện tiếng Việt

// Thẻ không bao giờ lấy chữ (kể cả khi nằm giữa đoạn văn)
export const SKIP_TEXT_TAGS = new Set([
  'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'BUTTON', 'SELECT', 'TEXTAREA', 'INPUT',
  'SVG', 'CANVAS', 'IFRAME', 'IMG', 'VIDEO', 'AUDIO', 'PICTURE', 'MATH', 'X-TRANS', 'OBJECT', 'EMBED'
]);

// Khối không bao giờ là nội dung bài đọc
export const SKIP_BLOCK_TAGS = new Set([
  ...SKIP_TEXT_TAGS,
  'NAV', 'ASIDE', 'FOOTER', 'FIGURE', 'FIGCAPTION', 'TABLE', 'PRE', 'FORM', 'DIALOG', 'MENU'
]);

// Thẻ cấp khối (dùng để chia đoạn)
export const BLOCK_TAGS = new Set([
  'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DD', 'DETAILS', 'DIALOG', 'DIV', 'DL', 'DT',
  'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'HEADER', 'HGROUP', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE', 'SECTION', 'SUMMARY',
  'TABLE', 'UL', 'CENTER', 'TBODY', 'THEAD', 'TR', 'TD', 'TH', 'MENU'
]);

// Vùng rác phổ biến (Wikipedia, báo, blog, diễn đàn)
export const EXCLUDE_SELECTOR = [
  '[hidden]', '[aria-hidden="true"]',
  '[role="navigation"]', '[role="complementary"]', '[role="banner"]', '[role="contentinfo"]',
  '[role="dialog"]', '[role="alert"]', '[role="toolbar"]', '[role="menu"]',
  '.infobox', '.navbox', '.vertical-navbox', '.sidebar', '.toc', '#toc', '.reflist', '.references', '.reference',
  '.mw-references-wrap', '.mw-editsection', '.hatnote', '.thumb', '.gallery', '.metadata', '.ambox',
  '.shortdescription', '.catlinks', '.mw-jump-link', '.noprint', '.mw-empty-elt',
  '#comments', '.comments', '.comment-list'
].join(',');

// Từ khóa class/id thường là rác
export const NEGATIVE_RE =
  /(^|[\s_-])(comments?|related|share|sharing|social|breadcrumbs?|sponsor(ed)?|advert\w*|ads?|promo\w*|popup|modal|cookie\w*|newsletter|widget|sidebar|menu|pagination|pager|recommend\w*|subscribe)([\s_-]|$)/i;

// Tiêu đề đánh dấu hết phần bài chính
export const STOP_HEADING_RE =
  /^(references|notes|see also|external links|further reading|bibliography|sources|citations|footnotes|tài liệu tham khảo|tham khảo|chú thích|xem thêm|liên kết ngoài|đọc thêm|bình luận|comments?|related (posts|articles)|bài viết liên quan|tin liên quan)\b/i;

export function isBlockEl(n: Node): n is HTMLElement {
  return n.nodeType === 1 && BLOCK_TAGS.has((n as Element).tagName.toUpperCase());
}

export function isHidden(el: HTMLElement): boolean {
  if (el.hidden) return true;
  const cs = getComputedStyle(el);
  return cs.display === 'none' || cs.visibility === 'hidden';
}

/** Có bỏ qua khối này (và toàn bộ bên trong) khi đi tìm đoạn văn không */
export function shouldSkip(el: HTMLElement): boolean {
  const tag = el.tagName.toUpperCase();
  if (SKIP_BLOCK_TAGS.has(tag)) return true;
  if (tag === 'HEADER' && !el.closest('article')) return true;
  if (el.matches(EXCLUDE_SELECTOR)) return true;
  const sig = `${el.getAttribute('class') || ''} ${el.id || ''}`;
  if (sig.trim() && NEGATIVE_RE.test(sig)) return true;
  return isHidden(el);
}

export interface Measure {
  text: string;
  linkDensity: number;
}

function collect(node: Node, acc: { parts: string[]; link: number }, inLink: boolean) {
  if (node.nodeType === 3) {
    const t = node.nodeValue || '';
    acc.parts.push(t);
    if (inLink) acc.link += t.trim().length;
    return;
  }
  if (node.nodeType !== 1) return;
  const el = node as HTMLElement;
  const tag = el.tagName.toUpperCase();
  if (tag === 'BR') {
    acc.parts.push('\n');
    return;
  }
  if (SKIP_TEXT_TAGS.has(tag)) return;
  // Bỏ chú thích kiểu [1], [a], [cần dẫn nguồn]
  if (tag === 'SUP' && /^\s*\[[^\]]{0,25}\]\s*$/.test(el.textContent || '')) return;
  if (el.matches(EXCLUDE_SELECTOR)) return;
  const link = inLink || tag === 'A';
  el.childNodes.forEach((c) => collect(c, acc, link));
}

/** Đo chữ và tỉ lệ chữ nằm trong link của một nhóm node */
export function measure(nodes: Node[]): Measure {
  const acc = { parts: [] as string[], link: 0 };
  nodes.forEach((n) => collect(n, acc, false));
  const text = acc.parts.join('');
  const len = text.replace(/\s+/g, '').length;
  return { text, linkDensity: len ? acc.link / len : 0 };
}

export function cleanText(t: string): string {
  return t
    .replace(/\[\s*(?:\d+|[a-z]|citation needed|cần dẫn nguồn|sửa|edit|note\s*\d+)\s*\]/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Độ dài chữ trực tiếp (không tính các khối con) – dùng cho trang truyện dùng <br> */
export function directTextLen(el: HTMLElement): number {
  const inline = Array.from(el.childNodes).filter((c) => !isBlockEl(c));
  return cleanText(measure(inline).text).length;
}

// Ký tự chỉ tiếng Việt mới có
const VI_CHARS = /[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/gi;

export function detectLang(text: string): 'vi' | 'other' {
  const letters = (text.match(/\p{L}/gu) || []).length;
  if (!letters) return 'other';
  const vi = (text.match(VI_CHARS) || []).length;
  return vi / letters >= 0.05 ? 'vi' : 'other';
}

/**
 * Quét nhận diện ngôn ngữ trang thông minh:
 * Ưu tiên kiểm tra thẻ HTML -> quét bộ ký tự đặc trưng (Hán, Nhật, Hàn, Nga, Thái, Ả Rập, Việt...)
 * Phục vụ tự động chọn giọng Nam bản địa tương ứng của từng quốc gia.
 */
export function detectPageLanguage(sampleText?: string): string {
  // 1. Thử lấy từ thẻ <html lang="..."> hoặc meta
  const docLang = (document.documentElement.lang || document.querySelector('meta[http-equiv="content-language"]')?.getAttribute('content') || '').toLowerCase().trim();
  if (docLang) {
    const base = docLang.split('-')[0].split('_')[0];
    if (base && base.length >= 2) return base;
  }

  // 2. Thuật toán quét ký tự thông minh trên văn bản mẫu
  const sample = (sampleText || document.body.innerText || '').slice(0, 3000);
  if (!sample) return 'en';

  // Tiếng Việt
  const viMatches = (sample.match(VI_CHARS) || []).length;
  if (viMatches > 8) return 'vi';

  // Tiếng Nhật (Kana)
  if (/[\u3040-\u309F\u30A0-\u30FF]/.test(sample)) return 'ja';

  // Tiếng Hàn (Hangul)
  if (/[\uAC00-\uD7AF\u1100-\u11FF]/.test(sample)) return 'ko';

  // Tiếng Trung (Hanzi)
  if (/[\u4E00-\u9FFF]/.test(sample)) return 'zh';

  // Tiếng Thái
  if (/[\u0E00-\u0E7F]/.test(sample)) return 'th';

  // Tiếng Ả Rập
  if (/[\u0600-\u06FF]/.test(sample)) return 'ar';

  // Tiếng Nga (Cyrillic)
  if (/[\u0400-\u04FF]/.test(sample)) return 'ru';

  // Tiếng Pháp (accent + stop words)
  if (/[éèêëàâùûçœ]/i.test(sample) && /\b(le|la|les|un|une|des|et|du|au)\b/i.test(sample)) return 'fr';

  // Tiếng Tây Ban Nha
  if (/[áéíóúñ¿¡]/i.test(sample) && /\b(el|la|los|las|un|una|y|de|en)\b/i.test(sample)) return 'es';

  // Tiếng Đức
  if (/[äöüß]/i.test(sample) && /\b(der|die|das|und|ein|eine|mit)\b/i.test(sample)) return 'de';

  return 'en';
}

/**
 * Tự động nhận diện thể loại trang web:
 * - 'story': Truyện chữ, tiểu thuyết, truyện dịch, webnovel, lightnovel, kiếm hiệp, huyền huyễn.
 * - 'general': Báo chí, tin tức, bách khoa toàn thư Wikipedia, bài viết kiến thức, blog công nghệ.
 */
export function detectContentProfile(url?: string, title?: string, sampleText?: string): 'story' | 'general' {
  const currentUrl = (url || (typeof window !== 'undefined' ? window.location.href : '')).toLowerCase();
  const currentTitle = (title || (typeof document !== 'undefined' ? document.title : '')).toLowerCase();

  // 1. Nhận diện qua URL & Tên miền truyện phổ biến (Việt Nam, Trung Quốc, Quốc tế)
  const storyUrlPatterns = [
    /truyen/i, /novel/i, /fiction/i, /wattpad/i, /qidian/i, /faloo/i,
    /biquge/i, /69shu/i, /uukanshu/i, /syosetu/i, /kakuyomu/i, /ao3/i,
    /archiveofourown/i, /royalroad/i, /wuxiaworld/i, /chivi/i, /wikidich/i,
    /tangthuvien/i, /metruyenchu/i, /sangtacviet/i, /bachngocsach/i,
    /truyenfull/i, /truyencv/i, /dtruyen/i, /nettruyen/i, /readlightnovel/i,
    /novelfull/i, /lightnovelpub/i, /freewebnovel/i, /novelcool/i, /boxnovel/i,
    /\/(?:chuong|chap|chapter|hoi|tiet)[-_/]?\d+/i,
    /\/(?:story|novel|truyen|fiction|book)\//i
  ];
  if (storyUrlPatterns.some((p) => p.test(currentUrl))) {
    return 'story';
  }

  // 2. Nhận diện qua Tiêu đề trang (Chương / Chapter / Hồi / Tiết / Quyển / 第...章)
  const storyTitlePatterns = [
    /(?:chương|chapter|hồi|tiết|quyển)\s*\d+/i,
    /第\s*[\d一二三四五六七八九十百千万]+\s*[章回卷节]/i,
    /\b(?:novel|webnovel|light novel|truyện chữ|tiểu thuyết)\b/i
  ];
  if (storyTitlePatterns.some((p) => p.test(currentTitle))) {
    return 'story';
  }

  // 3. Nhận diện qua cấu trúc văn bản mẫu (mật độ hội thoại và phân đoạn)
  const sample = (sampleText || (typeof document !== 'undefined' ? document.body.innerText : '') || '').slice(0, 4000);
  if (sample) {
    // Đếm số lượng dấu thoại (ngoặc kép thoại hoặc ngoặc thoại Á Đông)
    const dialogueMatches = sample.match(/["“”「」『』]/g) || [];
    // Nếu có từ 10 cặp dấu thoại trở lên trong 4000 ký tự -> 95% là truyện
    if (dialogueMatches.length >= 10) {
      return 'story';
    }
  }

  return 'general';
}


