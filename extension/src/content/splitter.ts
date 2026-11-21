// Bộ chia văn bản thích ứng đa thể loại & đa động cơ TTS (đồng bộ DOM và Backend).
// Toàn bộ thuật toán nằm trong ./nlp/segmenter.ts (PTS - Prosody-aware Text Segmenter).
import {
  resolveSegmenterConfig,
  SegmenterProfile,
  splitIntoChunks,
  TtsEngineKind,
} from './nlp/segmenter';

export {
  detectTtsEngine,
  resolveSegmenterConfig,
  splitSentences,
  segmentSpans,
  splitIntoChunks,
} from './nlp/segmenter';
export type { SegmenterConfig, SegmenterProfile, TtsEngineKind } from './nlp/segmenter';

export interface SplitOptions {
  profile?: SegmenterProfile | string;
  voiceId?: string;
  engine?: TtsEngineKind;
  maxChars?: number;
}

export function splitTextIntoChunks(rawText: string, options: number | SplitOptions = {}): string[] {
  if (typeof options === 'number') {
    return splitIntoChunks(rawText, options);
  }
  const cfg = resolveSegmenterConfig(options);
  return splitIntoChunks(rawText, undefined, cfg);
}
