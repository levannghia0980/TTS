# -*- coding: utf-8 -*-
"""
Kiểm tra tính tương đương tuyệt đối (Bit-for-bit Parity) giữa bản Python
(`backend/app/services/text_segmenter.py`) và bản TypeScript chạy trên trình duyệt
(`extension/src/content/nlp/segmenter.ts`) trên tất cả các chế độ thích ứng
(thể loại 'general' vs 'story' và động cơ CapCut/Edge/Piper).
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.text_segmenter import (
    resolve_segmenter_config,
    segment_spans,
    split_into_chunks,
    split_sentences,
)

TS_ENTRY = ROOT / "extension" / "src" / "content" / "nlp" / "segmenter.ts"
ESBUILD_JS = ROOT / "extension" / "node_modules" / "esbuild" / "bin" / "esbuild"
UD_DIR = ROOT / "research" / "segmentation" / "data" / "ud"

HANDCRAFTED_CASES = [
    "TP. HCM hôm nay có mưa lớn trên diện rộng.",
    "PGS. TS. Nguyễn Văn A tại ĐH Bách Khoa công bố kết quả phiên bản 3.14 trên https://example.com/v1.0/paper.pdf?a=1&b=2. Mức tăng đạt 12,5% so với năm 2025.",
    "\"Đi thôi!\" hắn nói khẽ rồi quay lưng bước đi, trong khi bên ngoài trời vẫn mưa tầm tã không dứt suốt từ sáng sớm đến tận chiều muộn.",
    "\"Hả?\" \"Thật sao?!\" Hắn giật mình quay lại nhìn đối phương rồi khẽ thở dài một tiếng.",
    "Giá trị hợp đồng lên tới 1.250.000.000 đồng, thanh toán trước ngày 21/11/2026 lúc 10:30 qua email finance@company.com.vn để xác nhận.",
    "1. Tổng quan về phương pháp phân đoạn văn bản theo ngữ điệu cho hệ thống tổng hợp tiếng nói tiếng Việt.",
    "Ngoài ra, các hệ thống như Node.js v20.18.0 hay Python 3.11 đều chạy rất ổn định, tuy nhiên việc xử lý dữ liệu thời gian thực vẫn đòi hỏi độ trễ cực thấp.",
    "Tôi đã đi đến siêu thị mua rất nhiều thực phẩm tươi sống cho bữa tiệc sinh nhật tối nay cùng gia đình, rất vui.",
    "Các công cụ phổ biến gồm FastAPI, Uvicorn, edge-tts, v.v. Chúng phối hợp với nhau khá nhịp nhàng.",
    "Đoạn văn dài có dấu ngoặc đơn (ví dụ như cụm giải thích kỹ thuật chi tiết không nên tách ngang giữa chừng) và dấu gạch ngang — một dấu ngắt rất tốt — giúp người nghe dễ theo dõi.",
    "Dr. J. K. Rowling met Prof. Smith at 10:30 a.m. in New York. They discussed e.g. NLP, TTS, and LLMs.",
    "The U.S. economy grew by 2.8% in Q3 2025, whereas several European markets slowed down due to rising energy costs and persistent supply-chain disruptions.",
    "See Fig. 3 and No. 5 on pp. 12-18 (published in Jan. 2024) for complete experimental results on multi-speaker prosody synthesis.",
    "自从2004年提出了兴建人文大楼的构想，企业界陆续有人提供捐款。楼顶有天文台，现为天文社使用。",
    "国际北极研究中心的主要伙伴是日本和美国，参与会务的还有来自加拿大、中国、丹麦、德国、日本、挪威、俄罗斯、英国和美国的代表。",
    "他说：“今天下午三点半我们在北京大学的图书馆见面，讨论关于自然语言处理和语音合成的最新论文。”然后转身离开了教室。",
    "🚀 Thử nghiệm emoji 😂 kết hợp https://sub.domain.org/path?x=1&y=2 và số 3.14159 trong một câu dài để kiểm tra lệch offset giữa UTF-16 của JS và Unicode code point của Python!",
    "Đoạn văn có ký tự toán học 𝐚𝐛𝐜 ∇·𝐄 = ρ/ε₀ — rất dễ gây lệch vị trí nếu JS dùng UTF-16 index thay vì code point — nhưng thuật toán phải khớp 100%.",
    "A" * 175 + " kết thúc.",
    "   \n\t  ",
    "",
]

PRESET_MODES = [
    ("general_capcut", "general", "BV074_streaming"),
    ("story_capcut", "story", "BV074_streaming"),
    ("general_edge", "general", "vi-VN-HoaiMyNeural"),
    ("story_local", "story", "local_ngoc_huyen_new"),
]


def load_ud_samples(max_per_lang: int = 80) -> List[str]:
    rng = random.Random(42)
    samples: List[str] = []
    for fname in ["vi_vtb-ud-test.conllu", "en_ewt-ud-test.conllu", "zh_gsdsimp-ud-test.conllu"]:
        path = UD_DIR / fname
        if not path.exists():
            continue
        sents: List[str] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# text ="):
                    t = line[len("# text ="):].strip()
                    if t:
                        sents.append(t)
        samples.extend(rng.sample(sents, min(max_per_lang, len(sents))))
        for i in range(0, min(60, len(sents) - 3), 3):
            joiner = "" if fname.startswith("zh_") else " "
            samples.append(joiner.join(sents[i:i + 3]))
    return samples


def build_ts_bundle(out_js: Path) -> None:
    cmd = [
        "node",
        str(ESBUILD_JS),
        str(TS_ENTRY),
        "--bundle",
        "--platform=node",
        "--format=cjs",
        f"--outfile={out_js}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"esbuild failed:\n{res.stderr}\n{res.stdout}")


def run_node_batch(bundle_js: Path, texts: List[str]) -> Dict[str, Any]:
    modes_js = json.dumps(PRESET_MODES)
    driver = f"""
const fs = require('fs');
const seg = require({json.dumps(str(bundle_js))});
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const modes = {modes_js};
const t0 = process.hrtime.bigint();
const out = payload.texts.map((txt) => {{
  const res = {{ sents: seg.splitSentences(txt), modes: {{}} }};
  for (const [label, profile, voiceId] of modes) {{
    const cfg = seg.resolveSegmenterConfig({{ profile, voiceId }});
    res.modes[label] = {{
      spans: seg.segmentSpans(txt, undefined, cfg),
      texts: seg.splitIntoChunks(txt, undefined, cfg),
    }};
  }}
  return res;
}});
const ms = Number(process.hrtime.bigint() - t0) / 1e6;
process.stdout.write(JSON.stringify({{ ms, out }}));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as tf:
        tf.write(driver)
        driver_path = Path(tf.name)
    try:
        inp = json.dumps({"texts": texts}, ensure_ascii=False)
        proc = subprocess.run(
            ["node", str(driver_path)],
            input=inp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(proc.stdout)
    finally:
        driver_path.unlink(missing_ok=True)


def run_parity_check() -> Dict[str, Any]:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    texts = HANDCRAFTED_CASES + load_ud_samples(80)
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_js = Path(tmpdir) / "segmenter.cjs"
        build_ts_bundle(bundle_js)
        ts_res = run_node_batch(bundle_js, texts)

    t0 = time.perf_counter()
    py_out = []
    for txt in texts:
        item: Dict[str, Any] = {"sents": split_sentences(txt), "modes": {}}
        for label, profile, voice_id in PRESET_MODES:
            cfg = resolve_segmenter_config(profile=profile, voice_id=voice_id)
            item["modes"][label] = {
                "spans": [list(sp) for sp in segment_spans(txt, cfg=cfg)],
                "texts": split_into_chunks(txt, cfg=cfg),
            }
        py_out.append(item)
    py_ms = (time.perf_counter() - t0) * 1000.0

    mismatches = []
    for idx, txt in enumerate(texts):
        py_i = py_out[idx]
        ts_i = ts_res["out"][idx]
        if py_i["sents"] != ts_i["sents"]:
            mismatches.append({"idx": idx, "kind": "SBD", "text": txt[:140], "py": py_i["sents"], "ts": ts_i["sents"]})
        for label, _p, _v in PRESET_MODES:
            if py_i["modes"][label] != ts_i["modes"][label]:
                mismatches.append({
                    "idx": idx,
                    "kind": label,
                    "text": txt[:140],
                    "py": py_i["modes"][label]["texts"],
                    "ts": ts_i["modes"][label]["texts"],
                })

    summary = {
        "total_cases": len(texts),
        "modes": len(PRESET_MODES),
        "mismatches": len(mismatches),
        "parity_rate": 100.0 * (len(texts) - len(mismatches)) / len(texts),
        "python_ms": round(py_ms, 2),
        "ts_node_ms": round(ts_res["ms"], 2),
    }
    print(f"Parity check: {summary['total_cases']} cases x {summary['modes']} adaptive modes | "
          f"Mismatches: {summary['mismatches']} | Parity: {summary['parity_rate']:.2f}% | "
          f"Python: {summary['python_ms']}ms | TS(Node): {summary['ts_node_ms']}ms")
    if mismatches:
        for m in mismatches[:5]:
            print("  MISMATCH:", m)
        raise AssertionError(f"Found {len(mismatches)} parity mismatches!")
    return summary


if __name__ == "__main__":
    run_parity_check()
