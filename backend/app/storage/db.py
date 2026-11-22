"""SQLite chỉ lưu metadata. Âm thanh nằm ở data/audio/*.wav, không lưu BLOB."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from .. import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    text TEXT NOT NULL,
    voice TEXT,
    speed REAL NOT NULL DEFAULT 1.0,
    pause_before INTEGER NOT NULL DEFAULT 0,
    pause_after INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    raw_hash TEXT,
    speed_applied REAL,
    duration REAL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_project ON segments(project_id, idx);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON")
            _conn.execute("PRAGMA journal_mode = WAL")
            _conn.executescript(SCHEMA)
            # Tiến trình trước bị ngắt giữa chừng: đoạn 'generating' quay lại 'pending'.
            _conn.execute("UPDATE segments SET status='pending' WHERE status='generating'")
        return _conn


@contextmanager
def tx():
    """Khóa + transaction; dùng cho mọi truy cập để an toàn giữa các thread."""
    with _lock:
        c = conn()
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()
