"""Storyboard: cảnh (thẻ), chỉnh sửa, thêm/xóa/sắp xếp, duyệt. Sửa một cảnh không đụng cảnh khác."""
from __future__ import annotations

import json

from . import characters, cost, references, store

MOVEMENTS = ("static", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "shake")
TRANSITIONS = ("cut", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright", "fadeblack", "circleopen")
EFFECTS = ("none", "vignette", "warm", "cool", "flash")
TEXT_FIELDS = ("title", "narration", "environment", "visual_description", "camera_angle", "character_action", "lighting",
               "image_prompt", "negative_prompt")
EDITABLE = (*TEXT_FIELDS, "camera_movement", "duration", "transition", "effect", "character_ids", "reference_ids")
# Sửa các trường này làm ảnh/âm thanh/clip cũ có thể lỗi thời (so hash khi chạy), và bắt duyệt lại storyboard.


class NotFound(KeyError):
    pass


def _d(r) -> dict:
    d = dict(r)
    for k in ("character_ids", "reference_ids"):
        d[k] = json.loads(d[k] or "[]")
    d["has_image"] = bool(d["image_gen_id"])
    d["has_audio"] = bool(d["audio_file"])
    return d


def get(sid: str) -> dict:
    rows = store.query("SELECT * FROM s2d_scenes WHERE id=?", (sid,))
    if not rows:
        raise NotFound(f"Không có cảnh {sid}")
    return _d(rows[0])


def list_for_project(pid: str) -> list[dict]:
    return [_d(r) for r in store.query("SELECT * FROM s2d_scenes WHERE project_id=? ORDER BY idx", (pid,))]


def clean(data: dict, pid: str) -> dict:
    """Chuẩn hóa/kiểm tra dữ liệu cảnh (dùng cho cả dữ liệu từ Claude lẫn từ người dùng)."""
    out: dict = {}
    for k in TEXT_FIELDS:
        if k in data and data[k] is not None:
            out[k] = str(data[k]).strip()
    if "camera_movement" in data and data["camera_movement"] is not None:
        out["camera_movement"] = data["camera_movement"] if data["camera_movement"] in MOVEMENTS else "static"
    if "transition" in data and data["transition"] is not None:
        out["transition"] = data["transition"] if data["transition"] in TRANSITIONS else "fade"
    if "effect" in data and data["effect"] is not None:
        out["effect"] = data["effect"] if data["effect"] in EFFECTS else "none"
    if "duration" in data and data["duration"] is not None:
        try:
            out["duration"] = min(60.0, max(1.0, float(data["duration"])))
        except (TypeError, ValueError):
            out["duration"] = 5.0
    if "character_ids" in data and data["character_ids"] is not None:
        known = {c["id"] for c in characters.list_for_project(pid)}
        out["character_ids"] = [i for i in data["character_ids"] if i in known]
    if "reference_ids" in data and data["reference_ids"] is not None:
        ok = []
        for i in data["reference_ids"]:
            try:
                references.get(i)
                ok.append(i)
            except references.NotFound:
                pass
        out["reference_ids"] = ok
    return out


def _unapprove(c, pid: str) -> None:
    c.execute("INSERT OR IGNORE INTO s2d_meta(project_id) VALUES(?)", (pid,))
    c.execute("UPDATE s2d_meta SET storyboard_approved=0 WHERE project_id=?", (pid,))


def insert(pid: str, data: dict, after_idx: int | None = None) -> dict:
    d = clean(data, pid)
    sid, ts = store.new_id(), store.now()
    with store.tx() as c:
        n = c.execute("SELECT COUNT(*) FROM s2d_scenes WHERE project_id=?", (pid,)).fetchone()[0]
        pos = n if after_idx is None else max(0, min(n, after_idx + 1))
        c.execute("UPDATE s2d_scenes SET idx=idx+1 WHERE project_id=? AND idx>=?", (pid, pos))
        cols = [k for k in d]
        vals = [store.dumps(v) if isinstance(v, list) else v for v in d.values()]
        c.execute(f"INSERT INTO s2d_scenes(id,project_id,idx,created_at,updated_at{''.join(',' + k for k in cols)}) "
                  f"VALUES(?,?,?,?,?{',?' * len(cols)})", (sid, pid, pos, ts, ts, *vals))
        _unapprove(c, pid)
    return get(sid)


def replace_all(pid: str, items: list[dict]) -> list[dict]:
    """Thay toàn bộ storyboard (khi Claude tạo lại). Xóa ảnh/âm thanh gắn với cảnh cũ khỏi cảnh, không xóa tư liệu."""
    ts = store.now()
    with store.tx() as c:
        c.execute("DELETE FROM s2d_scenes WHERE project_id=?", (pid,))
        for i, it in enumerate(items):
            d = clean(it, pid)
            cols = list(d)
            vals = [store.dumps(v) if isinstance(v, list) else v for v in d.values()]
            c.execute(f"INSERT INTO s2d_scenes(id,project_id,idx,created_at,updated_at{''.join(',' + k for k in cols)}) "
                      f"VALUES(?,?,?,?,?{',?' * len(cols)})", (store.new_id(), pid, i, ts, ts, *vals))
        _unapprove(c, pid)
    return list_for_project(pid)


def update(sid: str, patch: dict) -> dict:
    cur = get(sid)
    d = clean({k: v for k, v in patch.items() if k in EDITABLE}, cur["project_id"])
    if d:
        sets = ",".join(f"{k}=?" for k in d)
        vals = [store.dumps(v) if isinstance(v, list) else v for v in d.values()]
        with store.tx() as c:
            c.execute(f"UPDATE s2d_scenes SET {sets}, updated_at=? WHERE id=?", [*vals, store.now(), sid])
            _unapprove(c, cur["project_id"])
    return get(sid)


def delete(sid: str) -> None:
    cur = get(sid)
    with store.tx() as c:
        c.execute("DELETE FROM s2d_scenes WHERE id=?", (sid,))
        c.execute("UPDATE s2d_scenes SET idx=idx-1 WHERE project_id=? AND idx>?", (cur["project_id"], cur["idx"]))
        _unapprove(c, cur["project_id"])


def move(sid: str, direction: int) -> list[dict]:
    cur = get(sid)
    other = store.query("SELECT id FROM s2d_scenes WHERE project_id=? AND idx=?", (cur["project_id"], cur["idx"] + direction))
    if other:
        with store.tx() as c:
            c.execute("UPDATE s2d_scenes SET idx=? WHERE id=?", (cur["idx"], other[0]["id"]))
            c.execute("UPDATE s2d_scenes SET idx=? WHERE id=?", (cur["idx"] + direction, sid))
            _unapprove(c, cur["project_id"])
    return list_for_project(cur["project_id"])


def set_approved(pid: str, value: bool) -> None:
    cost.ensure_meta(pid)
    if value and not list_for_project(pid):
        raise ValueError("Chưa có cảnh nào để duyệt")
    with store.tx() as c:
        c.execute("UPDATE s2d_meta SET storyboard_approved=? WHERE project_id=?", (int(value), pid))
