// In-place text replacement & Clause-Level Highlighting (Đọc câu nào bôi vàng đúng câu đó)
import { anchorElement, anchors } from './extractor/registry';

const STYLE_ID = 'tts-native-style';

let isShowingTranslation = false; // Mặc định ở chế độ GỐC (Original)
let currentActiveSid: string | null = null;
let hoverButtonEl: HTMLButtonElement | null = null;
let hoveredSid: string | null = null;
let isHoverLoading = false;
let isHoverPlaying = false;
const translatedClauseCache = new Map<string, string>();

export type OnPlaySidCallback = (sid: string) => void;
let onPlayCallback: OnPlaySidCallback | null = null;

export function setOnPlayCallback(cb: OnPlaySidCallback) {
  onPlayCallback = cb;
}

export function setHoverButtonLoading(loading: boolean) {
  isHoverLoading = loading;
  if (!hoverButtonEl) return;
  if (loading) {
    hoverButtonEl.innerHTML = '<div class="tts-spinner"></div>';
    hoverButtonEl.style.backgroundColor = '#d97706';
  } else {
    hoverButtonEl.innerHTML = isHoverPlaying ? '⏸' : '▶';
    hoverButtonEl.style.backgroundColor = isHoverPlaying ? '#16a34a' : '#2563eb';
  }
}

export function setHoverButtonPlaying(playing: boolean) {
  isHoverPlaying = playing;
  if (!hoverButtonEl || isHoverLoading) return;
  hoverButtonEl.innerHTML = playing ? '⏸' : '▶';
  hoverButtonEl.style.backgroundColor = playing ? '#16a34a' : '#2563eb';
}

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `
    @keyframes tts-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .tts-spinner {
      width: 12px;
      height: 12px;
      border: 2px solid rgba(255, 255, 255, 0.4);
      border-top-color: #ffffff;
      border-radius: 50%;
      animation: tts-spin 0.7s linear infinite;
    }
    .tts-clause {
      display: inline;
      border-radius: 4px;
      padding: 1px 2px;
      transition: background-color 0.2s ease, box-shadow 0.2s ease;
    }
    .tts-clause:hover {
      background-color: rgba(254, 240, 138, 0.45);
      cursor: pointer;
    }
    [data-tts-active="true"] {
      background-color: #fef08a !important; /* Vàng chuẩn sáng */
      color: #0f172a !important;
      border-radius: 4px;
      box-shadow: 0 0 0 2px #eab308 !important;
      transition: background-color 0.2s ease;
    }
    .tts-hover-play-btn {
      position: absolute;
      display: none;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background-color: #2563eb;
      color: #ffffff;
      border: 2px solid #ffffff;
      box-shadow: 0 3px 10px rgba(0,0,0,0.35);
      cursor: pointer;
      z-index: 2147483640;
      font-size: 12px;
      line-height: 1;
      padding: 0;
      transition: transform 0.15s ease, background-color 0.15s ease;
    }
    .tts-hover-play-btn:hover {
      transform: scale(1.15);
    }
  `;
  (document.head || document.documentElement).appendChild(s);
}

function ensureHoverButton() {
  if (hoverButtonEl && document.body.contains(hoverButtonEl)) return;
  hoverButtonEl = document.createElement('button');
  hoverButtonEl.className = 'tts-hover-play-btn';
  hoverButtonEl.title = 'Bấm để nghe đúng câu/vế này ngay';
  hoverButtonEl.innerHTML = '▶';
  document.body.appendChild(hoverButtonEl);

  hoverButtonEl.addEventListener('click', (e) => {
    e.stopPropagation();
    if (hoveredSid && onPlayCallback) {
      onPlayCallback(hoveredSid);
    }
  });

  hoverButtonEl.addEventListener('mouseenter', () => {
    if (hoverButtonEl) hoverButtonEl.style.display = 'flex';
  });

  hoverButtonEl.addEventListener('mouseleave', () => {
    if (hoverButtonEl) hoverButtonEl.style.display = 'none';
  });
}

/**
 * Gắn sự kiện hover và click lên từng span câu cụ thể
 */
function bindClauseEvents(container: HTMLElement) {
  container.querySelectorAll<HTMLElement>('.tts-clause').forEach((span) => {
    const sid = span.getAttribute('data-tts-sid');
    if (!sid) return;

    span.addEventListener('click', (e) => {
      e.stopPropagation();
      if (onPlayCallback) onPlayCallback(sid);
    });

    span.addEventListener('mouseenter', () => {
      hoveredSid = sid;
      if (!hoverButtonEl) return;

      const rect = span.getBoundingClientRect();
      const scrollX = window.scrollX || window.pageXOffset;
      const scrollY = window.scrollY || window.pageYOffset;

      const btnLeft = Math.max(6, rect.left + scrollX - 30);
      const btnTop = rect.top + scrollY + Math.max(0, (rect.height - 26) / 2);

      hoverButtonEl.style.left = `${btnLeft}px`;
      hoverButtonEl.style.top = `${btnTop}px`;
      hoverButtonEl.style.display = 'flex';

      const isCurrentActive = currentActiveSid === sid;
      setHoverButtonPlaying(isCurrentActive && isHoverPlaying);
    });

    span.addEventListener('mouseleave', (e) => {
      const related = e.relatedTarget as Node | null;
      if (related !== hoverButtonEl && !hoverButtonEl?.contains(related)) {
        if (hoverButtonEl) hoverButtonEl.style.display = 'none';
      }
    });
  });
}

/**
 * Chia nhỏ đoạn văn (block) thành các span vế câu có data-tts-sid.
 * Giữ nguyên 100% bố cục và cấu trúc DOM gốc trên mọi website (kể cả web truyện dùng <br> như 69shuba, biquge...).
 */
export function prepareBlockSpans(xid: string, chunks: { sid: string; text: string }[]) {
  const anchor = anchors.get(xid);
  if (!anchor) return;
  ensureStyle();

  // Bọc từng chunk câu vào thẻ span có data-tts-sid
  const spanHtml = chunks
    .map(
      (c) =>
        `<span class="tts-clause" data-tts-sid="${c.sid}" data-tts-orig="${encodeURIComponent(c.text)}">${c.text}</span>`
    )
    .join(' ');

  if (anchor.kind === 'segment') {
    // Với đoạn ảo phân cách bởi <br> (như các trang truyện 69shuba, biquge, syosetu...):
    // TUYỆT ĐỐI KHÔNG dùng parent.innerHTML = spanHtml vì sẽ xóa sạch toàn bộ các đoạn khác trong container!
    // Ta chỉ thay thế chính xác các text node của segment này bằng một thẻ span inline.
    const nodes = anchor.nodes.filter((n) => n.isConnected);
    if (!nodes.length) return;

    const firstNode = nodes[0];
    const parent = firstNode.parentElement;
    if (!parent) return;

    const wrapper = document.createElement('span');
    wrapper.className = 'tts-segment-wrapper';
    wrapper.innerHTML = spanHtml;

    parent.insertBefore(wrapper, firstNode);

    // Xóa các node cũ của đoạn này mà giữ nguyên tất cả thẻ <br> và các đoạn văn khác
    nodes.forEach((n) => {
      if (n.parentNode) {
        n.parentNode.removeChild(n);
      }
    });

    bindClauseEvents(wrapper);
  } else if (anchor.kind === 'element') {
    // Với element độc lập (như <p>, <h2>, <h3>...):
    const el = anchor.el;
    if (!el || !el.isConnected || el.getAttribute('data-tts-spans-ready')) return;

    el.setAttribute('data-tts-spans-ready', 'true');
    if (!el.hasAttribute('data-tts-orig-html')) {
      el.setAttribute('data-tts-orig-html', el.innerHTML);
      el.setAttribute('data-tts-orig-text', el.textContent || '');
    }

    el.innerHTML = spanHtml;
    bindClauseEvents(el);
  }
}

/**
 * Gắn hover cho toàn bộ anchors
 */
export function setupHoverListeners() {
  ensureStyle();
  ensureHoverButton();
}

/**
 * Bơm bản dịch cho từng câu/vế câu cụ thể vào DOM
 */
export function injectClauseTranslation(sid: string, translatedText: string): void {
  ensureStyle();
  // Bóc tách tiền tố số nếu có
  const clean = (translatedText || '').replace(/^\d+\s*\|*\|*\s*/, '').trim();
  if (!clean) return;

  translatedClauseCache.set(sid, clean);

  const span = document.querySelector<HTMLElement>(`[data-tts-sid="${sid}"]`);
  if (!span) return;

  span.setAttribute('data-tts-trans', clean);
  if (isShowingTranslation) {
    span.textContent = clean;
  }
}

/**
 * Chuyển đổi qua lại giữa bản dịch và bản gốc tức thì (1-Click Switch)
 */
export function toggleTranslationMode(showTranslated: boolean): void {
  isShowingTranslation = showTranslated;

  document.querySelectorAll<HTMLElement>('.tts-clause').forEach((span) => {
    const sid = span.getAttribute('data-tts-sid') || '';
    if (showTranslated) {
      const trans = span.getAttribute('data-tts-trans') || translatedClauseCache.get(sid);
      if (trans) {
        span.setAttribute('data-tts-trans', trans);
        span.textContent = trans;
      }
    } else {
      const origEncoded = span.getAttribute('data-tts-orig');
      if (origEncoded) {
        try {
          span.textContent = decodeURIComponent(origEncoded);
        } catch {
          span.textContent = origEncoded;
        }
      }
    }
  });
}

export function isCurrentlyShowingTranslation(): boolean {
  return isShowingTranslation;
}

/**
 * Tô sáng vàng câu/vế câu đang đọc và cuộn mượt mà vào tầm nhìn
 */
export function highlightReading(sid: string): void {
  ensureStyle();

  // Bỏ active cũ
  if (currentActiveSid) {
    const oldSpan = document.querySelector<HTMLElement>(`[data-tts-sid="${currentActiveSid}"]`);
    if (oldSpan) oldSpan.removeAttribute('data-tts-active');
  }

  currentActiveSid = sid;
  const curSpan = document.querySelector<HTMLElement>(`[data-tts-sid="${sid}"]`);
  if (curSpan) {
    curSpan.setAttribute('data-tts-active', 'true');
    curSpan.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

export function clearHighlights(): void {
  if (currentActiveSid) {
    const span = document.querySelector<HTMLElement>(`[data-tts-sid="${currentActiveSid}"]`);
    if (span) span.removeAttribute('data-tts-active');
    currentActiveSid = null;
  }
}
