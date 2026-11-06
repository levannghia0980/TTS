// Bộ chia nhỏ văn bản thông minh đồng bộ giữa UI và TTS
// Quy tắc:
// 1. Tách theo dấu kết thúc câu (. ! ? … \n hoặc CJK 。！？)
// 2. Nếu vế câu vẫn dài hơn maxChars (mặc định 120 ký tự):
//    Tách tiếp theo dấu giữa câu (phẩy, chấm phẩy, hai chấm, gạch ngang, liên từ)
// 3. Đảm bảo mỗi mẩu đều <= maxChars, hoàn toàn đồng bộ 1-1 với 1 request TTS của CapCut/TikTok.

export function splitTextIntoChunks(rawText: string, maxChars: number = 120): string[] {
  if (!rawText || !rawText.trim()) return [];

  // Bước 1: Tách theo dấu kết thúc câu (. ! ? … \n hoặc CJK 。！？)
  const sentenceRegex = /(?<=[.?!…\n。！？])\s+/;
  const rawSentences = rawText
    .split(sentenceRegex)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  const clauseChunks: string[] = [];

  for (const sent of rawSentences) {
    if (sent.length <= maxChars) {
      clauseChunks.push(sent);
      continue;
    }

    // Bước 2: Câu dài hơn maxChars -> Cắt theo dấu phẩy, chấm phẩy, hai chấm, gạch ngang
    // Cắt và giữ lại dấu phân cách
    const parts = sent.split(/([,;:—–\-\,\;\:\，\；\：]+|\s+(?:và|nhưng|mà|cùng|hoặc|and|but|or|while)\s+)/);

    let currentBuf = '';

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!part) continue;

      if ((currentBuf + part).length <= maxChars) {
        currentBuf += part;
      } else {
        if (currentBuf.trim()) {
          clauseChunks.push(currentBuf.trim());
        }
        currentBuf = part;
      }
    }

    if (currentBuf.trim()) {
      clauseChunks.push(currentBuf.trim());
    }
  }

  // Bước 3: Đề phòng câu quá dài không hề có dấu câu -> cắt theo ranh giới từ
  const finalChunks: string[] = [];
  for (const c of clauseChunks) {
    if (c.length <= maxChars) {
      finalChunks.push(c);
    } else {
      const words = c.split(/\s+/);
      let buf = '';
      for (const w of words) {
        if ((buf ? buf + ' ' + w : w).length <= maxChars) {
          buf = buf ? buf + ' ' + w : w;
        } else {
          if (buf) finalChunks.push(buf);
          buf = w;
        }
      }
      if (buf) finalChunks.push(buf);
    }
  }

  return finalChunks.filter((s) => s.length > 1);
}

