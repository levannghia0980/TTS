import sys
import os
from pathlib import Path

# Fix Windows console utf-8 encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_all():
    print("=" * 60)
    print("1. Testing Root endpoint / ...")
    r1 = client.get("/")
    assert r1.status_code == 200, f"Error: {r1.text}"
    print("-> Root response:", r1.json())

    print("\n2. Testing GET /api/v1/settings ...")
    r2 = client.get("/api/v1/settings")
    assert r2.status_code == 200, f"Error: {r2.text}"
    print("-> Settings response:", r2.json())

    print("\n3. Testing GET /api/v1/settings/voices ...")
    r3 = client.get("/api/v1/settings/voices")
    assert r3.status_code == 200, f"Error: {r3.text}"
    data_voices = r3.json()
    print(f"-> Total voices: {data_voices['total']}")
    print("-> First 3 voices:", data_voices['voices'][:3])

    print("\n4. Testing POST /api/v1/tts (Đọc thử 1 câu bằng giọng Hoài My) ...")
    r_tts = client.post("/api/v1/tts", json={
        "text": "1. Xin chào, đây là bản thử nghiệm giọng đọc Hoài My.",
        "voice_id": "vi-VN-HoaiMyNeural",
        "speed": 1.0
    })
    assert r_tts.status_code == 200, f"Error: {r_tts.text}"
    tts_data = r_tts.json()
    print("-> TTS Status:", tts_data.get("status"))
    print("-> Cleaned Text (bóc số 1.):", tts_data.get("clean_text"))
    print("-> Audio format:", tts_data.get("audio_base64")[:35] + "...")
    print("-> Audio size bytes:", tts_data.get("size_bytes"))

    print("\n5. Testing POST /api/v1/tts/batch (Đọc song song 2 câu) ...")
    r_batch = client.post("/api/v1/tts/batch", json={
        "sentences": [
            {"id": "câu-1", "text": "Đoạn văn thứ nhất đang được đọc song song."},
            {"id": "câu-2", "text": "Đoạn văn thứ hai cũng được xử lý cùng lúc."}
        ],
        "voice_id": "vi-VN-HoaiMyNeural",
        "speed": 1.0,
        "max_workers": 2
    })
    assert r_batch.status_code == 200, f"Error: {r_batch.text}"
    batch_data = r_batch.json()
    print(f"-> Batch Total: {batch_data.get('total')}, Success: {batch_data.get('success_count')}")

    print("\n6. Testing POST /api/v1/translate (Kiểm tra validation khi chưa có key) ...")
    r_trans = client.post("/api/v1/translate", json={"text": "Hello world"})
    print("-> Translate without key response status:", r_trans.status_code)
    print("-> Translate response detail:", r_trans.json().get("detail"))

    print("\n" + "=" * 60)
    print("🎉 TẤT CẢ CÁC BÀI TEST BACKEND ĐỀU THÀNH CÔNG RỰC RỠ!")
    print("=" * 60)

if __name__ == "__main__":
    test_all()
