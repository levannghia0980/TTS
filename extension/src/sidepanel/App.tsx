import React, { useState } from 'react';
import { PlayerTab } from './components/PlayerTab';
import { SettingsTab } from './components/SettingsTab';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'player' | 'settings'>('player');

  return (
    <div style={containerStyle}>
      {/* Top Header */}
      <header style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '20px' }}>🎙️</span>
          <span style={{ fontWeight: 700, fontSize: '16px', color: '#0f172a' }}>
            TextToSpeech AI
          </span>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav style={navStyle}>
        <button
          onClick={() => setActiveTab('player')}
          style={{
            ...tabButtonStyle,
            borderBottomColor: activeTab === 'player' ? '#2563eb' : 'transparent',
            color: activeTab === 'player' ? '#2563eb' : '#64748b',
            fontWeight: activeTab === 'player' ? 600 : 500
          }}
        >
          🎧 Trình Phát
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          style={{
            ...tabButtonStyle,
            borderBottomColor: activeTab === 'settings' ? '#2563eb' : 'transparent',
            color: activeTab === 'settings' ? '#2563eb' : '#64748b',
            fontWeight: activeTab === 'settings' ? 600 : 500
          }}
        >
          ⚙️ Cài Đặt
        </button>
      </nav>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflowY: 'auto' }}>
        {activeTab === 'player' ? <PlayerTab /> : <SettingsTab />}
      </main>
    </div>
  );
};

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  backgroundColor: '#f8fafc',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
};

const headerStyle: React.CSSProperties = {
  padding: '12px 16px',
  backgroundColor: '#ffffff',
  borderBottom: '1px solid #e2e8f0',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between'
};

const navStyle: React.CSSProperties = {
  display: 'flex',
  backgroundColor: '#ffffff',
  borderBottom: '1px solid #e2e8f0',
  padding: '0 8px'
};

const tabButtonStyle: React.CSSProperties = {
  flex: 1,
  padding: '10px 0',
  background: 'none',
  border: 'none',
  borderBottom: '2px solid transparent',
  fontSize: '13px',
  cursor: 'pointer',
  transition: 'all 0.2s ease'
};

