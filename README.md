# Local AI Voice Studio (Vietnamese TTS)

Ứng dụng web chạy 100% local: React + Vite + Tailwind (frontend), FastAPI (backend), ZeroTTS (ONNX, CPU), FFmpeg.

## Chạy
```powershell
.\run.ps1          # build frontend nếu cần, mở http://127.0.0.1:8000
```
Phát triển frontend: `cd frontend; npm run dev` (http://localhost:5173, proxy sang :8000).

## Yêu cầu
Python 3.10+, Node 20+, FFmpeg (`winget install Gyan.FFmpeg`; tự tìm trong PATH hoặc thư mục winget, hoặc đặt `FFMPEG_PATH`).
Lần đầu chạy model tải ~900MB từ Hugging Face (chỉ tải model, không gửi văn bản đi đâu).

## Kiểm thử
```powershell
cd backend
.\.venv\Scripts\python -m pytest tests -q          # chia đoạn, khoảng lặng, tốc độ, MP3
.\.venv\Scripts\python tests\e2e_live.py           # cần server đang chạy; dùng model thật
```

## Cấu trúc
- `backend/app/engines/` — `TTSProvider`, `VoiceCloningProvider`, adapter ZeroTTS; thêm engine mới tại đây.
- `backend/app/services/` — segmenter (chia đoạn + `[pause=ms]`), audio (ghép bằng mẫu 0 thật, atempo, MP3), project, tts (hàng đợi), voice.
- `backend/data/` — `studio.db` (metadata), `audio/` (WAV từng đoạn), `exports/`, `voices/`.

## Giới hạn đã biết
- ZeroTTS không có tham số tốc độ → tốc độ áp dụng bằng FFmpeg `atempo` sau khi tạo.
- ZeroTTS 0.1.x không có voice encoder → **không clone từ file ghi âm**; UI hiển thị "Chưa có engine clone tương thích". Chỉ nạp được voice pack `.zip` có sẵn.
- Giấy phép: mã + trọng số MIT, nhưng model card ghi giọng đi kèm "for evaluation and demos" và nên công khai là giọng tổng hợp. Cân nhắc trước khi dùng thương mại.
- Bản vá UTF-8 cho `zerotts.voices.load_voice_dir` (bug đọc `meta.json` bằng cp1252 trên Windows) nằm trong `engines/zerotts_engine.py`.
