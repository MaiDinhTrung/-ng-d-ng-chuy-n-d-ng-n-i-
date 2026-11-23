"""Project Manager 2D: CRUD + lịch sử chỉnh sửa. Không đụng bảng projects/segments của Audio."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import config
from . import references, store

FIELDS = ("name", "description", "topic", "script", "language", "target_audience", "video_type",
          "duration_sec", "aspect_ratio", "visual_style", "voice_engine", "voice_id")
STATUSES = ("draft", "scripting", "storyboard", "imaging", "animating", "rendering", "done", "failed")


class NotFound(KeyError):
    pass


def project_dir(pid: str) -> Path:
    return config.STUDIO2D_DIR / "projects" / pid


def _raw(pid: str) -> dict:
    rows = store.query("SELECT * FROM s2d_projects WHERE id=?", (pid,))
    if not rows:
        raise NotFound(f"Không có dự án 2D {pid}")
    return dict(rows[0])


def list_projects() -> list[dict]:
    rows = store.query("""
        SELECT p.id, p.name, p.topic, p.aspect_ratio, p.visual_style, p.status, p.created_at, p.updated_at,
               (SELECT COUNT(*) FROM s2d_project_refs l WHERE l.project_id = p.id) AS reference_count
        FROM s2d_projects p ORDER BY p.updated_at DESC""")
    return [dict(r) for r in rows]


def get_project(pid: str) -> dict:
    d = _raw(pid)
    d["references"] = references.list_for_project(pid)
    return d


def _revision(c, pid: str, kind: str, changes: dict, ts: str) -> None:
    c.execute("INSERT INTO s2d_revisions(project_id,kind,changes,created_at) VALUES(?,?,?,?)",
              (pid, kind, store.dumps(changes), ts))


def create_project(data: dict) -> dict:
    pid, ts = store.new_id(), store.now()
    cols = ["id", *FIELDS, "created_at", "updated_at"]
    vals = [pid, *[data.get(f) for f in FIELDS], ts, ts]
    with store.tx() as c:
        c.execute(f"INSERT INTO s2d_projects({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        _revision(c, pid, "create", {"name": data.get("name")}, ts)
    project_dir(pid).mkdir(parents=True, exist_ok=True)
    return get_project(pid)


def _cut(v):
    return v if not isinstance(v, str) or len(v) <= 500 else v[:500] + "…"


def update_project(pid: str, patch: dict) -> dict:
    """patch chỉ chứa trường người dùng gửi lên. Ghi lại giá trị cũ/mới của trường thật sự thay đổi."""
    cur = _raw(pid)
    changes = {k: [cur[k], v] for k, v in patch.items() if k in FIELDS and cur[k] != v}
    if changes:
        ts = store.now()
        sets = ",".join(f"{k}=?" for k in changes)
        with store.tx() as c:
            c.execute(f"UPDATE s2d_projects SET {sets}, updated_at=? WHERE id=?",
                      [*[v[1] for v in changes.values()], ts, pid])
            # Không lưu cả kịch bản dài hai lần trong lịch sử: cắt giá trị lớn.
            _revision(c, pid, "update", {k: [_cut(a), _cut(b)] for k, (a, b) in changes.items()}, ts)
    return get_project(pid)


def delete_project(pid: str) -> None:
    _raw(pid)
    with store.tx() as c:
        c.execute("DELETE FROM s2d_projects WHERE id=?", (pid,))   # liên kết + lịch sử xóa theo (CASCADE)
    shutil.rmtree(project_dir(pid), ignore_errors=True)            # thư viện tư liệu dùng chung KHÔNG bị xóa


def revisions(pid: str, limit: int = 100) -> list[dict]:
    _raw(pid)
    rows = store.query("SELECT id,kind,changes,created_at FROM s2d_revisions WHERE project_id=? ORDER BY id DESC LIMIT ?",
                       (pid, limit))
    return [{**dict(r), "changes": json.loads(r["changes"])} for r in rows]


def link_reference(pid: str, rid: str, note: str = "") -> dict:
    _raw(pid)
    references.get(rid)
    ts = store.now()
    with store.tx() as c:
        c.execute("""INSERT INTO s2d_project_refs(project_id,reference_id,note,created_at) VALUES(?,?,?,?)
                     ON CONFLICT(project_id,reference_id) DO UPDATE SET note=excluded.note""", (pid, rid, note, ts))
        c.execute("UPDATE s2d_projects SET updated_at=? WHERE id=?", (ts, pid))
        _revision(c, pid, "link_reference", {"reference_id": rid}, ts)
    return get_project(pid)


def unlink_reference(pid: str, rid: str) -> dict:
    _raw(pid)
    ts = store.now()
    with store.tx() as c:
        c.execute("DELETE FROM s2d_project_refs WHERE project_id=? AND reference_id=?", (pid, rid))
        c.execute("UPDATE s2d_projects SET updated_at=? WHERE id=?", (ts, pid))
        _revision(c, pid, "unlink_reference", {"reference_id": rid}, ts)
    return get_project(pid)
