# 2D Animation Production Agent — tài liệu kỹ thuật

## Trạng thái từng giai đoạn
| Giai đoạn | Trạng thái | Kiểm chứng |
|---|---|---|
| 1. Project Manager, Reference Library, khung UI | Xong | pytest + build |
| 2. Claude client, Visual Director, Character Sheet, Storyboard | Xong về mã; **chưa gọi Claude thật** | pytest với máy chủ Claude **giả lập** |
| 3. Image Generation Manager | Kiến trúc adapter xong; **chưa có nhà cung cấp thật** (chờ bạn chọn + khóa) | pytest với provider test double. Người dùng tự tải ảnh cho cảnh được |
| 4. Animation, nối Audio, FFmpeg, xuất MP4 | Xong | pytest + e2e thật (TTS ZeroTTS + FFmpeg) |
| 5. Cost Manager, Workflow Engine | Xong | pytest |

## Chưa kiểm chứng / chưa làm (đọc kỹ)
- **Claude API thật:** chưa có `ANTHROPIC_API_KEY`, chưa từng gọi API Anthropic. Prompt, định dạng JSON và tên model (`ANTHROPIC_MODEL`, mặc định `claude-sonnet-5-5`) chưa được thử với dịch vụ thật; có thể phải chỉnh prompt sau lần chạy thật đầu tiên. `verified` luôn là `false`.
- **Giá token:** không hard-code. Chưa đặt `ANTHROPIC_PRICE_IN_PER_MTOK`/`ANTHROPIC_PRICE_OUT_PER_MTOK` thì token vẫn được đếm nhưng chi phí = null và ngân sách không áp dụng được cho Claude.
- **Image/Video provider:** chưa có adapter nào; không tạo ảnh bằng AI. Chưa có video generation API; chuyển động hiện chỉ bằng FFmpeg.
- **Chưa có:** parallax (cần ảnh tách lớp), hiệu ứng âm thanh (SFX), Dashboard tổng, Character Library xuyên dự án (nhân vật hiện thuộc từng dự án), kiểm tra tự động độ nhất quán nhân vật bằng thị giác.
- **Giới hạn:** ghép video dùng chuỗi `xfade` trong một lệnh FFmpeg; dự án hàng trăm cảnh có thể chạm giới hạn độ dài lệnh. Cảnh "cut" thực chất là chuyển cảnh 2 khung hình. UI chưa được mở bằng trình duyệt để thao tác thủ công (chỉ `tsc`/build).

## Nguyên tắc tách biệt với Audio
- Mã 2D: `backend/app/studio2d/`, `frontend/src/studio2d/`. Không module Audio nào import nó.
- Dùng chung hạ tầng: `config`, `storage.db`, `services/secret_store.py`, và (qua `audio_bridge.py`) engine TTS + `segmenter` + `audio_service` hiện có.
- Bảng riêng tiền tố `s2d_`; bảng Audio không đổi. Audio bridge gọi thẳng engine, **không tạo project/segment Audio**, nên dự án 2D không lọt vào My Projects / Audio History.
- Dữ liệu file: `backend/data/studio2d/{references,thumbs,projects/<id>/{images,audio,clips,renders}}`.

## Luồng sản xuất
1. Tạo dự án, nhập chủ đề/kịch bản, gắn tư liệu (Reference Library), chọn giọng.
2. **Start Production** lần đầu (chưa có cảnh): task `script` (nếu thiếu kịch bản) → `characters` → `storyboard` (Claude). Dừng chờ người dùng.
3. Người dùng sửa/xác nhận Character Sheet, sửa/duyệt Storyboard, thêm ảnh từng cảnh (tự tải hoặc qua provider).
4. **Start Production** lần hai: `scene_audio` (TTS qua adapter) → `scene_clip` (FFmpeg) → `render` (ghép + phụ đề + nhạc nền). Preview nhỏ nhanh; "Xuất MP4 chất lượng cao" = 1920×1080 / 1080×1920 / 1080×1080 tùy tỉ lệ.
5. Chặn bắt đầu nếu: storyboard chưa duyệt, nhân vật chưa xác nhận, cảnh thiếu ảnh. Mọi sửa cảnh bỏ trạng thái "đã duyệt".

## Workflow Engine (`workflow.py`)
- Task lưu trong `s2d_tasks`: `pending|running|completed|failed`, tiến độ, nhật ký, số lần thử. Một worker tuần tự (tránh tranh CPU với TTS).
- Khởi động lại: task `running` → `pending` và chạy tiếp (`recover()`).
- Retry từng task; hủy hàng chờ; chống trùng task cùng loại/cảnh.
- **Không chạy lại phần không đổi:** audio theo hash(engine, giọng, lời dẫn); clip theo hash(ảnh, chuyển động, hiệu ứng, thời lượng, kích thước); bản ghép theo hash(các clip, chuyển cảnh, audio, phụ đề, nhạc nền). Cache Claude theo hash đầu vào (`s2d_llm_cache`).

## Character consistency
Hồ sơ nhân vật (`s2d_characters`) được chèn nguyên văn bởi `director.compose_image_request()` vào prompt mọi cảnh có nhân vật đó, kèm ảnh tham chiếu của nhân vật (chỉ đính kèm khi provider hỗ trợ reference image). Sửa hồ sơ → bỏ xác nhận. Prompt cuối xem được trước khi gửi (`GET /scenes/{id}/image-request`).

## Image Generation Manager (`imaging.py`)
`ImageProvider` (ABC: `is_configured`, `capabilities`, `generate`) + `register()`. Thêm nhà cung cấp = viết 1 lớp và đăng ký; không sửa lõi. Mỗi lần tạo lưu: prompt, negative prompt, ảnh tham chiếu, provider, model, tham số, thời gian, chi phí, trạng thái, lỗi (kể cả lần thất bại) trong `s2d_generations`.

## Khóa API và chi phí
- Khóa chỉ đọc từ biến môi trường/`.env` ở backend (`services/secret_store.py`); API chỉ trả cờ "đã cấu hình" + bản che.
- `cost.py`: ghi token/chi phí (`s2d_usage`), ước tính trước khi chạy (`GET /projects/{id}/estimate`, ước lượng thô), ngân sách theo dự án, cảnh báo ≥80%, chặn gọi API trả phí khi đã vượt.

## API chính (`/api/2d`)
`status` · `projects` (+`/meta`, `/characters`, `/scenes`, `/references`, `/revisions`, `/stage/{script|characters|storyboard}`, `/produce`, `/tasks`, `/renders`, `/cost`, `/budget`, `/bgm`, `/estimate`, `/storyboard/approve`) · `characters/{id}` · `scenes/{id}` (+`/move`, `/regenerate`, `/image`, `/images`, `/images/generate`, `/image/select`, `/image-request`, `/audio`) · `tasks/{id}/retry` · `renders/{id}/file` · `generations/{id}/file` · `references` · `image-providers` · `cost`.
Mã lỗi: 412 thiếu khóa Claude, 409 chưa có provider ảnh, 402 vượt ngân sách, 502 lỗi Claude/FFmpeg.

## Kiểm thử
`cd backend; .venv\Scripts\python -m pytest tests -q` — gồm `test_studio2d.py` (GĐ1), `test_studio2d_pipeline.py` (GĐ2–5, FFmpeg thật; Claude và provider ảnh là test double) và các test Audio cũ.
