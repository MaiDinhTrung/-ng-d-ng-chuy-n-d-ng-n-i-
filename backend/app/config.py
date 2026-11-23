"""Cấu hình ứng dụng. Không chứa bí mật; khóa API đọc từ .env (xem services/secret_store.py)."""
from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VOICESTUDIO_DATA", BACKEND_DIR / "data")).resolve()
AUDIO_DIR = DATA_DIR / "audio"          # {segment_id}.raw.wav / {segment_id}.wav
EXPORT_DIR = DATA_DIR / "exports"
VOICES_DIR = DATA_DIR / "voices"        # voice pack do người dùng thêm
DB_PATH = DATA_DIR / "studio.db"
STUDIO2D_DIR = DATA_DIR / "studio2d"    # phân hệ 2D Animation: tư liệu, ảnh, video (tách khỏi audio)
S2D_REF_DIR = STUDIO2D_DIR / "references"
S2D_THUMB_DIR = STUDIO2D_DIR / "thumbs"

for _d in (DATA_DIR, AUDIO_DIR, EXPORT_DIR, VOICES_DIR, STUDIO2D_DIR, S2D_REF_DIR, S2D_THUMB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Phải đặt trước khi import zerotts: thư mục giọng của người dùng nằm trong data/.
os.environ.setdefault("ZEROTTS_VOICES_HOME", str(VOICES_DIR))

TTS_THREADS = int(os.environ.get("VOICESTUDIO_THREADS", min(6, os.cpu_count() or 4)))

DEFAULT_PAUSES_MS = {
    "comma": 250,
    "period": 450,
    "ellipsis": 800,
    "newline": 700,
}


def find_ffmpeg() -> str | None:
    """Tìm ffmpeg: biến môi trường, PATH, rồi thư mục cài của winget."""
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe")
    hits = glob.glob(pattern, recursive=True)
    return hits[0] if hits else None
