# 🎙️ Tiện Ích Trình Duyệt Đọc Văn Bản (Text-to-Speech) & Dịch Thuật Tại Chỗ

Hệ sinh thái đọc văn bản song ngữ thông minh tích hợp **Chrome Extension (Manifest V3)** và **Máy chủ Python FastAPI Backend**, hỗ trợ đa tầng giọng đọc (CapCut/TikTok, Microsoft Edge-TTS, Piper VITS Offline) và dịch thuật ngữ cảnh tức thì qua Google Gemini.

---

## 🌟 Tính Năng Nổi Bật

1. **Khởi động tức thì (Zero-Wait Startup):**
   * Tự động phát hiện ngôn ngữ trang web (`zh`, `en`, `ja`, `ko`, `vi`...).
   * Ưu tiên tạo âm thanh bản gốc cho các câu đầu tiên trong `< 0.4s` trước khi kích hoạt luồng dịch nền.
2. **Hàng đợi âm thanh kép (Double Buffering Audio Queue):**
   * Quản lý 2 luồng âm thanh độc lập (`orig` - Bản gốc và `vi` - Bản dịch tiếng Việt).
   * Chuyển đổi trạng thái mượt mà 1-Click: Tự động dọn sạch hàng đợi tàn dư, đưa con trỏ về câu số 1 (`s-0`) của trạng thái đích và đổi màu bôi vàng chính xác.
3. **Dịch thuật ngữ cảnh chuyên môn (Contextual Translation):**
   * Tích hợp Google Gemini Flash-Lite với bộ Prompt chuẩn mực.
   * Ưu tiên số 1: Giữ chuẩn danh pháp khoa học/thuật ngữ chuyên môn trong ngoặc đơn (ví dụ: *Setophaga magnolia*).
   * Ưu tiên số 2: Diễn đạt tiếng Việt hiện đại, mạch lạc, tránh lạm dụng từ Hán Việt cổ tối nghĩa (dịch `Etymology` thành "Nguồn gốc tên gọi" thay vì "Từ nguyên").
   * Bộ lọc 4 lớp loại bỏ hoàn toàn số chú thích `[1]`, `[13]`, `[edit]`, `[sửa]` và chặn triệt để chữ Hán/Anh lọt vào luồng đọc tiếng Việt.
4. **Bộ nhớ đệm đa tầng theo URL (Ephemeral Cache Manager):**
   * Quản lý cache JSON và file MP3 theo mã băm chuẩn hóa của link web (`url_hash`).
   * Tái sử dụng tức thì bản dịch và âm thanh đã tạo khi chuyển đổi qua lại giữa Gốc $\leftrightarrow$ Dịch hoặc mở lại trang web mà không tốn request API.
   * Tự động dọn sạch 100% rác bộ nhớ đệm khi tắt tiến trình Python (`atexit`).
5. **Kiềng 3 chân công nghệ giọng đọc (Hybrid TTS):**
   * **CapCut / TikTok TTS:** Giọng nam trầm ấm review (`BV074_streaming`), giọng nữ truyền cảm (`BV075_streaming`).
   * **Microsoft Edge-TTS:** Giọng phát thanh viên chuẩn mực (`vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`).
   * **Piper VITS (ONNX Runtime):** Giọng đọc nữ miền Bắc (*Ngọc Huyền New*) chạy ngoại tuyến 100% không cần kết nối Internet.

---

## 🏗️ Kiến Trúc Hệ Thống

```
texttospeech/
├── backend/                  # FastAPI Python Backend
│   ├── app/
│   │   ├── api/v1/           # REST API endpoints (session, tts, settings)
│   │   ├── constants/        # Danh mục giọng đọc đa ngôn ngữ
│   │   ├── core/             # Cấu hình Settings và biến môi trường
│   │   └── services/         # Logic lõi: Session, TTS, Translation, Cache
│   ├── requirements.txt      # Thư viện Python phụ thuộc
│   └── run.py                # Điểm khởi chạy FastAPI Server (Port 8000)
├── extension/                # Chrome Extension (WXT + TypeScript + Vite)
│   ├── entrypoints/          # Background script, Content script, Popup
│   ├── src/
│   │   ├── content/          # Trích xuất DOM (Walker, Cleaner, Injector)
│   │   └── sidepanel/        # Audio Queue Player (Double Buffering)
│   ├── package.json          # Node dependencies
│   └── wxt.config.ts         # Cấu hình WXT Build Manifest V3
├── .env.example              # File mẫu cấu hình môi trường
└── README.md                 # Hướng dẫn chi tiết
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Dự Án

### 1. Chuẩn bị Môi Trường
* **Python:** Phiên bản 3.10 hoặc 3.11+.
* **Node.js:** Phiên bản 18+ (kèm npm).
* **Trình duyệt:** Google Chrome, Cốc Cốc, Brave hoặc Microsoft Edge.

---

### 2. Cài Đặt và Khởi Chạy Backend (Python)

1. Mở Terminal / PowerShell tại thư mục `backend/`:
   ```bash
   cd backend
   ```

2. Tạo và kích hoạt môi trường ảo (Khuyên dùng):
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Cài đặt các thư viện cần thiết:
   ```bash
   pip install -r requirements.txt
   ```

4. Cấu hình file môi trường `.env`:
   * Sao chép file `.env.example` ở thư mục gốc thành file `.env` bên trong thư mục `backend/`:
     ```bash
     cp ../.env.example .env
     ```
   * Mở file `.env` và điền khóa **Gemini API Key** của bạn:
     ```env
     GEMINI_API_KEY=your_gemini_api_key_here
     GEMINI_MODEL=gemini-3.1-flash-lite
     SELECTED_VOICE=BV074_streaming
     ```

5. Khởi chạy máy chủ Backend:
   ```bash
   python run.py
   ```
   * Máy chủ sẽ chạy tại: `http://127.0.0.1:8000`
   * Tài liệu API Swagger UI: `http://127.0.0.1:8000/docs`

---

### 3. Build & Cài Đặt Extension Trên Trình Duyệt

1. Mở Terminal tại thư mục `extension/`:
   ```bash
   cd extension
   ```

2. Cài đặt các gói npm:
   ```bash
   npm install
   ```

3. Đóng gói tiện ích:
   ```bash
   npm run build
   ```
   * Thư mục build Manifest V3 sẽ được tạo tại: `extension/.output/chrome-mv3`

4. Nạp tiện ích vào Google Chrome:
   * Mở trình duyệt Chrome và truy cập đường dẫn: `chrome://extensions/`
   * Bật công tắc **Chế độ dành cho nhà phát triển (Developer mode)** ở góc trên bên phải.
   * Bấm nút **Tải tiện ích đã giải nén (Load unpacked)**.
   * Chọn thư mục: `d:\V_kì_I\texttospeech\extension\.output\chrome-mv3`.

---

## 📖 Hướng Dẫn Sử Dụng Thực Tế

1. **Bật đọc trang web:**
   * Mở bất kỳ bài viết báo chí, Wikipedia hoặc truyện chữ nào (tiếng Anh, Trung, Việt...).
   * Bấm nút **🎙️ Bật đọc trang này** trên thanh điều khiển nổi (Floating Player) ở góc dưới bên phải màn hình.
2. **Nghe câu nào bôi vàng câu đó:**
   * Tiện ích tự động bôi vàng câu/vế câu đang phát âm thanh và cuộn mượt màn hình theo nhịp đọc.
   * Rê chuột vào bất kỳ vế câu nào, bấm nút ▶ nhỏ xuất hiện bên cạnh để nghe ngay đúng câu đó.
3. **Chuyển đổi ngôn ngữ (Gốc $\leftrightarrow$ Dịch):**
   * Bấm nút **`🎙️ Gốc` / `🇻🇳 Dịch (VI)`** trên thanh nổi.
   * Toàn bộ chữ trên web sẽ lập tức đổi sang tiếng Việt hoặc khôi phục tiếng gốc.
   * Âm thanh sẽ được chuyển sang giọng tương ứng và tự động phát từ câu đầu tiên (`s-0`) của trạng thái đó.
4. **Tùy chỉnh giọng đọc:**
   * Bấm biểu tượng bánh răng **⚙️** trên thanh nổi để mở Popup cài đặt.
   * Lựa chọn giữa các giọng đọc CapCut, Microsoft Edge Neural hoặc Piper VITS Offline.

---

## 🛡️ Bản Quyền & Giấy Phép
Dự án được phát triển phục vụ mục đích học thuật và nghiên cứu công nghệ Text-to-Speech & Translation.
Mọi đóng góp và báo lỗi xin vui lòng tạo Issue trên GitHub Repository.

