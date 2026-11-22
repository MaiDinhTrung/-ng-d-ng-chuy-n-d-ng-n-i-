"""Hàng đợi tạo giọng chạy nền. Mỗi đoạn tạo độc lập; tạo lại 1 đoạn không đụng đoạn khác."""
from __future__ import annotations

import hashlib
import queue
import tempfile
import threading
from pathlib import Path

from .. import config
from ..engines import get_engine
from ..storage import db
from . import audio_service, project_service as ps

_q: "queue.Queue[tuple[str, bool]]" = queue.Queue()
_queued: set[str] = set()
_qlock = threading.Lock()
_worker: threading.Thread | None = None


def _hash(engine: str, voice: str | None, text: str, normalize: bool) -> str:
    return hashlib.sha1(f"{engine}|{voice}|{int(normalize)}|{text}".encode("utf-8")).hexdigest()


def start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_loop, daemon=True, name="tts-worker")
    _worker.start()
    # Đoạn 'pending' còn sót từ phiên trước không tự chạy; người dùng bấm Generate.


def enqueue(seg_ids: list[str], force: bool = False) -> int:
    n = 0
    for sid in seg_ids:
        with _qlock:
            if sid in _queued:
                continue
            _queued.add(sid)
        with db.tx() as c:
            c.execute("UPDATE segments SET status='pending', error=NULL WHERE id=?", (sid,))
        _q.put((sid, force))
        n += 1
    return n


_cancelled: set[str] = set()      # project_id đã bị hủy: đoạn đang chờ sẽ bị bỏ qua


def cancel_project(pid: str) -> None:
    _cancelled.add(pid)


def clear_cancel(pid: str) -> None:
    _cancelled.discard(pid)


def queue_size() -> int:
    with _qlock:
        return len(_queued)


def _loop() -> None:
    while True:
        sid, force = _q.get()
        try:
            _process(sid, force)
        except Exception as e:  # noqa: BLE001
            try:
                with db.tx() as c:
                    c.execute("UPDATE segments SET status='failed', error=? WHERE id=?",
                              (f"{type(e).__name__}: {e}", sid))
            except Exception:  # noqa: BLE001
                pass
        finally:
            with _qlock:
                _queued.discard(sid)


def _process(sid: str, force: bool) -> None:
    try:
        seg = ps.get_segment(sid)
    except ps.NotFound:
        return                                   # đã bị xóa khi đang chờ
    if seg["project_id"] in _cancelled:          # người dùng đã hủy: trả về pending, không đọc
        with db.tx() as c:
            c.execute("UPDATE segments SET status='pending' WHERE id=?", (sid,))
        return
    project = ps.get_project(seg["project_id"])
    st = project["settings"]
    engine = get_engine(st["engine"])
    voice = seg["voice"] or st["voice"]
    h = _hash(st["engine"], voice, seg["text"], st["normalize"])

    with db.tx() as c:
        c.execute("UPDATE segments SET status='generating', error=NULL WHERE id=?", (sid,))

    raw, final = ps.raw_path(sid), ps.final_path(sid)
    if force or seg["raw_hash"] != h or not raw.exists():
        if not engine.is_available():
            raise RuntimeError(f"Engine chưa sẵn sàng: {engine.status()}")
        audio, sr = engine.synthesize(seg["text"], voice, normalize=st["normalize"])
        if audio.size == 0:
            raise RuntimeError("Engine trả về âm thanh rỗng")
        audio_service.write_wav(raw, audio, sr)
    dur = audio_service.apply_speed(raw, final, float(seg["speed"]))

    cur = ps.get_segment(sid)  # có thể đã bị sửa trong lúc tạo
    if cur["text"] != seg["text"] or (cur["voice"] or st["voice"]) != voice:
        with db.tx() as c:
            c.execute("UPDATE segments SET status='pending' WHERE id=?", (sid,))
        return
    with db.tx() as c:
        c.execute("""UPDATE segments SET status='completed', error=NULL, raw_hash=?, speed_applied=?,
                     duration=?, updated_at=datetime('now') WHERE id=?""", (h, float(seg["speed"]), dur, sid))
    # speed có thể bị đổi trong lúc tạo: dựng lại cho khớp.
    if abs(float(cur["speed"]) - float(seg["speed"])) > 1e-3:
        d2 = audio_service.apply_speed(raw, final, float(cur["speed"]))
        with db.tx() as c:
            c.execute("UPDATE segments SET speed_applied=?, duration=? WHERE id=?", (float(cur["speed"]), d2, sid))


def preview(engine_id: str, text: str, voice: str | None, speed: float, normalize: bool = True) -> bytes:
    engine = get_engine(engine_id)
    if not engine.is_available():
        raise RuntimeError(f"Engine chưa sẵn sàng: {engine.status()}")
    audio, sr = engine.synthesize(text, voice, normalize=normalize)
    fd, tmp_raw = tempfile.mkstemp(suffix=".wav", dir=config.DATA_DIR)
    import os
    os.close(fd)
    raw = Path(tmp_raw)
    out = raw.with_suffix(".out.wav")
    try:
        audio_service.write_wav(raw, audio, sr)
        audio_service.apply_speed(raw, out, speed)
        return out.read_bytes()
    finally:
        raw.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
