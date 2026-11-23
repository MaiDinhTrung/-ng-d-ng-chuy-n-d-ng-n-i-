"""Schema và truy cập DB của phân hệ 2D. Bảng có tiền tố s2d_, dùng chung file studio.db nhưng tách hẳn bảng Audio."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from ..storage import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS s2d_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    script TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'vi',
    target_audience TEXT NOT NULL DEFAULT '',
    video_type TEXT NOT NULL DEFAULT '',
    duration_sec INTEGER,
    aspect_ratio TEXT NOT NULL DEFAULT '16:9',
    visual_style TEXT NOT NULL DEFAULT '',
    voice_engine TEXT,
    voice_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS s2d_references (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    filename TEXT NOT NULL,
    thumb TEXT,
    mime TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_refs_cat ON s2d_references(category, created_at);
CREATE TABLE IF NOT EXISTS s2d_project_refs (
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    reference_id TEXT NOT NULL REFERENCES s2d_references(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, reference_id)
);
CREATE TABLE IF NOT EXISTS s2d_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    changes TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_rev_project ON s2d_revisions(project_id, id);
"""

SCHEMA += """
CREATE TABLE IF NOT EXISTS s2d_meta (
    project_id TEXT PRIMARY KEY REFERENCES s2d_projects(id) ON DELETE CASCADE,
    storyboard_approved INTEGER NOT NULL DEFAULT 0,
    budget_usd REAL,
    bgm_file TEXT,
    bgm_volume REAL NOT NULL DEFAULT 0.15,
    subtitles INTEGER NOT NULL DEFAULT 1,
    default_transition TEXT NOT NULL DEFAULT 'fade'
);
CREATE TABLE IF NOT EXISTS s2d_characters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    facial_features TEXT NOT NULL DEFAULT '',
    hair TEXT NOT NULL DEFAULT '',
    costume TEXT NOT NULL DEFAULT '',
    main_colors TEXT NOT NULL DEFAULT '',
    weapons TEXT NOT NULL DEFAULT '',
    personality TEXT NOT NULL DEFAULT '',
    consistency_rules TEXT NOT NULL DEFAULT '',
    reference_ids TEXT NOT NULL DEFAULT '[]',
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_chars_project ON s2d_characters(project_id);
CREATE TABLE IF NOT EXISTS s2d_scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    narration TEXT NOT NULL DEFAULT '',
    character_ids TEXT NOT NULL DEFAULT '[]',
    environment TEXT NOT NULL DEFAULT '',
    visual_description TEXT NOT NULL DEFAULT '',
    camera_angle TEXT NOT NULL DEFAULT '',
    camera_movement TEXT NOT NULL DEFAULT 'static',
    character_action TEXT NOT NULL DEFAULT '',
    lighting TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 5,
    transition TEXT NOT NULL DEFAULT 'fade',
    effect TEXT NOT NULL DEFAULT 'none',
    image_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    reference_ids TEXT NOT NULL DEFAULT '[]',
    image_gen_id TEXT,
    audio_file TEXT,
    audio_hash TEXT,
    audio_duration REAL,
    clip_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_scenes_project ON s2d_scenes(project_id, idx);
CREATE TABLE IF NOT EXISTS s2d_generations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    scene_id TEXT,
    kind TEXT NOT NULL DEFAULT 'image',
    provider TEXT NOT NULL,
    model TEXT,
    prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    reference_ids TEXT NOT NULL DEFAULT '[]',
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    cost_usd REAL,
    duration_ms INTEGER,
    file TEXT,
    sha256 TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_gen_scene ON s2d_generations(scene_id, created_at);
CREATE TABLE IF NOT EXISTS s2d_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    purpose TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_usage_project ON s2d_usage(project_id);
CREATE TABLE IF NOT EXISTS s2d_llm_cache (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS s2d_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    scene_id TEXT,
    kind TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    progress REAL NOT NULL DEFAULT 0,
    log TEXT NOT NULL DEFAULT '',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_tasks_project ON s2d_tasks(project_id, id);
CREATE TABLE IF NOT EXISTS s2d_renders (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES s2d_projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    hash TEXT NOT NULL,
    duration REAL,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s2d_renders_project ON s2d_renders(project_id, created_at);
"""

_ready = False
_init_lock = threading.Lock()


def ensure_schema() -> None:
    """Idempotent; gọi ở lifespan và tự gọi lại ở lần truy cập đầu (an toàn cho test)."""
    global _ready
    if _ready:
        return
    with _init_lock:
        if _ready:
            return
        with db._lock:  # noqa: SLF001 - dùng chung khóa của kết nối SQLite
            db.conn().executescript(SCHEMA)
        _ready = True


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def query(sql: str, args: tuple = ()):
    ensure_schema()
    return db.query(sql, args)


def tx():
    ensure_schema()
    return db.tx()


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
