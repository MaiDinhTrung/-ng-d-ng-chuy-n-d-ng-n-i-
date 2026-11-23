"""Kho bí mật dùng chung (khóa API). Chỉ đọc từ biến môi trường / file .env ở backend.

- Không bao giờ trả giá trị đầy đủ ra API: chỉ trả trạng thái và bản đã che (`mask`).
- .env nằm trong .gitignore. Mẫu: `.env.example`.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import config

_ENV_FILES = (config.BACKEND_DIR.parent / ".env", config.BACKEND_DIR / ".env")
_loaded = False


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    k, v = line.split("=", 1)
    k, v = k.strip().removeprefix("export ").strip(), v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return (k, v) if k else None


def load_env(files: tuple[Path, ...] | None = None, force: bool = False) -> None:
    """Nạp .env vào os.environ; biến đã có sẵn trong môi trường được ưu tiên."""
    global _loaded
    if _loaded and not force:
        return
    for f in files or _ENV_FILES:
        try:
            text = f.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            kv = _parse_line(line)
            if kv and kv[0] not in os.environ:
                os.environ[kv[0]] = kv[1]
    _loaded = True


def get(name: str) -> str | None:
    load_env()
    v = os.environ.get(name, "").strip()
    return v or None


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return "•" * 6 + value[-4:] if len(value) > 8 else "•" * len(value)


def status(name: str) -> dict:
    v = get(name)
    return {"name": name, "configured": bool(v), "masked": mask(v)}
