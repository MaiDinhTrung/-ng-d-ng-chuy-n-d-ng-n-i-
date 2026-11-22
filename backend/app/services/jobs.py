"""Tác vụ nền (xuất file, tạo tự động cả văn bản). Có tiến độ, giai đoạn và hủy."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable


class Cancelled(Exception):
    pass


class JobCtx:
    """Truyền vào hàm công việc. Gọi ctx(done, total) để báo tiến độ kiểu cũ."""

    def __init__(self, job: dict):
        self.job = job
        self.cancelled = False

    def __call__(self, done: int, total: int) -> None:
        self.job["done"], self.job["total"] = done, total

    def set(self, phase: str | None = None, percent: float | None = None, detail: str | None = None) -> None:
        if phase is not None:
            self.job["phase"] = phase
        if percent is not None:
            self.job["percent"] = round(max(0.0, min(100.0, percent)), 1)
        if detail is not None:
            self.job["detail"] = detail

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()


_jobs: dict[str, dict] = {}
_ctx: dict[str, JobCtx] = {}
_lock = threading.Lock()


def start(kind: str, fn: Callable[[JobCtx], dict], **meta) -> str:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "status": "running", "phase": "", "percent": 0.0, "detail": "",
           "done": 0, "total": 0, "result": None, "error": None, "started": time.time(),
           "finished": None, **meta}
    ctx = JobCtx(job)
    with _lock:
        _jobs[jid] = job
        _ctx[jid] = ctx

    def run() -> None:
        try:
            job["result"] = fn(ctx)
            job["status"], job["percent"] = "done", 100.0
        except Cancelled:
            job["status"] = "cancelled"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "failed", str(e) or type(e).__name__
        finally:
            job["finished"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"job-{jid}").start()
    return jid


def get(jid: str) -> dict | None:
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def cancel(jid: str) -> bool:
    with _lock:
        c = _ctx.get(jid)
    if not c:
        return False
    c.cancelled = True
    return True
