export interface Voice {
  id: string;
  name: string;
  gender: 'male' | 'female';
}

export interface Settings {
  gemini_api_key: string;
  has_gemini_key: boolean;
  gemini_model: 'gemini-3.1-flash-lite' | 'gemini-3.5-flash-lite';
  supported_gemini_models: string[];
  tts_engine: string;
  selected_voice: string;
  tts_threads: number;
}

export type ChunkStatus = 'pending' | 'processing' | 'ready' | 'error';

export interface Sentence {
  id: string;
  text: string;
  audioBase64?: string;
  status: ChunkStatus;
}

export interface Paragraph {
  id: string;
  xid: string;
  original: string;
  kind: 'heading' | 'para';
  lang: 'vi' | 'other'; // 'vi' thì bỏ qua bước dịch
  translated?: string;
  status: ChunkStatus;
  sentences: Sentence[];
}

export interface ExtractedBlock {
  xid: string;
  text: string;
  kind: 'heading' | 'para';
  lang: 'vi' | 'other';
}

export interface ExtractResult {
  blocks: ExtractedBlock[];
  method: string;
  totalChars: number;
  viCount: number;
}

export interface ExtensionMessage {
  action:
    | 'PING'
    | 'EXTRACT_CONTENT'
    | 'PICK_ROOT'
    | 'ROOT_PICKED'
    | 'CLEAR_PREVIEW'
    | 'INJECT_TRANSLATION'
    | 'HIGHLIGHT_SENTENCE'
    | 'TOGGLE_ORIGINAL'
    | 'RESET';
  payload?: any;
}
