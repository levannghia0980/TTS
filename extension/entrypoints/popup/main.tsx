import React from 'react';
import ReactDOM from 'react-dom/client';
import { SettingsTab } from '../../src/sidepanel/components/SettingsTab';

const PopupApp: React.FC = () => {
  return (
    <div>
      <header style={{
        padding: '12px 16px',
        backgroundColor: '#ffffff',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '18px' }}>🎙️</span>
          <span style={{ fontWeight: 700, fontSize: '14px', color: '#0f172a' }}>
            TextToSpeech AI Cài Đặt
          </span>
        </div>
      </header>
      <main>
        <SettingsTab />
      </main>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PopupApp />
  </React.StrictMode>
);

