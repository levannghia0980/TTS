import uvicorn
import os
import sys

# Đảm bảo đường dẫn import đúng module app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Đang khởi động TextToSpeech Backend API...")
    print("📍 Swagger API Docs: http://127.0.0.1:8000/docs")
    print("📍 Settings Endpoint: http://127.0.0.1:8000/api/v1/settings")
    print("📍 Voices Endpoint: http://127.0.0.1:8000/api/v1/settings/voices")
    print("=" * 60)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

