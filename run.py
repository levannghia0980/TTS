import os
import sys
import time
import signal
import atexit
import subprocess
from pathlib import Path

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
EXTENSION_DIR = BASE_DIR / "extension"

CHILD_PROCESSES = []


def find_chrome_path():
    """Tự động tìm kiếm đường dẫn cài đặt của Google Chrome trên hệ điều hành."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def kill_process_tree(proc: subprocess.Popen):
    """Diệt triệt để tiến trình con và toàn bộ cây tiến trình nhánh của nó trên Windows/Linux."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        else:
            proc.terminate()
            proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def cleanup():
    """Dọn dẹp dứt điểm khi tắt chương trình, tránh để lại zombie process."""
    print("\n🛑 Đang dừng toàn bộ hệ thống (Backend & WXT Dev Server)...")
    for p in CHILD_PROCESSES:
        kill_process_tree(p)
    # Xóa sạch 100% cache JSON theo link web và file âm thanh tạm thời
    try:
        cache_dir = BACKEND_DIR / "cache"
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            print("🗑️ Đã xóa sạch 100% file cache JSON tạm thời theo link web.")
    except Exception:
        pass
    print("✅ Đã giải phóng 100% tiến trình và RAM. Hẹn gặp lại!\n")


signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
atexit.register(cleanup)


def main():
    print("=" * 65)
    print("🚀 KHỞI ĐỘNG HỆ THỐNG DỊCH THUẬT & ĐỌC WEB AI (ALL-IN-ONE)")
    print("=" * 65)

    # 0. Dọn dẹp cache cũ nếu có trước khi bắt đầu
    cache_dir = BACKEND_DIR / "cache"
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)

    # 1. Khởi chạy Backend (Uvicorn FastAPI)
    print("\n[1/2] ⚙️ Đang khởi chạy Backend API (FastAPI)...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)

    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(BACKEND_DIR),
        env=env
    )
    CHILD_PROCESSES.append(backend_proc)

    time.sleep(1.5)

    # 2. Khởi chạy WXT Dev Server & Tự động mở Chrome
    print("[2/2] 🎨 Đang khởi chạy WXT Dev Server & Tự động mở Chrome...")
    dev_cmd = "npx wxt -b chrome" if sys.platform != "win32" else "npx.cmd wxt -b chrome"
    frontend_proc = subprocess.Popen(
        dev_cmd,
        cwd=str(EXTENSION_DIR),
        shell=True
    )
    CHILD_PROCESSES.append(frontend_proc)

    output_dir = EXTENSION_DIR / ".output" / "chrome-mv3-dev"

    print("\n" + "=" * 65)
    print("🎉 HỆ THỐNG ĐÃ SẴN SÀNG HOẠT ĐỘNG!")
    print("=" * 65)
    print("📍 Backend API:        http://127.0.0.1:8000")
    print("📍 Swagger API Docs:   http://127.0.0.1:8000/docs")
    print(f"📍 Extension Dev thư mục: {output_dir}")
    print("   👉 Trình duyệt Chrome sẽ tự động mở kèm tiện ích đã nạp sẵn!")
    print("   👉 Có cơ chế TỰ ĐỘNG RELOAD: Khi bạn sửa code, tiện ích tự cập nhật tức thì!")
    print("=" * 65)
    print("💡 Nhấn Ctrl + C bất cứ lúc nào để dừng toàn bộ chương trình an toàn.\n")

    # Giám sát vòng đời tiến trình
    try:
        while True:
            if backend_proc.poll() is not None:
                print("⚠️ Backend API đã dừng đột ngột.")
                break
            if frontend_proc.poll() is not None:
                print("⚠️ WXT Dev Server đã dừng đột ngột.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

