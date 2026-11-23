"""Workflow Engine: mỗi công đoạn là một task độc lập, lưu trong DB (nên tiếp tục được sau khi tắt app).

Trạng thái: pending | running | completed | failed. Có tiến độ, nhật ký, retry. Mỗi handler tự bỏ qua (cache theo hash)
khi đầu vào không đổi, vì vậy sửa một cảnh chỉ chạy lại đúng công đoạn của cảnh đó.
Một worker duy nhất chạy tuần tự: tránh tranh CPU với TTS và giữ đúng thứ tự phụ thuộc.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Callable

from . import audio_bridge, characters, cost, director, imaging, projects, scenes, store, video

KINDS = ("script", "characters", "storyboard", "scene_regen", "scene_audio", "scene_clip", "render")
_worker: threading.Thread | None = None
_wake = threading.Event()
_stop = threading.Event()
_running_id: int | None = None
_cancel_current = threading.Event()
SIZE_OVERRIDE: tuple[int, int, int] | None = None     # chỉ dùng trong test để render nhỏ/nhanh


class Invalid(ValueError):
    pass


class Ctx:
    def __init__(self, tid: int):
        self.tid = tid

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        with store.tx() as c:
            c.execute("UPDATE s2d_tasks SET log=substr(log || ?, -8000), updated_at=? WHERE id=?", (line, store.now(), self.tid))

    def progress(self, p: float) -> None:
        with store.tx() as c:
            c.execute("UPDATE s2d_tasks SET progress=? WHERE id=?", (max(0.0, min(1.0, p)), self.tid))


# ---------------- hàng đợi ----------------

def enqueue(pid: str, task: str, scene_id: str | None = None, /, **params) -> int:
    """`task` là loại task; tham số riêng (vd kind=preview) đi qua **params."""
    if task not in KINDS:
        raise Invalid(f"Loại task không hợp lệ: {task}")
    dup = store.query("""SELECT id FROM s2d_tasks WHERE project_id=? AND kind=? AND IFNULL(scene_id,'')=IFNULL(?,'')
                         AND params=? AND status IN ('pending','running')""", (pid, task, scene_id, store.dumps(params)))
    if dup:
        return dup[0]["id"]
    ts = store.now()
    with store.tx() as c:
        cur = c.execute("INSERT INTO s2d_tasks(project_id,scene_id,kind,params,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (pid, scene_id, task, store.dumps(params), ts, ts))
        tid = cur.lastrowid
    _wake.set()
    return tid


def list_tasks(pid: str, limit: int = 200) -> list[dict]:
    rows = store.query("SELECT * FROM s2d_tasks WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit))
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"])
        out.append(d)
    return out[::-1]


def retry(tid: int) -> None:
    rows = store.query("SELECT status FROM s2d_tasks WHERE id=?", (tid,))
    if not rows:
        raise Invalid("Không có task")
    if rows[0]["status"] != "failed":
        raise Invalid("Chỉ thử lại được task đã lỗi")
    with store.tx() as c:
        c.execute("UPDATE s2d_tasks SET status='pending', error=NULL, progress=0, updated_at=? WHERE id=?", (store.now(), tid))
    _wake.set()


def cancel_pending(pid: str) -> int:
    with store.tx() as c:
        n = c.execute("UPDATE s2d_tasks SET status='failed', error='Đã hủy', updated_at=? WHERE project_id=? AND status='pending'",
                      (store.now(), pid)).rowcount
    return n


def recover() -> int:
    """Khởi động lại sau khi app bị đóng giữa chừng: task 'running' quay về 'pending' để chạy tiếp."""
    with store.tx() as c:
        return c.execute("UPDATE s2d_tasks SET status='pending', updated_at=? WHERE status='running'", (store.now(),)).rowcount


# ---------------- handlers ----------------

def _h_script(t: dict, ctx: Ctx) -> None:
    ctx.log("Claude viết kịch bản…")
    text = director.write_script(t["project_id"])
    projects.update_project(t["project_id"], {"script": text})
    ctx.log(f"Đã viết {len(text.split())} từ")


def _h_characters(t: dict, ctx: Ctx) -> None:
    ctx.log("Claude phân tích nhân vật…")
    created = director.extract_characters(t["project_id"])
    ctx.log(f"Tạo {len(created)} hồ sơ nhân vật mới (cần bạn xác nhận)")


def _h_storyboard(t: dict, ctx: Ctx) -> None:
    ctx.log("Claude chia cảnh và viết prompt…")
    sc = director.build_storyboard(t["project_id"])
    ctx.log(f"Tạo {len(sc)} cảnh (cần bạn duyệt storyboard)")


def _h_scene_regen(t: dict, ctx: Ctx) -> None:
    ctx.log("Claude thiết kế lại cảnh…")
    director.regenerate_scene(t["scene_id"], t["params"].get("instruction", ""))


def _h_scene_audio(t: dict, ctx: Ctx) -> None:
    r = audio_bridge.render_scene(t["scene_id"], force=bool(t["params"].get("force")))
    ctx.log("Bỏ qua: lời dẫn không đổi (dùng cache)" if r["skipped"] else f"Đã đọc xong, dài {r['duration']:.1f}s")


def _h_scene_clip(t: dict, ctx: Ctx) -> None:
    r = video.render_clip(t["scene_id"], t["params"].get("kind", "preview"), SIZE_OVERRIDE, bool(t["params"].get("force")))
    ctx.log("Bỏ qua: ảnh/chuyển động không đổi (dùng cache)" if r["skipped"] else f"Đã dựng clip {r['length']:.1f}s")


def _h_render(t: dict, ctx: Ctx) -> None:
    pid, kind = t["project_id"], t["params"].get("kind", "preview")
    scs = scenes.list_for_project(pid)
    files, hashes = [], []
    for i, s in enumerate(scs):
        ctx.progress(i / (len(scs) + 1))
        r = video.render_clip(s["id"], kind, SIZE_OVERRIDE)       # đã có cache thì trả ngay
        files.append(r["file"])
        hashes.append(r["hash"])
    r = video.assemble(pid, kind, files, hashes, SIZE_OVERRIDE, ctx)
    with store.tx() as c:
        c.execute("UPDATE s2d_projects SET status=?, updated_at=? WHERE id=?", ("done" if kind == "final" else "storyboard", store.now(), pid))
    ctx.log("Bỏ qua: không có gì thay đổi từ lần dựng trước" if r["skipped"] else f"Đã xuất {r['file']} ({r['duration']:.1f}s)")


HANDLERS: dict[str, Callable[[dict, Ctx], None]] = {
    "script": _h_script, "characters": _h_characters, "storyboard": _h_storyboard, "scene_regen": _h_scene_regen,
    "scene_audio": _h_scene_audio, "scene_clip": _h_scene_clip, "render": _h_render,
}


def _claim() -> dict | None:
    with store.tx() as c:
        r = c.execute("SELECT * FROM s2d_tasks WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE s2d_tasks SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (store.now(), r["id"]))
        d = dict(r)
    d["params"] = json.loads(d["params"])
    return d


def run_one() -> bool:
    """Chạy một task đang chờ (đồng bộ). Trả False nếu không có việc."""
    t = _claim()
    if not t:
        return False
    ctx = Ctx(t["id"])
    try:
        HANDLERS[t["kind"]](t, ctx)
        with store.tx() as c:
            c.execute("UPDATE s2d_tasks SET status='completed', progress=1, updated_at=? WHERE id=?", (store.now(), t["id"]))
    except Exception as e:  # noqa: BLE001
        ctx.log(traceback.format_exc(limit=2).strip().splitlines()[-1])
        with store.tx() as c:
            c.execute("UPDATE s2d_tasks SET status='failed', error=?, updated_at=? WHERE id=?",
                      (f"{type(e).__name__}: {e}"[:600], store.now(), t["id"]))
    return True


def _loop() -> None:
    while not _stop.is_set():
        try:
            if not run_one():
                _wake.wait(1.0)
                _wake.clear()
        except Exception:  # noqa: BLE001
            time.sleep(1.0)


def start_worker() -> None:
    global _worker
    store.ensure_schema()
    recover()
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, daemon=True, name="s2d-worker")
    _worker.start()


# ---------------- kế hoạch sản xuất ----------------

def produce(pid: str, kind: str = "preview") -> dict:
    """Start Production. Giai đoạn 1: nếu chưa có storyboard thì để Claude chuẩn bị (kịch bản, nhân vật, cảnh) rồi dừng chờ
    người dùng duyệt. Giai đoạn 2 (đã duyệt): đọc audio, dựng clip, ghép video; mọi bước tự bỏ qua nếu không đổi."""
    if kind not in ("preview", "final"):
        raise Invalid("kind phải là preview hoặc final")
    p = projects.get_project(pid)
    cost.ensure_meta(pid)
    scs = scenes.list_for_project(pid)
    if not scs:
        ids = []
        if not p["script"].strip():
            ids.append(enqueue(pid, "script"))
        ids.append(enqueue(pid, "characters"))
        ids.append(enqueue(pid, "storyboard"))
        return {"phase": "planning", "tasks": ids,
                "message": "Agent đang viết kịch bản/nhân vật/storyboard. Hãy xác nhận nhân vật và duyệt storyboard rồi bấm Start lần nữa."}
    meta = store.query("SELECT storyboard_approved FROM s2d_meta WHERE project_id=?", (pid,))[0]
    problems = []
    if not meta["storyboard_approved"]:
        problems.append("Storyboard chưa được duyệt")
    unconfirmed = [c["name"] for c in characters.list_for_project(pid) if not c["confirmed"]]
    if unconfirmed:
        problems.append("Nhân vật chưa xác nhận: " + ", ".join(unconfirmed))
    missing = [str(s["idx"] + 1) for s in scs if not s["image_gen_id"]]
    if missing:
        problems.append("Cảnh chưa có ảnh: " + ", ".join(missing))
    if problems:
        raise Invalid("; ".join(problems))
    ids = []
    for s in scs:
        if p["voice_id"] and s["narration"].strip():
            ids.append(enqueue(pid, "scene_audio", s["id"]))
        ids.append(enqueue(pid, "scene_clip", s["id"], kind=kind))
    ids.append(enqueue(pid, "render", None, kind=kind))
    with store.tx() as c:
        c.execute("UPDATE s2d_projects SET status=?, updated_at=? WHERE id=?", ("rendering", store.now(), pid))
    return {"phase": "producing", "tasks": ids, "message": f"Đã xếp {len(ids)} công đoạn ({kind})."}
