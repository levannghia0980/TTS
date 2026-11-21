# Prosody-aware Text Segmenter (PTS) — Phân đoạn văn bản tối ưu cho Đọc giọng nói (TTS)

Mô-đun nghiên cứu và thuật toán lõi phân tách văn bản đa ngôn ngữ (**Tiếng Việt – Tiếng Anh – Tiếng Trung**) đồng nhất 100% giữa trình duyệt (`TypeScript`) và máy chủ (`Python`).

---

## 1. Động lực & Phát biểu bài toán

Các hệ thống TTS theo luồng (streaming / low-latency) gặp 4 yêu cầu đối nghịch:
1. **Ràng buộc độ dài cứng ($L_{\max}$):** Mỗi mảnh văn bản gửi tới bộ tổng hợp không được vượt quá $L_{\max}$ (mặc định `120` ký tự hiệu dụng) để đảm bảo độ trễ khởi phát nhỏ và vết tô sáng (DOM highlight) gọn gàng.
2. **Bảo toàn thực thể không thể chia cắt:** URL, email, số thập phân/ngày giờ (`3.14`, `1.250.000`, `21/11/2026`), chức danh viết tắt (`PGS. TS.`, `TP.`, `Dr.`), tên viết tắt (`J. K.`), ký hiệu đánh số đầu dòng (`1. Mở đầu`) không được tách câu sai hoặc cắt ngang giữa từ.
3. **Tính tự nhiên về ngữ điệu & cú pháp:** Khi câu dài vượt $L_{\max}$, ranh giới cắt phải ưu tiên trùng với ranh giới cú pháp/ngữ điệu (dấu `; :`, `—`, `,`, trước liên từ, trước hư từ/chink) thay vì cắt ngang cụm danh từ, cụm giới từ hay từ ghép tiếng Việt.
4. **Đa ngôn ngữ đồng nhất (Code-point Lossless & Parity):** Tiếng Trung không dùng khoảng trắng phân từ và mỗi chữ Hán tương ứng ~1 âm tiết; do đó áp dụng độ dài hiệu dụng $L_{\text{eff}}(c) = \sum_{x \in c} w(x)$ với $w(x)=3.0$ cho CJK/Kana và $w(x)=1.0$ cho ký tự khác.

---

## 2. Kiến trúc 4 tầng của PTS

Mã nguồn tham chiếu Python tại [`backend/app/services/text_segmenter.py`](../../backend/app/services/text_segmenter.py) và bản TypeScript port 1-1 tại [`extension/src/content/nlp/segmenter.ts`](../../extension/src/content/nlp/segmenter.ts):

1. **Tầng 1 — Tokenization theo Unicode Category & Offset Code-Point:** Tách văn bản thành 4 loại token (`word`, `cjk`, `punct`, `space`), giữ nguyên từ ghép nối bằng gạch nối (`COVID-19`) hoặc dấu nháy (`don't`), ánh xạ chính xác UTF-16 ↔ Code Point để hỗ trợ cả emoji/ký tự toán học ngoài BMP.
2. **Tầng 2 — Nhận diện Vùng Bảo vệ (Hard & Soft Protected Spans):**
   - *Vùng cứng (cấm cắt):* URL, email, số/ngày giờ, từ viết tắt nhiều chấm (`U.S.`, `v.v.`), danh xưng (`TP.`, `PGS.`, `TS.`, `Dr.`, `Prof.`), viết tắt kèm số (`No. 5`, `Fig. 3`), chữ cái đầu tên (`J. K.`), số thứ tự đầu dòng (`1. `, `2. `).
   - *Vùng mềm (phạt nặng khi cắt bên trong):* cụm trong ngoặc `(...)` `«...»`, trích dẫn `"..."` `“...”`, chuỗi tên riêng viết hoa liên tiếp (`Nguyễn Văn An`, `New York`).
3. **Tầng 3 — Sentence Boundary Detection (SBD) dựa luật & ngoại lệ:** Phát hiện ranh giới câu có xét vùng bảo vệ cứng, tiếp nối chữ thường trong lời thoại (`"Đi thôi!" hắn nói.`), dấu đóng ngoặc và ký tự kết câu CJK không khoảng trắng (`。！？`).
4. **Tầng 4 — Tối ưu hóa toàn cục Ưu tiên Ngữ điệu bằng Quy hoạch động (Prosody-First DP):**
   Khác với bài toán ngắt dòng in ấn *Knuth–Plass* vốn cố chia đều độ rộng khiến TTS dễ "nghỉ giữa chừng vô lý" (ví dụ chia 65+60 thay vì dừng ở dấu phẩy thật), PTS sử dụng phí tách cố định $\lambda$ (`split_penalty`) kết hợp hệ số cân bằng rất nhỏ ($\alpha = 0.4$) đóng vai trò *tie-breaker* thứ cấp, lấy thang **Chinks 'n Chunks (Liberman & Church, 1992)** làm chủ đạo:

   $$J(c_1 \dots c_K) = \sum_{k=1}^{K} \left[ \lambda + \alpha \left(\frac{L_k - T}{T}\right)^2 + \beta \cdot \mathbb{I}(L_k < L_{\min}) \right] + \sum_{b} w(b), \quad \text{với } L_k \le L_{\max}$$

   - Thang chi phí $w(b)$: `; :` ($0.5$) $<$ `— –` ($1.0$) $<$ `, 、` ($1.5$) $<$ trước liên từ (`và`, `tuy nhiên`, `however`, `但是`) ($3.5$) $<$ trước hư từ/proclitic (`của`, `trong`, `of`, `at`, `在`, `把`) ($8.0$) $<$ giữa cụm từ liền ($14.0$).
   - Phạt treo hư từ/liên từ cuối chunk ($+6.0$) và phạt tách tiểu từ hậu trí khỏi từ trước (`này`, `đó`, `的`, `了`) ($+6.0$).
   - Vì $w(\text{dấu phẩy}) + \beta = 4.5 \ll w(\text{giữa cụm từ}) = 14.0$, thuật toán **không bao giờ cắt ngang cụm từ** khi trong ngưỡng $L_{\max}$ có ranh giới ngữ điệu tự nhiên.
5. **Thích ứng Đa thể loại & Đa động cơ TTS (`resolve_segmenter_config`):**
   - **Thể loại `story` (Truyện/Tiểu thuyết):** Bật `merge_short_turns` để gộp các câu thoại/cảm thán siêu ngắn liền kề trên cùng dòng (`"Hả?" "Thật sao?!"`), tăng bảo vệ trích dẫn thoại, mở rộng từ nối kể chuyện (`rồi`, `liền`, `bỗng`, `chợt`, `suddenly`, `忽然`).
   - **Thể loại `general` (Báo chí/Wikipedia/Chuyên ngành):** Tách rành mạch từng câu thông tin, tăng bảo vệ ngoặc danh pháp khoa học `(Setophaga magnolia)`, ưu tiên liên từ lập luận.
   - **Động cơ TTS (`detect_tts_engine`):** Tự động điều chỉnh $L_{\max}$ theo giới hạn và khả năng giữ ngữ điệu của từng bộ tổng hợp: **CapCut/TikTok** (`120`), **Piper VITS Offline** (`160`), **Microsoft Edge Neural** (`220`) — giảm tối đa số vết cắt ghép chắp vá giữa câu.

---

## 3. Tái lập thực nghiệm & Kiểm thử

Chạy toàn bộ các kiểm thử và đánh giá định lượng trên 3 bộ cây phụ thuộc **Universal Dependencies** (`vi_vtb-ud-test.conllu`, `en_ewt-ud-test.conllu`, `zh_gsdsimp-ud-test.conllu`):

```bash
# 1. Kiểm tra đồng nhất 100% giữa Python và TypeScript (321 ca đa ngôn ngữ)
python research/segmentation/parity_check.py

# 2. Chạy Unit Tests & Integration Tests (FastAPI + TTS Service)
python -m unittest research/segmentation/test_segmenter.py -v

# 3. Chạy Benchmark SBD, Cắt cú pháp trên cây UD và Stress Suite
python research/segmentation/evaluate.py
```

Kết quả đầy đủ sau khi chạy được lưu tại [`REPORT.md`](./REPORT.md) và [`results.json`](./results.json).
