"""Adapter nối phân hệ 2D với module Audio/TTS hiện có (engine ZeroTTS, segmenter, audio_service).

Không tạo hệ TTS mới và không tạo project/segment Audio (để dự án 2D không lọt vào lịch sử Audio): chỉ gọi lại engine
và các hàm ghép/đổi tốc độ đã có, rồi lưu WAV theo từng dự án 2D. Cache theo hash: lời dẫn không đổi thì không đọc lại.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from ..engines import get_engine
from ..services import audio_service, segmenter
from . import projects, scenes, store

SPEED = 1.0


def audio_hash(engine: str, voice: str, narration: str) -> str:
    return hashlib.sha1(f"{engine}|{voice}|{SPEED}|{narration.strip()}".encode("utf-8")).hexdigest()


def scene_audio_path(pid: str, sid: str) -> Path:
    return projects.project_dir(pid) / "audio" / f"{sid}.wav"


def render_scene(sid: str, force: bool = False) -> dict:
    """Trả {'skipped': bool, 'duration': float}. Ném lỗi rõ ràng nếu thiếu giọng/engine."""
    sc = scenes.get(sid)
    pid = sc["project_id"]
    p = projects.get_project(pid)
    engine_id, voice = p["voice_engine"] or "zerotts", p["voice_id"]
    if not voice:
        raise ValueError("Dự án chưa chọn giọng đọc")
    text = sc["narration"].strip()
    if not text:
        raise ValueError(f"Cảnh {sc['idx'] + 1} chưa có lời dẫn")
    h = audio_hash(engine_id, voice, text)
    dst = scene_audio_path(pid, sid)
    if not force and sc["audio_hash"] == h and dst.exists() and sc["audio_duration"]:
        return {"skipped": True, "duration": sc["audio_duration"]}

    engine = get_engine(engine_id)
    if not engine.is_available():
        raise RuntimeError(f"Engine TTS chưa sẵn sàng: {engine.status()}")
    segs = segmenter.parse_text(text)
    if not segs:
        raise ValueError(f"Cảnh {sc['idx'] + 1}: không có nội dung đọc được")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as td:
        items = []
        for i, s in enumerate(segs):
            audio, sr = engine.synthesize(s.text, voice, normalize=True)
            if audio.size == 0:
                raise RuntimeError("Engine trả về âm thanh rỗng")
            raw = Path(td) / f"{i}.wav"
            audio_service.write_wav(raw, audio, sr)
            items.append((raw, s.pause_before, s.pause_after))
        merged, sr = audio_service.merge_with_pauses(items)
        audio_service.write_wav(dst, merged, sr)
    dur = len(merged) / sr
    with store.tx() as c:
        c.execute("UPDATE s2d_scenes SET audio_file=?, audio_hash=?, audio_duration=?, updated_at=? WHERE id=?",
                  (f"audio/{sid}.wav", h, dur, store.now(), sid))
    return {"skipped": False, "duration": dur}
