import { extractContent } from '../src/content/extractor';
import { splitTextIntoChunks } from '../src/content/splitter';
import {
  prepareBlockSpans,
  injectClauseTranslation,
  setupHoverListeners,
  setOnPlayCallback,
  highlightReading,
  clearHighlights,
  setHoverButtonLoading,
  setHoverButtonPlaying,
  toggleTranslationMode
} from '../src/content/injector';
import {
  initFloatingPlayer,
  updateFloatingPlayerState
} from '../src/content/floating_player';
import {
  startReaderSession,
  getReaderSessionStatus,
  seekReaderSession,
  closeReaderSession,
  getOrigAudioDataUri,
  getViAudioDataUri,
  switchSessionMode,
  fetchSettings
} from '../src/sidepanel/services/api';
import { AudioQueuePlayer, PlayableItem } from '../src/sidepanel/services/audio_player';

export default defineContentScript({
  matches: ['*://*/*'],
  main() {
    let currentSessionId: string | null = null;
    let pollInterval: any = null;
    const player = new AudioQueuePlayer();
    let sentenceMapping: { [sid: string]: number } = {};
    let sentencesTotal = 0;
    let isPipelineRunning = false;
    let cachedBlocks: any[] = [];
    let detectedLang = 'en';
    let detectedProfile: 'story' | 'general' = 'general';
    let currentMode: 'orig' | 'vi' = 'orig'; // Mặc định luôn là bản GỐC (zero-wait)

    // Audio Loader: Phân luồng độc lập tuyệt đối theo trạng thái yêu cầu ('orig' hoặc 'vi')
    player.audioLoader = async (index: number, reqMode: 'orig' | 'vi' = currentMode) => {
      if (!currentSessionId) return '';
      try {
        const uri = reqMode === 'vi'
          ? await getViAudioDataUri(currentSessionId, index)
          : await getOrigAudioDataUri(currentSessionId, index);
        setHoverButtonLoading(false);
        return uri;
      } catch (e) {
        console.warn(`[TTS] Lỗi tải audio (${reqMode}) câu ${index}:`, e);
        setHoverButtonLoading(false);
        return '';
      }
    };

    // Sự kiện khi chuyển câu đọc: Bôi vàng CHÍNH XÁC câu/vế câu đang đọc
    player.onTrackChange = (idx, item) => {
      setHoverButtonLoading(false);
      setHoverButtonPlaying(true);
      updateFloatingPlayerState({ currentIndex: idx });
      if (item.id) {
        highlightReading(item.id);
      }
      if (currentSessionId) {
        seekReaderSession(currentSessionId, idx).catch(() => {});
      }
    };

    player.onStateChange = (playing) => {
      setHoverButtonPlaying(playing);
      updateFloatingPlayerState({ isPlaying: playing });
      if (!playing) {
        clearHighlights();
      }
    };

    player.onFinish = () => {
      setHoverButtonPlaying(false);
      updateFloatingPlayerState({ isPlaying: false });
      clearHighlights();
    };

    // Khi người dùng hover vào 1 vế câu cụ thể hoặc bấm trực tiếp vào span câu
    setOnPlayCallback(async (sid: string) => {
      let targetIdx = sentenceMapping[sid];

      // Nếu phiên chưa nạp xong: khởi động ngay
      if (targetIdx === undefined) {
        if (!currentSessionId && cachedBlocks.length > 0) {
          setHoverButtonLoading(true);
          await startSessionWithBlocks(cachedBlocks);
          targetIdx = sentenceMapping[sid];
        }
      }

      if (targetIdx !== undefined) {
        const curIdx = player.getCurrentIndex();
        const isCurrentPlaying = (player as any).playing;

        // Bấm lại đúng vế câu đang đọc: tạm dừng
        if (curIdx === targetIdx && isCurrentPlaying) {
          player.pause();
          setHoverButtonPlaying(false);
          return;
        }

        // Chuyển sang đọc câu này: bật spinner và tô vàng câu đích
        setHoverButtonLoading(true);
        highlightReading(sid);
        player.seek(targetIdx);
        if (currentSessionId) {
          seekReaderSession(currentSessionId, targetIdx).catch(() => {});
        }
      }
    });

    // Khởi tạo thanh điều khiển nổi (Floating Player)
    initFloatingPlayer({
      onTogglePlay: () => {
        const isPlaying = (player as any).playing;
        if (isPlaying) {
          player.pause();
          setHoverButtonPlaying(false);
        } else {
          player.play();
          setHoverButtonPlaying(true);
        }
      },
      onPrev: () => {
        player.prev();
        const curIdx = player.getCurrentIndex();
        if (currentSessionId) seekReaderSession(currentSessionId, curIdx).catch(() => {});
      },
      onNext: () => {
        player.next();
        const curIdx = player.getCurrentIndex();
        if (currentSessionId) seekReaderSession(currentSessionId, curIdx).catch(() => {});
      },
      onOpenSettings: () => {
        chrome.runtime.sendMessage({ action: 'OPEN_SETTINGS' }).catch(() => {});
      },
      onToggleMode: async (toMode: 'orig' | 'vi') => {
        currentMode = toMode;
        const isPlaying = (player as any).playing;

        // 1. Chuyển đổi mượt mà toàn bộ nội dung văn bản trên DOM về đúng trạng thái vừa chọn ('orig' hoặc 'vi')
        toggleTranslationMode(toMode === 'vi');

        // 2. NGAY LẬP TỨC dọn sạch slot phát của trạng thái cũ, vô hiệu hóa mọi preload đang bay của trạng thái cũ,
        //    đưa con trỏ MP3 về câu đầu tiên (Index 0 / s-0) của trạng thái mới và tái sử dụng cache RAM nếu đã có
        player.switchModeAndResetToStart(toMode, isPlaying);

        // 3. Chuyển vết bôi vàng về câu đầu tiên (s-0) và cuộn mượt về đầu bài
        clearHighlights();
        highlightReading('s-0');

        // 4. Cập nhật thanh điều khiển nổi về câu số 1 của trạng thái mới
        updateFloatingPlayerState({
          currentMode: toMode,
          currentIndex: 0,
          totalSentences: sentencesTotal,
          isPlaying: isPlaying
        });

        // 5. Đồng bộ trạng thái và vị trí câu 0 với Backend + tiếp tục polling tiến độ
        if (currentSessionId) {
          await switchSessionMode(currentSessionId, toMode).catch(() => {});
          seekReaderSession(currentSessionId, 0).catch(() => {});
          startPolling(currentSessionId);
        }
      },
      // BẬT / TẮT đọc trang web này theo yêu cầu người dùng (Mặc định là TẮT để không spam API)
      onTogglePower: async (enabled: boolean) => {
        if (enabled) {
          // Người dùng bấm BẬT: Trích xuất nội dung và khởi động đọc
          await activateReaderForCurrentPage();
        } else {
          // Người dùng bấm TẮT: Dừng audio, đóng phiên ngầm, xóa highlights
          deactivateReaderForCurrentPage();
        }
      },
      // Xóa sạch toàn bộ cache JSON và dừng chương trình
      onClearCache: async () => {
        deactivateReaderForCurrentPage();
        try {
          await fetch('http://127.0.0.1:8000/api/v1/session/stop-and-clear', { method: 'POST' });
          alert('🗑️ Đã đánh dấu DỪNG và xóa sạch 100% cache JSON theo link web!');
        } catch (e) {
          console.warn('[TTS] Lỗi xóa cache:', e);
        }
      }
    }, detectedLang, false);

    // KIỂM TRA TRANG ĐẦU TIÊN:
    // Trang đầu tiên người dùng mở sau khi bật trình duyệt sẽ TỰ ĐỘNG BẬT và chuẩn bị trước
    // Các trang mở sau sẽ ở trạng thái chờ (Standby), có nút Bật/Tắt để tiết kiệm API
    try {
      chrome.runtime.sendMessage({ action: 'CLAIM_PRIMARY_AUTO_START' }, (res) => {
        if (res && res.isPrimary) {
          console.log('[TTS] 🎯 Trang đầu tiên được phát hiện -> Tự động kích hoạt luồng đọc & chuẩn bị trước!');
          setTimeout(() => {
            activateReaderForCurrentPage();
          }, 300);
        }
      });
    } catch {}

    async function activateReaderForCurrentPage() {
      try {
        const result = extractContent();
        if (result && result.blocks && result.blocks.length > 0) {
          cachedBlocks = result.blocks;
          detectedLang = result.detectedLang || 'en';
          detectedProfile = result.detectedProfile || 'general';

          updateFloatingPlayerState({
            isPowerOn: true,
            langCode: detectedLang,
            currentMode: 'orig',
            profile: detectedProfile
          });

          setupHoverListeners();
          await startSessionWithBlocks(result.blocks);
        }
      } catch (e) {
        console.warn('[TTS] Lỗi trích xuất trang:', e);
      }
    }

    function deactivateReaderForCurrentPage() {
      player.pause();
      setHoverButtonPlaying(false);
      if (currentSessionId) {
        closeReaderSession(currentSessionId).catch(() => {});
        currentSessionId = null;
      }
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
      clearHighlights();
      isPipelineRunning = false;
      toggleTranslationMode(false);
      updateFloatingPlayerState({
        isPowerOn: false,
        isPlaying: false
      });
    }

    async function startSessionWithBlocks(blocks: any[]) {
      if (isPipelineRunning) return;
      isPipelineRunning = true;

      let conf: any = null;
      try {
        conf = await fetchSettings();
      } catch (e) {
        console.warn('[TTS] Không thể kết nối Backend Settings:', e);
      }

      // ĐỒNG BỘ 100% GIỮA HIỂN THỊ DOM VÀ TTS:
      // Chia nhỏ từng block thành các vế câu (<= 120 ký tự), gắn thẻ span có data-tts-sid
      const sessionChunks: any[] = [];
      let globalIdx = 0;

      blocks.forEach((b) => {
        const clauses = splitTextIntoChunks(b.text, 120);
        const blockChunks: { sid: string; text: string }[] = [];

        clauses.forEach((cText) => {
          const sid = `s-${globalIdx++}`;
          blockChunks.push({ sid, text: cText });
          sessionChunks.push({
            text: cText,
            xid: b.xid,
            sid: sid,
            lang: b.lang
          });
        });

        // Bọc DOM của block này thành các span vế câu có data-tts-sid
        prepareBlockSpans(b.xid, blockChunks);
      });

      const sid = `session_web_${Date.now()}`;
      currentSessionId = sid;

      updateFloatingPlayerState({ isProcessing: true });

      try {
        const res = await startReaderSession({
          session_id: sid,
          blocks: sessionChunks,
          profile: detectedProfile,
          voice_id: conf?.selected_voice || 'BV074_streaming',
          lang: detectedLang,
          page_url: window.location.href,
          mode: currentMode,
          speed: 1.0,
          model: conf?.gemini_model
        });

        sentencesTotal = res.total_sentences || 0;
        sentenceMapping = {};
        const playables: PlayableItem[] = [];

        // Ánh xạ chính xác sid -> index câu
        if (res.sentences && res.sentences.length > 0) {
          res.sentences.forEach((s: any) => {
            const sentenceSid = s.sid || `s-${s.index}`;
            sentenceMapping[sentenceSid] = s.index;

            // Nếu câu đã có bản dịch tiếng Việt hợp lệ, nạp ngay vào DOM
            if (s.translated && s.translated.trim() !== s.original.trim()) {
              injectClauseTranslation(sentenceSid, s.translated);
            }

            playables.push({
              id: sentenceSid,
              xid: s.xid,
              text: s.original,
              origAudioBlobUrl: undefined,
              viAudioBlobUrl: undefined
            });
          });
        }

        // Đảm bảo nội dung DOM hiển thị khớp 100% với trạng thái hiện tại
        toggleTranslationMode(currentMode === 'vi');

        const readyCount = currentMode === 'vi'
          ? (res.status_data?.vi_ready_count || 0)
          : (res.status_data?.orig_ready_count || 1);

        updateFloatingPlayerState({
          currentIndex: 0,
          totalSentences: sentencesTotal,
          readyCount: readyCount,
          isProcessing: true,
          currentMode: currentMode,
          langCode: detectedLang
        });

        player.setQueue(playables, 0, currentMode);

        // Bắt đầu vòng lặp đồng bộ tiến độ
        startPolling(sid);
      } catch (err) {
        console.warn('[TTS] Lỗi khởi động phiên đọc:', err);
        updateFloatingPlayerState({ isProcessing: false });
      } finally {
        isPipelineRunning = false;
      }
    }

    function startPolling(sid: string) {
      if (pollInterval) clearInterval(pollInterval);

      pollInterval = setInterval(async () => {
        if (currentSessionId !== sid) return;
        try {
          const data = await getReaderSessionStatus(sid);
          if (data) {
            const readyCount = currentMode === 'vi'
              ? data.vi_ready_count
              : data.orig_ready_count;

            // Polling chỉ được dừng khi:
            // 1. Toàn bộ bài đã dịch xong 100% (translated_count >= total_sentences)
            // 2. VÀ toàn bộ audio của chế độ hiện tại đã sẵn sàng 100%
            const isTranslationDone = (data.translated_count || 0) >= (data.total_sentences || 0);
            const isAudioDone = currentMode === 'vi' ? data.is_vi_complete : data.is_complete;
            const isAllDone = isTranslationDone && isAudioDone;

            updateFloatingPlayerState({
              currentIndex: player.getCurrentIndex(),
              totalSentences: data.total_sentences,
              readyCount: readyCount,
              isProcessing: !isAllDone
            });

            // Bơm bản dịch chuẩn xác cho từng vế câu data-tts-sid vào DOM ngay khi có
            if (data.translated_items && data.translated_items.length > 0) {
              data.translated_items.forEach((item: any) => {
                if (item.sid && item.translated) {
                  injectClauseTranslation(item.sid, item.translated);
                }
              });
            }

            if (isAllDone && pollInterval) {
              clearInterval(pollInterval);
              pollInterval = null;
            }
          }
        } catch {}
      }, 1200);
    }

    // Lắng nghe lệnh từ Popup Settings khi người dùng đổi giọng đọc mới
    chrome.runtime.onMessage.addListener(async (msg, _sender, sendResponse) => {
      if (msg.action === 'SETTINGS_UPDATED') {
        try {
          const wasPlaying = (player as any).playing;

          // 1. Dừng player, xóa sạch toàn bộ URL audio cũ trong RAM, reset về câu số 1
          player.resetToStart(false);
          clearHighlights();
          highlightReading('s-0');
          updateFloatingPlayerState({
            currentIndex: 0,
            isPlaying: false
          });

          // 2. Đóng phiên cũ ngầm trên Backend
          if (currentSessionId) {
            await closeReaderSession(currentSessionId).catch(() => {});
            currentSessionId = null;
          }
          isPipelineRunning = false;

          // 3. Khởi tạo lại phiên mới từ câu số 1 theo đúng giọng mới vừa chọn
          if (cachedBlocks.length > 0) {
            await startSessionWithBlocks(cachedBlocks);
            if (wasPlaying) {
              player.play();
            }
          }
        } catch (e) {
          console.warn('[TTS] Lỗi áp dụng cài đặt mới:', e);
        }
        sendResponse({ status: 'ok' });
      }
    });

    window.addEventListener('beforeunload', () => {
      if (currentSessionId) {
        closeReaderSession(currentSessionId);
      }
      if (pollInterval) clearInterval(pollInterval);
      player.pause();
    });
  }
});
