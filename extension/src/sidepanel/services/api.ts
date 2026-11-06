import { Settings, Voice } from '../../types';

export const API_BASE = 'http://127.0.0.1:8000/api/v1';

/**
 * Gọi API thông qua Background Service Worker để tránh triệt để lỗi Mixed Content (HTTPS -> HTTP) và CORS.
 */
async function callProxyApi(endpoint: string, method: string = 'GET', body?: any, isAudio: boolean = false): Promise<any> {
  if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
    try {
      const resp = await chrome.runtime.sendMessage({
        action: 'PROXY_API',
        payload: { endpoint, method, body, isAudio }
      });
      if (resp && resp.success) {
        return resp.data;
      }
      if (resp && resp.error) {
        throw new Error(resp.error);
      }
    } catch (e: any) {
      // Nếu worker chưa sẵn sàng, thử gọi fetch trực tiếp nếu là trang extension
      if (typeof window !== 'undefined' && window.location.protocol.startsWith('chrome-extension')) {
        return directFetch(endpoint, method, body);
      }
      throw e;
    }
  }
  return directFetch(endpoint, method, body);
}

async function directFetch(endpoint: string, method: string = 'GET', body?: any) {
  const url = `${API_BASE}${endpoint}`;
  const headers: Record<string, string> = {};
  const init: RequestInit = { method, headers };
  if (body && method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchSettings(): Promise<Settings> {
  return callProxyApi('/settings');
}

export async function saveSettings(data: Partial<Settings>): Promise<any> {
  return callProxyApi('/settings', 'POST', data);
}

export async function testGeminiKey(apiKey: string, model: string): Promise<any> {
  return callProxyApi('/settings/test-gemini', 'POST', { api_key: apiKey, model });
}

export async function fetchVoices(): Promise<Voice[]> {
  const data = await callProxyApi('/settings/voices');
  return data.voices || [];
}

export interface StartSessionParams {
  session_id: string;
  blocks: any[];
  profile?: string;
  voice_id?: string;
  orig_voice_id?: string;
  vi_voice_id?: string;
  lang?: string;
  page_url?: string;
  mode?: 'orig' | 'vi';
  speed?: number;
  model?: string;
}

export async function startReaderSession(params: StartSessionParams): Promise<any> {
  return callProxyApi('/session/start', 'POST', params);
}

export async function getReaderSessionStatus(sessionId: string): Promise<any> {
  return callProxyApi(`/session/status/${sessionId}`);
}

export async function seekReaderSession(sessionId: string, index: number): Promise<any> {
  return callProxyApi('/session/seek', 'POST', { session_id: sessionId, index });
}

export async function switchSessionMode(sessionId: string, mode: 'orig' | 'vi'): Promise<any> {
  return callProxyApi('/session/switch-mode', 'POST', { session_id: sessionId, mode });
}

export async function closeReaderSession(sessionId: string): Promise<any> {
  try {
    return await callProxyApi(`/session/${sessionId}`, 'DELETE');
  } catch {
    return null;
  }
}

/**
 * Tải audio dưới dạng Data URI an toàn (data:audio/mp3;base64,...) để phát mượt mà trên mọi trang web HTTPS
 */
export async function getAudioDataUri(sessionId: string, index: number): Promise<string> {
  const res = await callProxyApi(`/session/audio/${sessionId}/${index}`, 'GET', null, true);
  return res?.dataUri || '';
}

export async function getOrigAudioDataUri(sessionId: string, index: number): Promise<string> {
  const res = await callProxyApi(`/session/audio-orig/${sessionId}/${index}`, 'GET', null, true);
  return res?.dataUri || '';
}

export async function getViAudioDataUri(sessionId: string, index: number): Promise<string> {
  const res = await callProxyApi(`/session/audio-vi/${sessionId}/${index}`, 'GET', null, true);
  return res?.dataUri || '';
}

export function getReaderAudioUrl(sessionId: string, index: number): string {
  return `${API_BASE}/session/audio/${sessionId}/${index}`;
}
