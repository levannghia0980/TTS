const API_BASE = 'http://127.0.0.1:8000/api/v1';

async function handleApiCall(payload: {
  endpoint: string;
  method?: string;
  body?: any;
  isAudio?: boolean;
}): Promise<any> {
  const url = `${API_BASE}${payload.endpoint}`;
  const method = payload.method || 'GET';
  const headers: Record<string, string> = {};

  const init: RequestInit = { method, headers };

  if (payload.body && method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(payload.body);
  }

  const res = await fetch(url, init);

  if (payload.isAudio) {
    if (!res.ok) {
      throw new Error(`Lỗi tải audio: ${res.status}`);
    }
    const contentType = res.headers.get('content-type') || 'audio/mpeg';
    const buffer = await res.arrayBuffer();
    // Chuyển sang base64 data URI
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    const b64 = btoa(binary);
    return { dataUri: `data:${contentType};base64,${b64}`, size: len };
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `HTTP ${res.status}`);
  }

  return await res.json();
}

export default defineBackground(() => {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action === 'PROXY_API') {
      handleApiCall(message.payload)
        .then((data) => sendResponse({ success: true, data }))
        .catch((err) => sendResponse({ success: false, error: err.message }));
      return true; // Bắt buộc return true để giữ kênh phản hồi bất đồng bộ
    }
    if (message.action === 'OPEN_SETTINGS') {
      if ((chrome.action as any)?.openPopup) {
        (chrome.action as any).openPopup().catch(() => {});
      }
      sendResponse({ success: true });
      return false;
    }
    // Quản lý trang đầu tiên được tự động bật
    if (message.action === 'CLAIM_PRIMARY_AUTO_START') {
      chrome.storage.session.get(['primaryAutoStartClaimed'], (res) => {
        if (!res.primaryAutoStartClaimed) {
          chrome.storage.session.set({ primaryAutoStartClaimed: true });
          sendResponse({ isPrimary: true });
        } else {
          sendResponse({ isPrimary: false });
        }
      });
      return true;
    }
    return false;
  });

  chrome.runtime.onInstalled.addListener(() => {
    console.log('🎉 TextToSpeech Background Service Worker đã sẵn sàng!');
  });
});
