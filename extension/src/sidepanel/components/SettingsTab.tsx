import React, { useState, useEffect } from 'react';
import { Settings, Voice } from '../../types';
import { fetchSettings, saveSettings, testGeminiKey, fetchVoices } from '../services/api';

export const SettingsTab: React.FC = () => {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);

  // Form states
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState<'gemini-3.1-flash-lite' | 'gemini-3.5-flash-lite'>('gemini-3.1-flash-lite');
  const [selectedVoice, setSelectedVoice] = useState('vi-VN-HoaiMyNeural');
  const [threads, setThreads] = useState(32);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [conf, vList] = await Promise.all([fetchSettings(), fetchVoices()]);
      setSettings(conf);
      setVoices(vList);

      setModel(conf.gemini_model);
      setSelectedVoice(conf.selected_voice || 'vi-VN-HoaiMyNeural');
      setThreads(conf.tts_threads || 32);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleTestKey = async () => {
    const keyToTest = apiKey.trim();
    if (!keyToTest && !settings?.has_gemini_key) {
      setTestResult({ success: false, message: 'Vui lòng nhập Gemini API Key trước khi kiểm tra!' });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testGeminiKey(keyToTest, model);
      setTestResult({ success: true, message: res.message || 'Kết nối thành công!' });
      await loadData();
    } catch (err: any) {
      setTestResult({ success: false, message: err.message || 'Kiểm tra thất bại.' });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage(null);
    try {
      const payload: any = {
        gemini_model: model,
        selected_voice: selectedVoice,
        tts_threads: threads
      };
      if (apiKey.trim()) {
        payload.gemini_api_key = apiKey.trim();
      }
      await saveSettings(payload);
      setSaveMessage('✅ Đã lưu cấu hình thành công!');
      setApiKey('');
      await loadData();
      
      // Bắn thông báo cập nhật tới tab đang mở để áp dụng ngay giọng mới
      if (typeof chrome !== 'undefined' && chrome.tabs) {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          tabs.forEach((tab) => {
            if (tab.id) {
              chrome.tabs.sendMessage(tab.id, { action: 'SETTINGS_UPDATED' }).catch(() => {});
            }
          });
        });
      }

      setTimeout(() => setSaveMessage(null), 3000);
    } catch (err: any) {
      setSaveMessage(`❌ ${err.message || 'Lỗi khi lưu cấu hình'}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
        Đang tải cấu hình từ Backend...
      </div>
    );
  }

  const femaleVoices = voices.filter((v) => v.gender === 'female');
  const maleVoices = voices.filter((v) => v.gender === 'male');

  return (
    <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. Cấu hình Gemini API */}
      <div style={cardStyle}>
        <div style={cardHeaderStyle}>
          <span style={iconSpanStyle}>✨</span>
          <h3 style={cardTitleStyle}>Google Gemini API (Dịch thuật)</h3>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={labelStyle}>Gemini API Key:</label>
            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <input
                type={showKey ? 'text' : 'password'}
                placeholder={settings?.has_gemini_key ? `Đã lưu: ${settings.gemini_api_key}` : 'Dán API Key (bắt đầu bằng AIza...)'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                style={inputStyle}
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                style={secondaryButtonStyle}
                title="Ẩn/Hiện Key"
              >
                {showKey ? '🙈' : '👁️'}
              </button>
            </div>
            {settings?.has_gemini_key && (
              <span style={{ fontSize: '12px', color: '#16a34a', marginTop: '4px', display: 'block' }}>
                ● Đã có API Key hợp lệ trong hệ thống
              </span>
            )}
          </div>

          <div>
            <label style={labelStyle}>Mô hình (Model):</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value as any)}
              style={selectStyle}
            >
              <option value="gemini-3.1-flash-lite">gemini-3.1-flash-lite (Mặc định - Siêu nhanh, rẻ)</option>
              <option value="gemini-3.5-flash-lite">gemini-3.5-flash-lite (Bản nâng cấp chất lượng)</option>
            </select>
          </div>

          <button
            onClick={handleTestKey}
            disabled={testing}
            style={outlineButtonStyle}
          >
            {testing ? 'Đang kiểm tra kết nối...' : '⚡ Kiểm Tra Kết Nối Gemini Key'}
          </button>

          {testResult && (
            <div
              style={{
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '13px',
                backgroundColor: testResult.success ? '#dcfce7' : '#fee2e2',
                color: testResult.success ? '#15803d' : '#b91c1c'
              }}
            >
              {testResult.message}
            </div>
          )}
        </div>
      </div>

      {/* 2. Cấu hình Giọng đọc TTS (18 Voices ReviewMatThon) */}
      <div style={cardStyle}>
        <div style={cardHeaderStyle}>
          <span style={iconSpanStyle}>🎙️</span>
          <h3 style={cardTitleStyle}>Giọng Đọc TTS (Review Phim / Truyện)</h3>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={labelStyle}>Chọn giọng đọc mặc định (18 giọng chuẩn):</label>
            <select
              value={selectedVoice}
              onChange={(e) => setSelectedVoice(e.target.value)}
              style={selectStyle}
            >
              <optgroup label="Top Giọng Nữ Review & Kể Chuyện">
                {femaleVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Top Giọng Nam Thuyết Minh & Trầm Hùng">
                {maleVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </optgroup>
            </select>
          </div>

          {/* 3. Slider số luồng song song */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <label style={labelStyle}>Số luồng TTS song song:</label>
              <span style={{ fontWeight: 600, color: '#2563eb', fontSize: '13px' }}>
                {threads} luồng
              </span>
            </div>
            <input
              type="range"
              min={4}
              max={128}
              step={4}
              value={threads}
              onChange={(e) => setThreads(Number(e.target.value))}
              style={{ width: '100%', cursor: 'pointer' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#94a3b8' }}>
              <span>4 luồng (Ổn định)</span>
              <span>32 luồng (Khuyên dùng)</span>
              <span>128 luồng (Siêu tốc)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Nút lưu */}
      <button
        onClick={handleSave}
        disabled={saving}
        style={primaryButtonStyle}
      >
        {saving ? 'Đang lưu...' : '💾 Lưu Cài Đặt Hệ Thống'}
      </button>

      {saveMessage && (
        <div style={{ textAlign: 'center', fontSize: '14px', fontWeight: 500 }}>
          {saveMessage}
        </div>
      )}
    </div>
  );
};

// Inline CSS Styles
const cardStyle: React.CSSProperties = {
  backgroundColor: '#ffffff',
  borderRadius: '10px',
  padding: '16px',
  boxShadow: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
  border: '1px solid #e2e8f0'
};

const cardHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  marginBottom: '14px',
  borderBottom: '1px solid #f1f5f9',
  paddingBottom: '8px'
};

const cardTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: '15px',
  fontWeight: 600,
  color: '#0f172a'
};

const iconSpanStyle: React.CSSProperties = {
  fontSize: '18px'
};

const labelStyle: React.CSSProperties = {
  fontSize: '13px',
  fontWeight: 500,
  color: '#475569',
  display: 'block'
};

const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: '8px 12px',
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  fontSize: '13px',
  outline: 'none',
  boxSizing: 'border-box'
};

const selectStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  borderRadius: '6px',
  border: '1px solid #cbd5e1',
  fontSize: '13px',
  backgroundColor: '#ffffff',
  marginTop: '4px',
  outline: 'none'
};

const primaryButtonStyle: React.CSSProperties = {
  backgroundColor: '#2563eb',
  color: '#ffffff',
  border: 'none',
  borderRadius: '8px',
  padding: '12px',
  fontSize: '14px',
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'background 0.2s',
  boxShadow: '0 2px 4px rgba(37,99,235,0.2)'
};

const secondaryButtonStyle: React.CSSProperties = {
  backgroundColor: '#f1f5f9',
  border: '1px solid #cbd5e1',
  borderRadius: '6px',
  padding: '6px 12px',
  cursor: 'pointer'
};

const outlineButtonStyle: React.CSSProperties = {
  backgroundColor: '#f8fafc',
  color: '#334155',
  border: '1px solid #cbd5e1',
  borderRadius: '6px',
  padding: '8px 14px',
  fontSize: '13px',
  fontWeight: 500,
  cursor: 'pointer'
};

