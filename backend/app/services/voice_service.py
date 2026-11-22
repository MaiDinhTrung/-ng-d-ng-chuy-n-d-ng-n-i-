"""Voice Library: giọng tích hợp + voice pack do người dùng thêm. Clone chỉ khi có provider thật."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..engines import cloning_provider, get_engine, get_engines


def list_voices(engine_id: str | None = None) -> list[dict]:
    out: list[dict] = []
    for eid, eng in get_engines().items():
        if engine_id and eid != engine_id:
            continue
        for v in eng.get_voices():
            d = asdict(v)
            d["engine"] = eid
            d["status"] = "ok"
            d["reference_path"] = None
            d["created_at"] = None
            if v.source == "custom":
                vdir = config.VOICES_DIR / v.id
                npz = vdir / "voice.npz"
                if npz.exists():
                    d["created_at"] = datetime.fromtimestamp(npz.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
                    d["reference_path"] = str(vdir)
            out.append(d)
    return out


def import_voice_pack(engine_id: str, upload_path: Path, filename: str) -> list[str]:
    eng = get_engine(engine_id)
    if not hasattr(eng, "add_voice_zip"):
        raise ValueError("Engine này không hỗ trợ nạp voice pack")
    if not filename.lower().endswith(".zip"):
        raise ValueError("Voice pack phải là file .zip chứa thư mục có voice.npz")
    return eng.add_voice_zip(str(upload_path))  # type: ignore[attr-defined]


def delete_voice(engine_id: str, voice_id: str) -> None:
    eng = get_engine(engine_id)
    if not hasattr(eng, "remove_custom_voice"):
        raise ValueError("Engine này không hỗ trợ xóa giọng")
    eng.remove_custom_voice(voice_id)  # type: ignore[attr-defined]


def clone_status() -> dict:
    return cloning_provider.check_availability()
