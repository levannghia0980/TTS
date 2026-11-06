import React, { useState, useEffect, useRef } from 'react';
import { Settings, Voice } from '../../types';
import {
  fetchSettings,
  fetchVoices,
  startReaderSession,
  getReaderSessionStatus,
  seekReaderSession,
  closeReaderSession,
  getReaderAudioUrl
} from '../services/api';
import { AudioQueuePlayer, PlayableItem } from '../services/audio_player';

export const PlayerTab: React.FC = () => {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [sessionId, setSessionId] = useState<string>('');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [readyCount, setReadyCount] = useState(0);
  const [currentSentenceText, setCurrentSentenceText] = useState('Chưa có nội dung.');
  const [nextSentenceText, setNextSentenceText] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1.0);
  const [selectedVoice, setSelectedVoice] = useState('BV074_streaming');
  const [selectedProfile, setSelectedProfile] = useState<'general' | 'story'>('general');
  const [hideOriginal, setHideOriginal] = useState(true);
  const [statusText, setStatusText] = useState('Sẵn sàng');
  const [isProcessing, setIsProcessing] = useState(false);

  const playerRef = useRef<AudioQueuePlayer>(new AudioQueuePlayer());
  const activeSessionIdRef = useRef<string>('');
  const statusPollingRef = useRef<any>(null);
  const injectedXidsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    fetchSettings().then((s) => {
      setSettings(s);
      if (s?.selected_voice) setSelectedVoice(s.selected_voice);
    }).catch(console.error);

    fetchVoices().then(setVoices).catch(console.error);

    const player = playerRef.current;
    player.onTrackChange = (idx, item) => {
      setCurrentIndex(idx);
      if (activeSessionIdRef.current) {
        seekReaderSession(activeSessionIdRef.current, idx).catch(() => {});
      }
      sendTabMessage({
        action: 'HIGHLIGHT_SENTENCE',
        payload: { xid: item.xid }
      });
    };

    player.onStateChange = (playing) => {
      setIsPlaying(playing);
    };

    player.onFinish = () => {
      setStatusText('🎉 Đã đọc xong toàn bộ bài!');
      setIsPlaying(false);
    };

    const handleRuntimeMessage = (msg: any) => {
      if (msg.action === 'PAGE_PRE_EXTRACTED' && msg.payload?.blocks) {
        initSessionWithBlocks(msg.payload.blocks);
      }
    };
    chrome.runtime.onMessage.addListener(handleRuntimeMessage);

    scanActiveTab();

    return () => {
      chrome.runtime.onMessage.removeListener(handleRuntimeMessage);
      player.pause();
      if (statusPollingRef.current) clearInterval(statusPollingRef.current);
      if (activeSessionIdRef.current) {
        closeReaderSession(activeSessionIdRef.current);
      }
    };
  }, []);

  const sendTabMessage = async (msg: any): Promise<any> => {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id || tab.url?.startsWith('chrome://') || tab.url?.startsWith('edge://')) return null;

      try {
        const pong = await chrome.tabs.sendMessage(tab.id, { action: 'PING' });
        if (pong?.status === 'pong') {
          return await chrome.tabs.sendMessage(tab.id, msg);
        }
      } catch {
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['content.js']
          });
          await new Promise((r) => setTimeout(r, 120));
          return await chrome.tabs.sendMessage(tab.id, msg);
        } catch {}
      }
      return await chrome.tabs.sendMessage(tab.id, msg);
    } catch {
      return null;
    }
  };

  const scanActiveTab = async () => {
    setStatusText('Đang quét nội dung bài viết...');
    const res = await sendTabMessage({ action: 'EXTRACT_CONTENT' });
    if (res && res.blocks && res.blocks.length > 0) {
      initSessionWithBlocks(res.blocks);
    } else {
      setStatusText('Không tìm thấy văn bản phù hợp.');
    }
  };

  const initSessionWithBlocks = async (blocks: any[]) => {
    if (activeSessionIdRef.current) {
      closeReaderSession(activeSessionIdRef.current);
    }
    if (statusPollingRef.current) clearInterval(statusPollingRef.current);
    injectedXidsRef.current.clear();

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const tabId = tab?.id || 'tab';

    // Tự động nhận diện thể loại Truyện vs Tin tức/Báo chí
    let detectedP: 'general' | 'story' = 'general';
    if (tab?.url) {
      const u = tab.url.toLowerCase();
      const t = (tab.title || '').toLowerCase();
      const storyPatterns = /(truyen|novel|fiction|wattpad|qidian|faloo|biquge|69shu|uukanshu|syosetu|kakuyomu|ao3|archiveofourown|royalroad|wuxiaworld|chivi|wikidich|tangthuvien|metruyenchu|sangtacviet|bachngocsach|truyenfull|\/chuong|\/chap|\/chapter|\/story\/|\/book\/)/i;
      const storyTitlePatterns = /(?:chương|chapter|hồi|tiết|quyển)\s*\d+/i;
      if (storyPatterns.test(u) || storyTitlePatterns.test(t)) {
        detectedP = 'story';
      }
    }
    setSelectedProfile(detectedP);

    const newSessionId = `session_${tabId}_${Date.now()}`;
    activeSessionIdRef.current = newSessionId;
    setSessionId(newSessionId);
    setIsProcessing(true);
    setStatusText('Đang chuẩn bị phiên đọc...');

    try {
      const res = await startReaderSession({
        session_id: newSessionId,
        blocks,
        profile: detectedP,
        voice_id: selectedVoice,
        speed: speed,
        model: settings?.gemini_model
      });

      const total = res.total_sentences || 0;
      setTotalCount(total);
      setCurrentIndex(0);

      const playables: PlayableItem[] = Array.from({ length: total }, (_, i) => ({
        id: `s-${i}`,
        xid: `xid-${i}`,
        text: `Câu ${i + 1}`,
        audioBlobUrl: getReaderAudioUrl(newSessionId, i)
      }));

      playerRef.current.setQueue(playables, 0);

      // Kích hoạt ẩn gốc mặc định để hiện bản dịch đè lên
      sendTabMessage({ action: 'TOGGLE_ORIGINAL', payload: { hide: hideOriginal } });

      startStatusPolling(newSessionId);
    } catch (err: any) {
      setStatusText(`Lỗi: ${err.message || 'Không thể tạo phiên đọc'}`);
      setIsProcessing(false);
    }
  };

  const startStatusPolling = (sid: string) => {
    if (statusPollingRef.current) clearInterval(statusPollingRef.current);

    const poll = async () => {
      if (activeSessionIdRef.current !== sid) return;
      try {
        const data = await getReaderSessionStatus(sid);
        if (data) {
          setTotalCount(data.total_sentences || 0);
          setReadyCount(data.ready_audio_count || 0);

          if (data.current_sentence) {
            const curText = data.current_sentence.translated || data.current_sentence.original;
            setCurrentSentenceText(curText || 'Đang chuẩn bị...');
          }

          if (data.next_sentence) {
            const nextText = data.next_sentence.translated || data.next_sentence.original;
            setNextSentenceText(nextText || '');
          } else {
            setNextSentenceText('');
          }

          // BƠM BẢN DỊCH ĐÈ LÊN TRANG WEB (INJECT TRANSLATION)
          if (data.translated_items && data.translated_items.length > 0) {
            const groupedByXid: { [xid: string]: string[] } = {};
            data.translated_items.forEach((item: any) => {
              if (item.xid && item.translated) {
                if (!groupedByXid[item.xid]) groupedByXid[item.xid] = [];
                groupedByXid[item.xid].push(item.translated);
              }
            });

            Object.keys(groupedByXid).forEach((xid) => {
              const fullText = groupedByXid[xid].join(' ');
              sendTabMessage({
                action: 'INJECT_TRANSLATION',
                payload: { xid, translatedText: fullText }
              });
            });
          }

          if (data.ready_audio_count > 0) {
            setIsProcessing(!data.is_complete);
            setStatusText(
              data.is_complete
                ? '✅ Sẵn sàng 100% âm thanh!'
                : `⚡ Đã sẵn sàng phát (${data.ready_audio_count}/${data.total_sentences} câu)`
            );
          }
        }
      } catch (e) {
        console.warn('Polling status error:', e);
      }
    };

    poll();
    statusPollingRef.current = setInterval(poll, 1000);
  };

  const handleTogglePlay = () => {
    if (isPlaying) {
      playerRef.current.pause();
    } else {
      playerRef.current.play();
    }
  };

  const handlePrevSentence = () => {
    if (currentIndex > 0) {
      playerRef.current.prev();
      if (activeSessionIdRef.current) {
        seekReaderSession(activeSessionIdRef.current, currentIndex - 1).catch(() => {});
      }
    }
  };

  const handleNextSentence = () => {
    if (currentIndex < totalCount - 1) {
      playerRef.current.next();
      if (activeSessionIdRef.current) {
        seekReaderSession(activeSessionIdRef.current, currentIndex + 1).catch(() => {});
      }
    }
  };

  const handleToggleHideOriginal = () => {
    const nextState = !hideOriginal;
    setHideOriginal(nextState);
    sendTabMessage({ action: 'TOGGLE_ORIGINAL', payload: { hide: nextState } });
  };

  const handleVoiceChange = async (newVoice: string) => {
    setSelectedVoice(newVoice);
    try {
      await saveSettings({ selected_voice: newVoice });
      chrome.tabs?.query({ active: true, currentWindow: true }, (tabs) => {
        tabs.forEach((tab) => {
          if (tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: 'SETTINGS_UPDATED' }).catch(() => {});
          }
        });
      });
    } catch (e) {
      console.warn('[PlayerTab] Lỗi lưu giọng mới:', e);
    }
    scanActiveTab();
  };

  const handleProfileChange = (newProfile: 'general' | 'story') => {
    setSelectedProfile(newProfile);
    scanActiveTab();
  };

  return (
    <div style={containerStyle}>
      {/* 1. Thanh Công Cụ Nhanh */}
      <div style={topBarCardStyle}>
        <button onClick={scanActiveTab} style={actionButtonStyle} title="Quét lại nội dung trang">
          🔍 Quét lại
        </button>

        <button
          onClick={handleToggleHideOriginal}
          style={{
            ...actionButtonStyle,
            backgroundColor: hideOriginal ? '#dbeafe' : '#f8fafc',
            color: hideOriginal ? '#1d4ed8' : '#475569',
            borderColor: hideOriginal ? '#93c5fd' : '#cbd5e1'
          }}
          title="Ẩn/Hiện chữ gốc tiếng Anh"
        >
          {hideOriginal ? '🙈 Đang ẩn chữ gốc' : '👁️ Xem song ngữ'}
        </button>

        <span
          style={{
            fontSize: '11px',
            padding: '5px 10px',
            borderRadius: '6px',
            backgroundColor: selectedProfile === 'story' ? '#fef3c7' : '#f1f5f9',
            color: selectedProfile === 'story' ? '#b45309' : '#475569',
            fontWeight: 600,
            border: `1px solid ${selectedProfile === 'story' ? '#fde68a' : '#e2e8f0'}`,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px'
          }}
          title={selectedProfile === 'story' ? 'Hệ thống tự động nhận diện: Truyện / Tiểu thuyết' : 'Hệ thống tự động nhận diện: Báo chí / Tin tức'}
        >
          {selectedProfile === 'story' ? '📖 Tự động: Truyện' : '📰 Tự động: Báo chí'}
        </span>
      </div>

      {/* 2. Header Trạng thái */}
      <div style={headerCardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#1e293b' }}>🎙️ TTS Reader</span>
          <span style={{ fontSize: '11px', color: isProcessing ? '#2563eb' : '#16a34a', fontWeight: 600 }}>
            {isProcessing ? '⏳ Đang nạp ngầm' : '✅ Đã hoàn tất'}
          </span>
        </div>
        <div style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>
          Đã chuẩn bị: <b>{readyCount}</b> / {totalCount} câu audio · {statusText}
        </div>
      </div>

      {/* 3. CÂU ĐANG ĐỌC (Nổi bật nhất) */}
      <div style={currentCardStyle}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: '#2563eb', textTransform: 'uppercase', marginBottom: '6px' }}>
          👉 Câu đang đọc ({totalCount > 0 ? `${currentIndex + 1}/${totalCount}` : '0/0'})
        </div>
        <div style={{ fontSize: '14px', lineHeight: '1.6', color: '#0f172a', fontWeight: 600 }}>
          {currentSentenceText}
        </div>
      </div>

      {/* 4. CÂU TIẾP THEO (Gọn gàng) */}
      {nextSentenceText && (
        <div style={nextCardStyle}>
          <div style={{ fontSize: '10px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '2px' }}>
            Câu tiếp theo
          </div>
          <div style={{ fontSize: '12px', lineHeight: '1.4', color: '#475569' }}>
            {nextSentenceText}
          </div>
        </div>
      )}

      {/* 5. CỤM ĐIỀU KHIỂN TUA CÂU (Zero lag, chuyển câu tức thì) */}
      <div style={controlCardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <button
            onClick={handlePrevSentence}
            disabled={currentIndex === 0}
            style={stepButtonStyle}
            title="Lùi 1 câu"
          >
            ⏮️ Câu {currentIndex > 0 ? currentIndex : 1}
          </button>

          <span style={{ fontSize: '13px', fontWeight: 700, color: '#1e293b' }}>
            {totalCount > 0 ? `${currentIndex + 1} / ${totalCount}` : '0 / 0'}
          </span>

          <button
            onClick={handleNextSentence}
            disabled={currentIndex >= totalCount - 1}
            style={stepButtonStyle}
            title="Tiến 1 câu"
          >
            Câu {currentIndex + 2 <= totalCount ? currentIndex + 2 : totalCount} ⏭️
          </button>
        </div>

        {/* Nút Play to chính giữa */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', margin: '8px 0' }}>
          <button
            onClick={handleTogglePlay}
            style={mainPlayButtonStyle}
            title={isPlaying ? 'Tạm dừng' : 'Phát ngay'}
          >
            {isPlaying ? '⏸️' : '▶️'}
          </button>
        </div>

        {/* Chọn tốc độ và giọng đọc CapCut */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
          <select
            value={speed}
            onChange={(e) => {
              const spd = Number(e.target.value);
              setSpeed(spd);
              playerRef.current.setSpeed(spd);
            }}
            style={{ ...selectStyle, flex: 1 }}
          >
            <option value={0.75}>0.75x</option>
            <option value={1.0}>1.0x Chuẩn</option>
            <option value={1.25}>1.25x</option>
            <option value={1.5}>1.5x Nhanh</option>
            <option value={2.0}>2.0x Cực nhanh</option>
          </select>

          <select
            value={selectedVoice}
            onChange={(e) => handleVoiceChange(e.target.value)}
            style={{ ...selectStyle, flex: 2 }}
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
};

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  padding: '14px',
  gap: '12px',
  boxSizing: 'border-box',
  height: '100%'
};

const topBarCardStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '6px'
};

const actionButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  backgroundColor: '#f8fafc',
  fontSize: '11px',
  fontWeight: 600,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  gap: '4px'
};

const profileSelectStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  backgroundColor: '#ffffff',
  fontSize: '11px',
  fontWeight: 500,
  cursor: 'pointer',
  outline: 'none'
};

const headerCardStyle: React.CSSProperties = {
  backgroundColor: '#ffffff',
  borderRadius: '8px',
  padding: '10px 12px',
  border: '1px solid #e2e8f0',
  boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
};

const currentCardStyle: React.CSSProperties = {
  backgroundColor: '#eff6ff',
  borderRadius: '10px',
  padding: '14px',
  border: '2px solid #3b82f6',
  boxShadow: '0 2px 4px rgba(59,130,246,0.1)'
};

const nextCardStyle: React.CSSProperties = {
  backgroundColor: '#f8fafc',
  borderRadius: '8px',
  padding: '10px 12px',
  border: '1px dashed #cbd5e1'
};

const controlCardStyle: React.CSSProperties = {
  backgroundColor: '#ffffff',
  borderRadius: '10px',
  padding: '14px',
  border: '1px solid #e2e8f0',
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  marginTop: 'auto'
};

const mainPlayButtonStyle: React.CSSProperties = {
  width: '52px',
  height: '52px',
  borderRadius: '50%',
  backgroundColor: '#2563eb',
  color: '#ffffff',
  border: 'none',
  fontSize: '24px',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  boxShadow: '0 4px 10px rgba(37,99,235,0.35)'
};

const stepButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: '11px',
  fontWeight: 600,
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  backgroundColor: '#f1f5f9',
  cursor: 'pointer'
};

const selectStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  fontSize: '11px',
  backgroundColor: '#f8fafc',
  outline: 'none',
  cursor: 'pointer'
};
