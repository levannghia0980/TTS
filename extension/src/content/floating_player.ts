// Floating Mini Player (Thanh điều khiển nổi thông minh trên trang web)
import { toggleTranslationMode, isCurrentlyShowingTranslation } from './injector';

export interface FloatingPlayerCallbacks {
  onTogglePlay: () => void;
  onPrev: () => void;
  onNext: () => void;
  onOpenSettings: () => void;
  onToggleMode?: (toMode: 'orig' | 'vi') => void;
  onTogglePower?: (enabled: boolean) => void;
  onClearCache?: () => void;
}

let containerEl: HTMLDivElement | null = null;
let playBtnEl: HTMLButtonElement | null = null;
let counterEl: HTMLSpanElement | null = null;
let langToggleBtnEl: HTMLButtonElement | null = null;
let statusDotEl: HTMLSpanElement | null = null;
let readyStatusEl: HTMLSpanElement | null = null;
let standbyBoxEl: HTMLElement | null = null;
let mainControlsEl: HTMLElement | null = null;

let isPlayingState = false;
let callbacks: FloatingPlayerCallbacks | null = null;
let isCollapsed = false;
let isPowerOnState = false; // Mặc định TẮT khi mở web mới để tránh spam request API
let currentModeState: 'orig' | 'vi' = 'orig';
let pageLangCode = 'EN';

export function initFloatingPlayer(
  cb: FloatingPlayerCallbacks,
  initialLang: string = 'en',
  initialPowerOn: boolean = false
) {
  callbacks = cb;
  pageLangCode = (initialLang || 'en').toUpperCase();
  isPowerOnState = initialPowerOn;

  if (containerEl && document.body.contains(containerEl)) return;

  containerEl = document.createElement('div');
  containerEl.id = 'tts-floating-pill';
  containerEl.innerHTML = `
    <style>
      #tts-floating-pill {
        position: fixed;
        bottom: 22px;
        right: 24px;
        z-index: 2147483647;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: rgba(15, 23, 42, 0.94);
        backdrop-filter: blur(14px);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 30px;
        box-shadow: 0 10px 32px rgba(0, 0, 0, 0.4);
        color: #ffffff;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 13px;
        user-select: none;
        transition: transform 0.2s ease, opacity 0.2s ease, width 0.2s ease;
      }
      #tts-floating-pill:hover {
        transform: translateY(-2px);
        box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5);
      }
      .tts-pill-standby-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        background: #2563eb;
        color: #ffffff;
        border: none;
        border-radius: 20px;
        padding: 6px 14px;
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
        transition: all 0.2s ease;
      }
      .tts-pill-standby-btn:hover {
        background: #1d4ed8;
        transform: scale(1.05);
      }
      .tts-pill-btn {
        background: transparent;
        border: none;
        color: #ffffff;
        cursor: pointer;
        padding: 5px 7px;
        border-radius: 8px;
        font-size: 13px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.15s ease, transform 0.1s ease;
      }
      .tts-pill-btn:hover {
        background: rgba(255, 255, 255, 0.18);
        transform: scale(1.1);
      }
      .tts-pill-power-off-btn {
        background: rgba(239, 68, 68, 0.2);
        border: 1px solid rgba(239, 68, 68, 0.6);
        color: #fca5a5;
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .tts-pill-power-off-btn:hover {
        background: #ef4444;
        color: #ffffff;
      }
      .tts-pill-play-btn {
        width: 34px;
        height: 34px;
        border-radius: 50%;
        background: #2563eb;
        color: #ffffff;
        border: none;
        cursor: pointer;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 10px rgba(37, 99, 235, 0.55);
        transition: transform 0.15s ease, background-color 0.15s ease;
      }
      .tts-pill-play-btn:hover {
        background: #1d4ed8;
        transform: scale(1.1);
      }
      .tts-pill-lang-btn {
        font-size: 11px;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 12px;
        background: rgba(37, 99, 235, 0.25);
        border: 1px solid rgba(59, 130, 246, 0.5);
        color: #fcd34d;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .tts-pill-lang-btn:hover {
        background: rgba(37, 99, 235, 0.45);
        color: #ffffff;
      }
      .tts-pill-counter {
        font-size: 12px;
        font-weight: 600;
        color: #cbd5e1;
        min-width: 44px;
        text-align: center;
      }
      .tts-pill-ready {
        font-size: 11px;
        color: #94a3b8;
        padding: 0 4px;
        white-space: nowrap;
      }
      .tts-pill-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #22c55e;
        display: inline-block;
      }
      .tts-pill-dot.pulsing {
        animation: tts-pulse 1.2s infinite;
        background: #3b82f6;
      }
      @keyframes tts-pulse {
        0% { transform: scale(0.9); opacity: 0.7; }
        50% { transform: scale(1.3); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.7; }
      }
      .tts-pill-profile {
        font-size: 11px;
        color: #cbd5e1;
        padding: 2px 6px;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.1);
        white-space: nowrap;
      }
      .tts-pill-collapse-btn {
        font-size: 12px;
        color: #94a3b8;
        cursor: pointer;
        padding: 2px 4px;
        border: none;
        background: none;
        border-radius: 4px;
      }
      .tts-pill-collapse-btn:hover {
        color: #ffffff;
      }
      .tts-pill-content {
        display: flex;
        align-items: center;
        gap: 8px;
      }
    </style>

    <!-- 1. Trạng thái CHỜ (TẮT mặc định khi mở tab mới) -->
    <div id="tts-pill-standby" style="display: ${isPowerOnState ? 'none' : 'flex'};">
      <button class="tts-pill-standby-btn" id="tts-pill-start-btn" title="Bấm để BẬT đọc và dịch trang web này">
        🎙️ Bật đọc trang này
      </button>
    </div>

    <!-- 2. Trạng thái HOẠT ĐỘNG (Đầy đủ bảng điều khiển) -->
    <div class="tts-pill-content" id="tts-pill-main-controls" style="display: ${isPowerOnState ? 'flex' : 'none'};">
      <!-- Nút Tắt nhanh để dừng toàn bộ request API của trang này -->
      <button class="tts-pill-power-off-btn" id="tts-pill-power-off" title="Tắt đọc trang này (Ngừng API và giải phóng)">
        🔴 Tắt
      </button>

      <span class="tts-pill-dot" id="tts-pill-dot" title="Sẵn sàng"></span>
      
      <!-- Nút Lùi 1 câu -->
      <button class="tts-pill-btn" id="tts-pill-prev" title="Lùi 1 câu (⏮️)">⏮️</button>
      
      <!-- Nút Play / Pause chính -->
      <button class="tts-pill-play-btn" id="tts-pill-play" title="Phát / Dừng">▶</button>
      
      <!-- Nút Tiến 1 câu -->
      <button class="tts-pill-btn" id="tts-pill-next" title="Tiến 1 câu (⏭️)">⏭️</button>
      
      <!-- Chỉ số câu hiện tại / Tổng số -->
      <span class="tts-pill-counter" id="tts-pill-counter" title="Câu đang đọc / Tổng số câu">0 / 0</span>

      <!-- Trạng thái audio sẵn sàng ngầm -->
      <span class="tts-pill-ready" id="tts-pill-ready" title="Tiến độ chuẩn bị âm thanh ngầm"></span>
      
      <!-- Nút chuyển nhanh Gốc ↔ Dịch -->
      <button class="tts-pill-lang-btn" id="tts-pill-lang" title="Bấm để chuyển giữa Giọng Nam Bản Gốc và Bản Dịch Tiếng Việt">
        🎙️ Gốc (${pageLangCode})
      </button>

      <!-- Badge nhận diện thể loại nội dung -->
      <span class="tts-pill-profile" id="tts-pill-profile" title="Thể loại nội dung dịch"></span>

      <!-- Nút Dừng & Xóa sạch Cache JSON -->
      <button class="tts-pill-btn" id="tts-pill-clear" title="Dừng đọc & Xóa sạch 100% cache JSON theo link web">🗑️</button>

      <!-- Nút Cài đặt -->
      <button class="tts-pill-btn" id="tts-pill-settings" title="Cài đặt giọng đọc & tốc độ">⚙️</button>

      <!-- Nút thu gọn -->
      <button class="tts-pill-collapse-btn" id="tts-pill-collapse" title="Thu nhỏ / Mở rộng">−</button>
    </div>
  `;

  document.body.appendChild(containerEl);

  standbyBoxEl = containerEl.querySelector('#tts-pill-standby');
  mainControlsEl = containerEl.querySelector('#tts-pill-main-controls');
  playBtnEl = containerEl.querySelector('#tts-pill-play');
  counterEl = containerEl.querySelector('#tts-pill-counter');
  readyStatusEl = containerEl.querySelector('#tts-pill-ready');
  langToggleBtnEl = containerEl.querySelector('#tts-pill-lang');
  statusDotEl = containerEl.querySelector('#tts-pill-dot');

  // Sự kiện bấm nút BẬT ĐỌC (từ trạng thái chờ)
  containerEl.querySelector('#tts-pill-start-btn')?.addEventListener('click', () => {
    setPowerUI(true);
    callbacks?.onTogglePower?.(true);
  });

  // Sự kiện bấm nút TẮT ĐỌC (về trạng thái chờ)
  containerEl.querySelector('#tts-pill-power-off')?.addEventListener('click', () => {
    setPowerUI(false);
    callbacks?.onTogglePower?.(false);
  });

  // Sự kiện bấm Xóa Cache JSON
  containerEl.querySelector('#tts-pill-clear')?.addEventListener('click', () => {
    if (confirm('Bạn có chắc muốn DỪNG phiên đọc và XÓA SẠCH toàn bộ cache JSON tạm thời?')) {
      setPowerUI(false);
      callbacks?.onClearCache?.();
    }
  });

  playBtnEl?.addEventListener('click', () => callbacks?.onTogglePlay());
  containerEl.querySelector('#tts-pill-prev')?.addEventListener('click', () => callbacks?.onPrev());
  containerEl.querySelector('#tts-pill-next')?.addEventListener('click', () => callbacks?.onNext());
  containerEl.querySelector('#tts-pill-settings')?.addEventListener('click', () => callbacks?.onOpenSettings());

  const collapseBtn = containerEl.querySelector('#tts-pill-collapse');
  collapseBtn?.addEventListener('click', () => {
    isCollapsed = !isCollapsed;
    if (mainControlsEl) {
      Array.from(mainControlsEl.children).forEach((child: any) => {
        if (child !== collapseBtn && child.id !== 'tts-pill-play') {
          child.style.display = isCollapsed ? 'none' : '';
        }
      });
    }
    if (collapseBtn) {
      collapseBtn.textContent = isCollapsed ? '➕' : '−';
    }
  });

  langToggleBtnEl?.addEventListener('click', () => {
    const nextMode = currentModeState === 'orig' ? 'vi' : 'orig';
    currentModeState = nextMode;

    const showTranslated = nextMode === 'vi';
    toggleTranslationMode(showTranslated);

    if (langToggleBtnEl) {
      if (nextMode === 'vi') {
        langToggleBtnEl.textContent = '🇻🇳 Dịch (VI)';
        langToggleBtnEl.style.color = '#93c5fd';
      } else {
        langToggleBtnEl.textContent = `🎙️ Gốc (${pageLangCode})`;
        langToggleBtnEl.style.color = '#fcd34d';
      }
    }

    callbacks?.onToggleMode?.(nextMode);
  });
}

function setPowerUI(on: boolean) {
  isPowerOnState = on;
  if (standbyBoxEl) standbyBoxEl.style.display = on ? 'none' : 'flex';
  if (mainControlsEl) mainControlsEl.style.display = on ? 'flex' : 'none';
}

export function updateFloatingPlayerState(params: {
  isPowerOn?: boolean;
  isPlaying?: boolean;
  currentIndex?: number;
  totalSentences?: number;
  readyCount?: number;
  isProcessing?: boolean;
  currentMode?: 'orig' | 'vi';
  langCode?: string;
  profile?: 'story' | 'general';
}) {
  if (params.isPowerOn !== undefined) {
    setPowerUI(params.isPowerOn);
  }

  if (params.profile !== undefined && containerEl) {
    const profileEl = containerEl.querySelector('#tts-pill-profile');
    if (profileEl) {
      if (params.profile === 'story') {
        profileEl.textContent = '📖 Truyện';
        profileEl.setAttribute('title', 'Tự động áp dụng Prompt Truyện (Văn phong mượt mà, xưng hô hắn/nàng, số đổi thành chữ)');
      } else {
        profileEl.textContent = '📰 Tin tức';
        profileEl.setAttribute('title', 'Tự động áp dụng Prompt Báo chí (Chuẩn mực, lọc sạch số chú thích)');
      }
    }
  }

  if (params.langCode) {
    pageLangCode = params.langCode.toUpperCase();
    if (langToggleBtnEl && currentModeState === 'orig') {
      langToggleBtnEl.textContent = `🎙️ Gốc (${pageLangCode})`;
    }
  }

  if (params.currentMode !== undefined) {
    currentModeState = params.currentMode;
    if (langToggleBtnEl) {
      if (currentModeState === 'vi') {
        langToggleBtnEl.textContent = '🇻🇳 Dịch (VI)';
        langToggleBtnEl.style.color = '#93c5fd';
      } else {
        langToggleBtnEl.textContent = `🎙️ Gốc (${pageLangCode})`;
        langToggleBtnEl.style.color = '#fcd34d';
      }
    }
  }

  if (params.isPlaying !== undefined) {
    isPlayingState = params.isPlaying;
    if (playBtnEl) {
      playBtnEl.innerHTML = isPlayingState ? '⏸' : '▶';
    }
  }

  if (params.currentIndex !== undefined && params.totalSentences !== undefined) {
    if (counterEl) {
      counterEl.textContent = params.totalSentences > 0 
        ? `${params.currentIndex + 1} / ${params.totalSentences}` 
        : '0 / 0';
    }
  }

  if (params.readyCount !== undefined && params.totalSentences !== undefined && readyStatusEl) {
    if (params.readyCount < params.totalSentences) {
      readyStatusEl.textContent = `(Sẵn sàng: ${params.readyCount}/${params.totalSentences})`;
    } else {
      readyStatusEl.textContent = '';
    }
  }

  if (params.isProcessing !== undefined && statusDotEl) {
    if (params.isProcessing) {
      statusDotEl.className = 'tts-pill-dot pulsing';
      statusDotEl.title = 'Đang chuẩn bị âm thanh ngầm...';
    } else {
      statusDotEl.className = 'tts-pill-dot';
      statusDotEl.title = 'Tất cả âm thanh đã sẵn sàng 100%';
    }
  }
}

export function hideFloatingPlayer() {
  if (containerEl) containerEl.style.display = 'none';
}

export function showFloatingPlayer() {
  if (containerEl) containerEl.style.display = 'flex';
}
