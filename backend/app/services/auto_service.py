"""Chế độ tạo nhanh: văn bản -> chia đoạn -> đọc từng đoạn -> ghép thành 1 file. Chạy nền, có tiến độ."""
from __future__ import annotations

import time
from datetime import datetime

from ..engines import get_engine
from ..storage import db
from . import audio_service, jobs, project_service as ps, tts_service

GEN_SHARE = 92.0      # % tiến độ dành cho bước đọc; phần còn lại là ghép


def _name_from(text: str) -> str:
    head = " ".join(text.split())[:24].strip()   # ngắn để tên file còn giữ phần ngày giờ (slug cắt ở 40 ký tự)
    return f"{head}… ({datetime.now():%d/%m %H:%M})" if head else f"Tạo nhanh {datetime.now():%d/%m %H:%M}"


def _snapshot(pid: str) -> list[tuple[str, int, str | None]]:
    rows = db.query("SELECT status, length(text) AS n, error FROM segments WHERE project_id=?", (pid,))
    return [(r["status"], r["n"], r["error"]) for r in rows]


def prepare(text: str, voice: str, speed: float, fmt: str, pauses: dict | None, split_commas: bool,
            name: str | None, engine_id: str = "zerotts") -> dict:
    """Kiểm tra điều kiện rồi tạo project + chia đoạn (đồng bộ, vài giây cho văn bản 1 giờ)."""
    if not text.strip():
        raise ps.Invalid("Chưa có văn bản")
    if not voice:
        raise ps.Invalid("Hãy chọn giọng đọc")
    eng = get_engine(engine_id)
    if not eng.is_available():
        st = eng.status()
        raise RuntimeError("Model đang nạp, vui lòng đợi vài giây rồi thử lại." if st["state"] == "loading"
                           else f"Engine chưa sẵn sàng: {st}")
    if (fmt == "mp3" or abs(speed - 1.0) > 1e-3) and not audio_service.ffmpeg_path():
        raise ps.Invalid("Cần FFmpeg cho MP3 hoặc đổi tốc độ (winget install Gyan.FFmpeg).")
    settings = {"engine": engine_id, "voice": voice, "speed": speed, "split_commas": split_commas}
    if pauses:
        settings["pauses"] = pauses
    p = ps.create_project(name or _name_from(text), text, settings)
    if not p["segments"]:
        ps.delete_project(p["id"])
        raise ps.Invalid("Không tìm thấy nội dung đọc được trong văn bản")
    return p


def run(pid: str, fmt: str, output_dir: str | None, mp3_kbps: int, ctx: jobs.JobCtx) -> dict:
    """Đọc mọi đoạn chưa xong (tự thử lại đoạn lỗi 1 lần), rồi ghép. Gọi lại được để tiếp tục."""
    tts_service.clear_cancel(pid)
    t0 = time.time()
    for attempt in (1, 2):
        todo = [s["id"] for s in ps.get_project(pid)["segments"] if s["status"] != "completed"]
        if todo:
            tts_service.enqueue(todo, force=False)
        ctx.set(phase="generate")
        while True:
            if ctx.cancelled:
                tts_service.cancel_project(pid)
                raise jobs.Cancelled()
            snap = _snapshot(pid)
            total_w = sum(n for _, n, _ in snap) or 1
            done_w = sum(n for st, n, _ in snap if st == "completed")
            n_done = sum(st == "completed" for st, _, _ in snap)
            ctx.set(percent=GEN_SHARE * done_w / total_w,
                    detail=f"Đang đọc {n_done}/{len(snap)} đoạn")
            ctx.job["done"], ctx.job["total"] = n_done, len(snap)
            if done_w > 0:
                el = time.time() - t0
                ctx.job["eta_s"] = el * (total_w - done_w) / done_w
            if not any(st in ("pending", "generating") for st, _, _ in snap):
                break
            time.sleep(0.8)
        failed = [(st, err) for st, _, err in _snapshot(pid) if st == "failed"]
        if not failed:
            break
        if attempt == 2:
            raise RuntimeError(f"{len(failed)} đoạn đọc lỗi: {failed[0][1]}")
        for s in ps.get_project(pid)["segments"]:           # thử lại đoạn lỗi 1 lần
            if s["status"] == "failed":
                tts_service.enqueue([s["id"]], force=True)

    ctx.set(phase="merge", percent=GEN_SHARE, detail="Đang ghép thành 1 file…")
    ctx.job["eta_s"] = None

    def merge_progress(done: int, total: int) -> None:
        ctx.set(percent=GEN_SHARE + (100 - GEN_SHARE) * done / max(1, total), detail=f"Đang ghép {done}/{total} đoạn")

    result = ps.export_project(pid, fmt, "merged", output_dir, mp3_kbps, merge_progress)
    result["project_id"] = pid
    return result
