import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  runner: {
    binaries: {
      chrome: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    },
    startUrls: ['https://en.wikipedia.org/wiki/Magnolia_warbler']
  },
  manifest: {
    name: 'TextToSpeech AI - Dịch & Đọc Web',
    description: 'Extension dịch thuật Google Gemini và phát đọc TTS chuẩn Review Phim/Truyện',
    version: '1.0.0',
    permissions: [
      'activeTab',
      'storage',
      'scripting',
      'tabs'
    ],
    host_permissions: [
      '*://*/*',
      '<all_urls>',
      'http://127.0.0.1:8000/*'
    ],
    action: {
      default_title: 'Cài đặt TextToSpeech AI',
      default_popup: 'popup.html'
    }
  }
});
