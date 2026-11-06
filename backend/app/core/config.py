import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv()


class Settings:
    PROJECT_NAME: str = "TextToSpeech Backend API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Paths
    BASE_DIR: Path = BASE_DIR
    ENV_PATH: Path = ENV_PATH

    # Gemini API Settings (Chỉ dùng gemini-3.1-flash-lite hoặc gemini-3.5-flash-lite)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    # TTS Settings
    TTS_ENGINE: str = os.getenv("TTS_ENGINE", "capcut")
    SELECTED_VOICE: str = os.getenv("SELECTED_VOICE", "BV074_streaming")
    TTS_MAX_WORKERS: int = int(os.getenv("TTS_MAX_WORKERS", "32"))
    CAPCUT_COOKIE: str = os.getenv("CAPCUT_COOKIE", "")
    TIKTOK_SESSION_ID: str = os.getenv("TIKTOK_SESSION_ID", "")
    LOCAL_PIPER_MODEL_PATH: str = os.getenv(
        "LOCAL_PIPER_MODEL_PATH",
        r"D:\NENGHIA0980\AIREAD\models\ngoc_huyen_new\ngochuyennew.onnx"
    )
    LOCAL_PIPER_CONFIG_PATH: str = os.getenv(
        "LOCAL_PIPER_CONFIG_PATH",
        r"D:\NENGHIA0980\AIREAD\models\ngoc_huyen_new\ngochuyennew.onnx.json"
    )

    @classmethod
    def reload_from_env(cls):
        """Đọc lại cấu hình từ file .env vào runtime settings và os.environ ngay lập tức."""
        if not cls.ENV_PATH.exists():
            return
        int_fields = {"TTS_MAX_WORKERS"}
        with open(cls.ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k in int_fields:
                        try:
                            val = int(v)
                        except Exception:
                            val = 32
                    else:
                        val = v
                    setattr(cls, k, val)
                    os.environ[k] = str(val)

    @classmethod
    def save_to_env(cls, updates: dict):
        """Lưu cấu hình mới vào file .env và cập nhật biến runtime."""
        env_lines = []
        updated_keys = set()

        if cls.ENV_PATH.exists():
            with open(cls.ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.split("=", 1)[0].strip()
                        if key in updates:
                            env_lines.append(f"{key}={updates[key]}\n")
                            updated_keys.add(key)
                        else:
                            env_lines.append(line)
                    else:
                        env_lines.append(line)

        # Thêm các key mới chưa có trong file
        for k, v in updates.items():
            if k not in updated_keys:
                env_lines.append(f"{k}={v}\n")

        with open(cls.ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(env_lines)

        cls.reload_from_env()


settings = Settings()

