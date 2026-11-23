"""Reference Library: lưu ảnh tham chiếu dùng lại được (ID riêng, danh mục, mô tả), gắn vào nhiều dự án."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .. import config
from . import store

MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 100_000_000
THUMB_SIZE = 360
# Định dạng cho phép -> (đuôi file, mime). Đuôi do ta chọn theo định dạng thật, không dùng tên file người dùng.
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp"),
           "GIF": ("gif", "image/gif")}


class NotFound(KeyError):
    pass


class InvalidImage(ValueError):
    pass


def _to_dict(r) -> dict:
    d = dict(r)
    d["tags"] = json.loads(d["tags"] or "[]")
    d["url"] = f"/api/2d/references/{d['id']}/file"
    d["thumb_url"] = f"/api/2d/references/{d['id']}/thumb" if d.get("thumb") else d["url"]
    d.pop("filename", None)
    d.pop("thumb", None)
    return d


def _clean_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        t = t.strip()[:40]
        if t and t not in out:
            out.append(t)
    return out[:30]


def _raw(rid: str):
    rows = store.query("SELECT * FROM s2d_references WHERE id=?", (rid,))
    if not rows:
        raise NotFound(f"Không có tư liệu {rid}")
    return rows[0]


def get(rid: str) -> dict:
    return _to_dict(_raw(rid))


def add_image(data: bytes, original_name: str, category: str, description: str = "", tags: list[str] | None = None,
              name: str | None = None) -> dict:
    if not data:
        raise InvalidImage("File rỗng")
    if len(data) > MAX_BYTES:
        raise InvalidImage(f"Ảnh quá lớn (tối đa {MAX_BYTES // (1024 * 1024)} MB)")
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format or ""
        if fmt not in FORMATS:
            raise InvalidImage(f"Định dạng {fmt or 'không rõ'} không được hỗ trợ (PNG, JPEG, WEBP, GIF)")
        w, h = im.size
        if w * h > MAX_PIXELS:
            raise InvalidImage("Ảnh có số điểm ảnh quá lớn")
        im.load()                                   # phát hiện file hỏng ngay bây giờ
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise InvalidImage("Không đọc được file ảnh (hỏng hoặc không phải ảnh)") from e

    rid = store.new_id()
    ext, mime = FORMATS[fmt]
    fname, thumb_name = f"{rid}.{ext}", f"{rid}.jpg"
    (config.S2D_REF_DIR / fname).write_bytes(data)
    thumb = im.convert("RGBA")
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
    bg = Image.new("RGB", thumb.size, (255, 255, 255))
    bg.paste(thumb, mask=thumb.getchannel("A"))
    bg.save(config.S2D_THUMB_DIR / thumb_name, "JPEG", quality=82)

    ts = store.now()
    title = (name or Path(original_name or "").stem or "Tư liệu").strip()[:200] or "Tư liệu"
    try:
        with store.tx() as c:
            c.execute("""INSERT INTO s2d_references(id,category,name,description,tags,filename,thumb,mime,width,height,
                         size,sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, category, title, description, store.dumps(_clean_tags(tags)), fname, thumb_name, mime,
                       w, h, len(data), hashlib.sha256(data).hexdigest(), ts, ts))
    except Exception:
        (config.S2D_REF_DIR / fname).unlink(missing_ok=True)
        (config.S2D_THUMB_DIR / thumb_name).unlink(missing_ok=True)
        raise
    return get(rid)


def list_refs(category: str | None = None, project_id: str | None = None, q: str | None = None) -> list[dict]:
    sql, args, where = "SELECT r.* FROM s2d_references r", [], []
    if project_id:
        sql += " JOIN s2d_project_refs l ON l.reference_id = r.id"
        where.append("l.project_id = ?")
        args.append(project_id)
    if category:
        where.append("r.category = ?")
        args.append(category)
    if q and q.strip():
        like = f"%{q.strip().replace('%', '').replace('_', '')}%"
        where.append("(r.name LIKE ? OR r.description LIKE ? OR r.tags LIKE ?)")
        args += [like, like, like]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.created_at DESC, r.id"
    refs = [_to_dict(r) for r in store.query(sql, tuple(args))]
    # Số dự án đang dùng mỗi tư liệu (để UI cảnh báo khi xóa).
    use = {r["reference_id"]: r["n"] for r in store.query(
        "SELECT reference_id, COUNT(*) AS n FROM s2d_project_refs GROUP BY reference_id")}
    for r in refs:
        r["used_by"] = use.get(r["id"], 0)
    return refs


def list_for_project(pid: str) -> list[dict]:
    refs = list_refs(project_id=pid)
    notes = {r["reference_id"]: r["note"] for r in store.query(
        "SELECT reference_id, note FROM s2d_project_refs WHERE project_id=?", (pid,))}
    for r in refs:
        r["note"] = notes.get(r["id"], "")
    return refs


def update(rid: str, patch: dict) -> dict:
    _raw(rid)
    sets, vals = [], []
    for k in ("name", "description", "category"):
        if patch.get(k) is not None:
            sets.append(f"{k}=?")
            vals.append(patch[k].strip() if k == "name" else patch[k])
    if patch.get("tags") is not None:
        sets.append("tags=?")
        vals.append(store.dumps(_clean_tags(patch["tags"])))
    if sets:
        with store.tx() as c:
            c.execute(f"UPDATE s2d_references SET {','.join(sets)}, updated_at=? WHERE id=?", [*vals, store.now(), rid])
    return get(rid)


def delete(rid: str) -> None:
    r = _raw(rid)
    with store.tx() as c:
        c.execute("DELETE FROM s2d_references WHERE id=?", (rid,))      # liên kết dự án xóa theo (CASCADE)
    (config.S2D_REF_DIR / r["filename"]).unlink(missing_ok=True)
    if r["thumb"]:
        (config.S2D_THUMB_DIR / r["thumb"]).unlink(missing_ok=True)


def file_path(rid: str, thumb: bool = False) -> tuple[Path, str]:
    r = _raw(rid)
    if thumb and r["thumb"]:
        return config.S2D_THUMB_DIR / r["thumb"], "image/jpeg"
    return config.S2D_REF_DIR / r["filename"], r["mime"]
