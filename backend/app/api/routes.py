from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .. import config
from ..engines import cloning_provider, get_engine, get_engines
from ..engines.base import CloneNotSupported
from ..schemas import (AutoIn, ExportIn, GenerateIn, PreviewIn, ProjectCreate, ProjectUpdate, QuickIn,
                       ResegmentIn, SegmentCreate, SegmentPreviewText, SegmentUpdate)
from ..services import audio_service, auto_service, jobs, project_service as ps, segmenter, tts_service, voice_service

router = APIRouter(prefix="/api")


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ps.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except (ps.Invalid, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except audio_service.AudioError as e:
        raise HTTPException(422, str(e)) from e
    except CloneNotSupported as e:
        raise HTTPException(501, str(e)) from e


# ---------------- hệ thống ----------------

@router.get("/health")
def health():
    ff = audio_service.ffmpeg_path()
    return {
        "ok": True,
        "ffmpeg": {"available": bool(ff), "path": ff},
        "data_dir": str(config.DATA_DIR),
        "engines": {k: e.status() for k, e in get_engines().items()},
        "queue": tts_service.queue_size(),
    }


@router.get("/engines")
def engines():
    out = []
    for k, e in get_engines().items():
        cap = e.get_capabilities()
        out.append({"id": k, "name": e.name, "license": e.license, "status": e.status(),
                    "capabilities": cap.__dict__})
    return {"engines": out, "cloning": cloning_provider.check_availability()}


@router.post("/engines/{engine_id}/load")
def load_engine(engine_id: str):
    eng = _wrap(get_engine, engine_id) if engine_id in get_engines() else None
    if eng is None:
        raise HTTPException(404, "Không có engine")
    if hasattr(eng, "start_loading"):
        eng.start_loading()  # type: ignore[attr-defined]
    return eng.status()


@router.post("/system/pick-folder")
def pick_folder():
    """Mở hộp thoại chọn thư mục của Windows (ứng dụng chạy local nên hợp lệ)."""
    code = ("import tkinter as tk\nfrom tkinter import filedialog\n"
            "r=tk.Tk();r.withdraw();r.attributes('-topmost',True)\n"
            "print(filedialog.askdirectory(title='Chọn thư mục lưu file'))")
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300,
                           encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise HTTPException(408, "Hết thời gian chọn thư mục") from e
    if p.returncode != 0:
        raise HTTPException(500, f"Không mở được hộp thoại: {p.stderr.strip()[:200]}")
    path = p.stdout.strip()
    return {"path": path or None}


@router.get("/exports/download")
def download_export(path: str):
    p = Path(path).resolve()
    root = config.EXPORT_DIR.resolve()
    if (root not in p.parents and str(p) not in ps.EXPORTED) or not p.is_file():
        raise HTTPException(404, "Chỉ tải được file do ứng dụng vừa xuất")
    return FileResponse(p, filename=p.name)


# ---------------- giọng ----------------

@router.get("/voices")
def voices(engine: str | None = None):
    return {"voices": voice_service.list_voices(engine), "cloning": voice_service.clone_status()}


@router.get("/voices/{engine_id}/{voice_id}/preview")
def voice_preview(engine_id: str, voice_id: str):
    eng = get_engine(engine_id)
    path = eng.voice_preview_path(voice_id) if hasattr(eng, "voice_preview_path") else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "Giọng này không có file nghe thử đi kèm; dùng nút Nghe thử để tạo.")
    return FileResponse(path, media_type="audio/wav")


@router.post("/voices/import")
async def import_voice(file: UploadFile = File(...), engine: str = Form("zerotts")):
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "pack.zip"
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            names = _wrap(voice_service.import_voice_pack, engine, dst, file.filename or "pack.zip")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 - lỗi validate từ zerotts (sai model, thiếu file…)
            raise HTTPException(422, f"Voice pack không hợp lệ: {e}") from e
    return {"imported": names}


@router.post("/voices/clone")
def clone_voice():
    status = cloning_provider.check_availability()
    if not status["available"]:
        raise HTTPException(501, status["reason"])
    raise HTTPException(501, "Provider clone chưa được nối với API tải file")  # chỉ chạm khi có provider thật


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, engine: str = "zerotts"):
    try:
        _wrap(voice_service.delete_voice, engine, voice_id)
    except KeyError as e:
        raise HTTPException(400, str(e.args[0])) from e
    return {"deleted": voice_id}


# ---------------- tts ----------------

@router.post("/tts/preview")
def tts_preview(body: PreviewIn):
    try:
        wav = tts_service.preview(body.engine, body.text, body.voice, body.speed, body.normalize)
    except (RuntimeError, ValueError, audio_service.AudioError) as e:
        raise HTTPException(503 if isinstance(e, RuntimeError) else 400, str(e)) from e
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/segmenter/parse")
def parse(body: SegmentPreviewText):
    pauses = {k: v for k, v in (body.pauses.model_dump() if body.pauses else {}).items() if v is not None}
    segs = segmenter.parse_text(body.text, pauses, body.split_commas)
    return {"segments": [{"text": s.text, "pause_before": s.pause_before, "pause_after": s.pause_after} for s in segs]}


# ---------------- project ----------------

@router.post("/projects")
def create_project(body: ProjectCreate):
    return _wrap(ps.create_project, body.name, body.text, body.settings.clean() if body.settings else None)


@router.get("/projects")
def list_projects():
    return {"projects": ps.list_projects()}


@router.get("/projects/{pid}")
def get_project(pid: str):
    return _wrap(ps.get_project, pid)


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectUpdate):
    return _wrap(ps.update_project, pid, body.name, body.settings.clean() if body.settings else None,
                 body.apply_to_segments)


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    _wrap(ps.delete_project, pid)
    return {"deleted": pid}


@router.post("/projects/{pid}/resegment")
def resegment(pid: str, body: ResegmentIn):
    return _wrap(ps.resegment, pid, body.text)


@router.post("/projects/{pid}/segments")
def add_segment(pid: str, body: SegmentCreate):
    return _wrap(ps.add_segment, pid, body.after_idx, body.text)


@router.post("/projects/{pid}/generate")
def generate(pid: str, body: GenerateIn | None = None):
    body = body or GenerateIn()
    p = _wrap(ps.get_project, pid)
    segs = p["segments"]
    if body.segment_ids:
        wanted = set(body.segment_ids)
        segs = [s for s in segs if s["id"] in wanted]
    elif not body.force:
        segs = [s for s in segs if s["status"] in ("pending", "failed")]
    n = tts_service.enqueue([s["id"] for s in segs], force=body.force)
    return {"queued": n}


@router.post("/projects/{pid}/export")
def export(pid: str, body: ExportIn):
    """Kiểm tra điều kiện ngay (lỗi trả về 400), rồi chạy xuất ở nền; theo dõi qua /jobs/{id}."""
    if body.format == "mp3" and not audio_service.ffmpeg_path():
        raise HTTPException(422, "Không tìm thấy FFmpeg (cần để xuất MP3).")
    _wrap(ps.check_exportable, pid)
    jid = jobs.start("export", lambda progress: ps.export_project(
        pid, body.format, body.mode, body.output_dir, body.mp3_kbps, progress))
    return {"job_id": jid}


@router.get("/jobs/{jid}")
def get_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "Không có tác vụ (có thể máy chủ đã khởi động lại)")
    return {k: v for k, v in j.items() if k != "started"} | {"elapsed": (j["finished"] or time.time()) - j["started"]}


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    if not jobs.cancel(jid):
        raise HTTPException(404, "Không có tác vụ")
    return {"cancelling": jid}


def _start_auto(pid: str, fmt: str, output_dir: str | None, kbps: int) -> str:
    return jobs.start("auto", lambda ctx: auto_service.run(pid, fmt, output_dir, kbps, ctx), project_id=pid)


@router.post("/quick")
def quick(body: QuickIn):
    """Dán văn bản -> tự chia -> tự đọc -> tự ghép 1 file. Trả về job để theo dõi tiến độ."""
    pauses = {k: v for k, v in (body.pauses.model_dump() if body.pauses else {}).items() if v is not None}
    try:
        p = auto_service.prepare(body.text, body.voice, body.speed, body.format, pauses or None,
                                 body.split_commas, body.name, body.engine)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except (ps.Invalid, ValueError, KeyError) as e:
        raise HTTPException(400, str(e.args[0] if isinstance(e, KeyError) else e)) from e
    return {"job_id": _start_auto(p["id"], body.format, body.output_dir, body.mp3_kbps),
            "project_id": p["id"], "segments": len(p["segments"])}


@router.post("/projects/{pid}/auto")
def auto_resume(pid: str, body: AutoIn):
    """Tiếp tục/đọc lại các đoạn chưa xong của một project rồi ghép (dùng sau khi bị ngắt hoặc lỗi)."""
    _wrap(ps.get_project, pid)
    return {"job_id": _start_auto(pid, body.format, body.output_dir, body.mp3_kbps), "project_id": pid}


@router.post("/system/open-folder")
def open_folder(path: str):
    p = Path(path).resolve()
    ok_dirs = {str(Path(f).parent) for f in ps.EXPORTED}
    if str(p) not in ok_dirs and str(p) not in {str(Path(f).resolve()) for f in ps.EXPORTED}:
        raise HTTPException(400, "Chỉ mở được thư mục chứa file vừa xuất")
    target = p if p.is_dir() else p.parent
    import os
    os.startfile(str(target))  # type: ignore[attr-defined]  # Windows
    return {"opened": str(target)}


# ---------------- segment ----------------

@router.get("/segments/{sid}")
def get_segment(sid: str):
    return _wrap(ps.get_segment, sid)


@router.patch("/segments/{sid}")
def patch_segment(sid: str, body: SegmentUpdate):
    return _wrap(ps.update_segment, sid, body.model_dump(exclude_unset=True))


@router.delete("/segments/{sid}")
def delete_segment(sid: str):
    _wrap(ps.delete_segment, sid)
    return {"deleted": sid}


@router.post("/segments/{sid}/regenerate")
def regenerate(sid: str):
    _wrap(ps.get_segment, sid)
    tts_service.enqueue([sid], force=True)
    return _wrap(ps.get_segment, sid)


@router.get("/segments/{sid}/audio")
def segment_audio(sid: str):
    _wrap(ps.get_segment, sid)
    p = ps.final_path(sid)
    if not p.exists():
        raise HTTPException(404, "Đoạn chưa có âm thanh")
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/history")
def history(limit: int = 200):
    return {"items": ps.history(limit)}
