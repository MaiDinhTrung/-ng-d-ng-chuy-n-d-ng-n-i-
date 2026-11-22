"""Project + segment: lưu trữ, chia đoạn lại, xuất file."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..storage import db
from . import audio_service, segmenter

DEFAULT_SETTINGS = {
    "engine": "zerotts",
    "voice": None,
    "speed": 1.0,
    "pauses": dict(config.DEFAULT_PAUSES_MS),
    "split_commas": False,
    "normalize": True,
}


EXPORTED: set[str] = set()     # file do chính ứng dụng vừa xuất: được phép tải/mở từ giao diện


class NotFound(KeyError):
    pass


class Invalid(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex[:12]


def raw_path(seg_id: str) -> Path:
    return config.AUDIO_DIR / f"{seg_id}.raw.wav"


def final_path(seg_id: str) -> Path:
    return config.AUDIO_DIR / f"{seg_id}.wav"


def _delete_audio(seg_id: str) -> None:
    raw_path(seg_id).unlink(missing_ok=True)
    final_path(seg_id).unlink(missing_ok=True)


def seg_to_dict(r) -> dict:
    d = dict(r)
    d["has_audio"] = final_path(d["id"]).exists()
    return d


def project_row_to_dict(r) -> dict:
    d = dict(r)
    d["settings"] = {**DEFAULT_SETTINGS, **json.loads(d["settings"] or "{}")}
    return d


# ---------------- projects ----------------

def create_project(name: str, text: str, settings: dict | None = None) -> dict:
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    s["pauses"] = {**DEFAULT_SETTINGS["pauses"], **(s.get("pauses") or {})}
    pid, now = _id(), _now()
    with db.tx() as c:
        c.execute("INSERT INTO projects(id,name,source_text,settings,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (pid, name.strip() or "Dự án mới", text, json.dumps(s), now, now))
    if text.strip():
        resegment(pid, text)
    return get_project(pid)


def list_projects() -> list[dict]:
    rows = db.query("""
        SELECT p.*, COUNT(s.id) AS segment_count,
               SUM(CASE WHEN s.status='completed' THEN 1 ELSE 0 END) AS completed_count
        FROM projects p LEFT JOIN segments s ON s.project_id = p.id
        GROUP BY p.id ORDER BY p.updated_at DESC""")
    out = []
    for r in rows:
        d = project_row_to_dict(r)
        d.pop("source_text", None)
        d["completed_count"] = d["completed_count"] or 0
        out.append(d)
    return out


def get_project(pid: str) -> dict:
    rows = db.query("SELECT * FROM projects WHERE id=?", (pid,))
    if not rows:
        raise NotFound(f"Không có project {pid}")
    d = project_row_to_dict(rows[0])
    segs = db.query("SELECT * FROM segments WHERE project_id=? ORDER BY idx", (pid,))
    d["segments"] = [seg_to_dict(s) for s in segs]
    return d


def update_project(pid: str, name: str | None, settings: dict | None, apply_to_segments: list[str] | None = None) -> dict:
    p = get_project(pid)
    new = dict(p["settings"])
    if settings:
        for k, v in settings.items():
            if k == "pauses" and isinstance(v, dict):
                new["pauses"] = {**new["pauses"], **v}
            else:
                new[k] = v
    with db.tx() as c:
        c.execute("UPDATE projects SET name=?, settings=?, updated_at=? WHERE id=?",
                  (name.strip() if name else p["name"], json.dumps(new), _now(), pid))
    for field in (apply_to_segments or []):
        if field not in ("voice", "speed"):
            raise Invalid("apply_to_segments chỉ nhận 'voice' hoặc 'speed'")
        for s in p["segments"]:
            update_segment(s["id"], {field: new[field]})
    return get_project(pid)


def delete_project(pid: str) -> None:
    get_project(pid)
    ids = [r["id"] for r in db.query("SELECT id FROM segments WHERE project_id=?", (pid,))]
    with db.tx() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    for i in ids:
        _delete_audio(i)
    shutil.rmtree(config.EXPORT_DIR / project_folder_name(pid), ignore_errors=True)


def project_folder_name(pid: str) -> str:
    return pid


# ---------------- segments ----------------

def resegment(pid: str, text: str) -> dict:
    """Chia lại toàn bộ văn bản. Đoạn có text+voice trùng với đoạn cũ giữ nguyên audio."""
    p = get_project(pid)
    s = p["settings"]
    new = segmenter.parse_text(text, s["pauses"], s["split_commas"])
    old = {}
    for seg in p["segments"]:
        old.setdefault((seg["text"], seg["voice"]), []).append(seg)
    reused: set[str] = set()
    now = _now()
    with db.tx() as c:
        for i, ns in enumerate(new):
            key = (ns.text, None)
            cand = next((o for o in old.get(key, []) if o["id"] not in reused), None)
            if cand:
                reused.add(cand["id"])
                c.execute("UPDATE segments SET idx=?, pause_before=?, pause_after=?, updated_at=? WHERE id=?",
                          (i, ns.pause_before, ns.pause_after, now, cand["id"]))
            else:
                c.execute("""INSERT INTO segments(id,project_id,idx,text,voice,speed,pause_before,pause_after,status,updated_at)
                             VALUES(?,?,?,?,?,?,?,?,'pending',?)""",
                          (_id(), pid, i, ns.text, None, s["speed"], ns.pause_before, ns.pause_after, now))
        drop = [o["id"] for o in p["segments"] if o["id"] not in reused]
        for sid in drop:
            c.execute("DELETE FROM segments WHERE id=?", (sid,))
        c.execute("UPDATE projects SET source_text=?, updated_at=? WHERE id=?", (text, now, pid))
    for sid in drop:
        _delete_audio(sid)
    return get_project(pid)


def get_segment(sid: str) -> dict:
    rows = db.query("SELECT * FROM segments WHERE id=?", (sid,))
    if not rows:
        raise NotFound(f"Không có đoạn {sid}")
    return seg_to_dict(rows[0])


def update_segment(sid: str, fields: dict) -> dict:
    seg = get_segment(sid)
    allowed = {"text", "voice", "speed", "pause_before", "pause_after"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if "speed" in fields and not 0.5 <= float(fields["speed"]) <= 2.0:
        raise Invalid("Tốc độ phải trong khoảng 0.5–2.0")
    for k in ("pause_before", "pause_after"):
        if k in fields and not 0 <= int(fields[k]) <= segmenter.MAX_PAUSE_MS:
            raise Invalid(f"{k} phải trong 0–{segmenter.MAX_PAUSE_MS} ms")
    if "text" in fields:
        t = fields["text"].strip()
        if segmenter.PAUSE_TAG.search(t):
            raise Invalid("Không đặt thẻ [pause=…] trong text của đoạn; hãy dùng ô Pause before/after.")
        if not t:
            raise Invalid("Text không được rỗng")
        fields["text"] = t
    if not fields:
        return seg
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE segments SET {sets}, updated_at=? WHERE id=?", (*fields.values(), _now(), sid))
    changed_audio_inputs = ("text" in fields and fields["text"] != seg["text"]) or \
                           ("voice" in fields and fields["voice"] != seg["voice"])
    if changed_audio_inputs:
        with db.tx() as c:
            c.execute("UPDATE segments SET status='pending', error=NULL WHERE id=?", (sid,))
    elif "speed" in fields and seg["status"] == "completed" and raw_path(sid).exists():
        # Chỉ đổi tốc độ: dựng lại từ raw bằng FFmpeg, không gọi lại model.
        try:
            dur = audio_service.apply_speed(raw_path(sid), final_path(sid), float(fields["speed"]))
            with db.tx() as c:
                c.execute("UPDATE segments SET speed_applied=?, duration=? WHERE id=?",
                          (float(fields["speed"]), dur, sid))
        except audio_service.AudioError as e:
            with db.tx() as c:
                c.execute("UPDATE segments SET status='failed', error=? WHERE id=?", (str(e), sid))
    return get_segment(sid)


def add_segment(pid: str, after_idx: int | None, text: str) -> dict:
    p = get_project(pid)
    n = len(p["segments"])
    at = n if after_idx is None else max(0, min(n, after_idx + 1))
    s = p["settings"]
    now, sid = _now(), _id()
    with db.tx() as c:
        c.execute("UPDATE segments SET idx = idx + 1 WHERE project_id=? AND idx>=?", (pid, at))
        c.execute("""INSERT INTO segments(id,project_id,idx,text,voice,speed,pause_before,pause_after,status,updated_at)
                     VALUES(?,?,?,?,?,?,0,?,'pending',?)""",
                  (sid, pid, at, text.strip(), None, s["speed"], s["pauses"]["period"], now))
    return get_segment(sid)


def delete_segment(sid: str) -> None:
    seg = get_segment(sid)
    with db.tx() as c:
        c.execute("DELETE FROM segments WHERE id=?", (sid,))
        c.execute("UPDATE segments SET idx = idx - 1 WHERE project_id=? AND idx>?", (seg["project_id"], seg["idx"]))
    _delete_audio(sid)


def history(limit: int = 200) -> list[dict]:
    rows = db.query("""
        SELECT s.*, p.name AS project_name FROM segments s JOIN projects p ON p.id = s.project_id
        WHERE s.status='completed' ORDER BY s.updated_at DESC LIMIT ?""", (limit,))
    return [seg_to_dict(r) for r in rows]


# ---------------- export ----------------

def _slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "_")
    return s[:40] or "audio"


def check_exportable(pid: str) -> dict:
    p = get_project(pid)
    segs = p["segments"]
    if not segs:
        raise Invalid("Project chưa có đoạn nào")
    bad = [s for s in segs if s["status"] != "completed" or not s["has_audio"]]
    if bad:
        nums = ", ".join(str(s["idx"] + 1) for s in bad[:20])
        raise Invalid(f"Còn {len(bad)} đoạn chưa tạo xong (đoạn {nums}). Hãy tạo âm thanh trước khi xuất.")
    stale = [s for s in segs if s["speed_applied"] is None or abs(s["speed_applied"] - s["speed"]) > 1e-3]
    if stale:
        raise Invalid("Có đoạn có tốc độ chưa được áp dụng; hãy tạo lại đoạn đó.")
    return p


def export_project(pid: str, fmt: str, mode: str, output_dir: str | None, mp3_kbps: int = 192,
                   progress=None) -> dict:
    fmt = fmt.lower()
    if fmt not in ("wav", "mp3"):
        raise Invalid("Định dạng phải là wav hoặc mp3")
    if mode not in ("merged", "segments"):
        raise Invalid("mode phải là merged hoặc segments")
    p = check_exportable(pid)
    segs = p["segments"]

    out_dir = Path(output_dir).expanduser() if output_dir else config.EXPORT_DIR / project_folder_name(pid)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Invalid(f"Không tạo được thư mục: {e}") from e
    base = _slug(p["name"])
    files: list[str] = []
    duration = None
    if mode == "merged":
        dst = out_dir / f"{base}.{fmt}"
        duration = audio_service.merge_to_file(
            [(final_path(s["id"]), s["pause_before"], s["pause_after"]) for s in segs],
            dst, fmt, mp3_kbps, progress)
        files.append(str(dst))
    else:
        width = max(3, len(str(len(segs))))
        for n, s in enumerate(segs, 1):
            dst = out_dir / f"{base}_{s['idx'] + 1:0{width}d}.{fmt}"
            audio_service.convert_file(final_path(s["id"]), dst, fmt, mp3_kbps)
            files.append(str(dst))
            if progress:
                progress(n, len(segs))
    EXPORTED.update(str(Path(f).resolve()) for f in files)
    return {"files": files, "directory": str(out_dir), "format": fmt, "mode": mode, "duration": duration}
