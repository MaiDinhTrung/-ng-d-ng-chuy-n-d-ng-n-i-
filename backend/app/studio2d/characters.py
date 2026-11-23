"""Character Consistency: hồ sơ nhân vật theo dự án. Hồ sơ + ảnh tham chiếu được tái sử dụng ở mọi cảnh."""
from __future__ import annotations

import json

from . import references, store

TEXT_FIELDS = ("name", "description", "facial_features", "hair", "costume", "main_colors", "weapons", "personality",
               "consistency_rules")


class NotFound(KeyError):
    pass


def _d(r) -> dict:
    d = dict(r)
    d["reference_ids"] = json.loads(d["reference_ids"] or "[]")
    d["confirmed"] = bool(d["confirmed"])
    return d


def get(cid: str) -> dict:
    rows = store.query("SELECT * FROM s2d_characters WHERE id=?", (cid,))
    if not rows:
        raise NotFound(f"Không có nhân vật {cid}")
    return _d(rows[0])


def list_for_project(pid: str) -> list[dict]:
    return [_d(r) for r in store.query("SELECT * FROM s2d_characters WHERE project_id=? ORDER BY rowid", (pid,))]


def _valid_refs(ids: list[str] | None) -> list[str]:
    out = []
    for i in ids or []:
        try:
            references.get(i)
            out.append(i)
        except references.NotFound:
            pass
    return out


def create(pid: str, data: dict) -> dict:
    cid, ts = store.new_id(), store.now()
    vals = [str(data.get(f) or "").strip() for f in TEXT_FIELDS]
    if not vals[0]:
        raise ValueError("Nhân vật cần có tên")
    with store.tx() as c:
        c.execute(f"""INSERT INTO s2d_characters(id,project_id,{','.join(TEXT_FIELDS)},reference_ids,confirmed,created_at,updated_at)
                      VALUES(?,?,{','.join('?' * len(TEXT_FIELDS))},?,0,?,?)""",
                  (cid, pid, *vals, store.dumps(_valid_refs(data.get("reference_ids"))), ts, ts))
    return get(cid)


def update(cid: str, patch: dict) -> dict:
    get(cid)
    sets, vals = [], []
    for k in TEXT_FIELDS:
        if patch.get(k) is not None:
            if k == "name" and not str(patch[k]).strip():
                raise ValueError("Tên nhân vật không được để trống")
            sets.append(f"{k}=?")
            vals.append(str(patch[k]).strip())
    if patch.get("reference_ids") is not None:
        sets.append("reference_ids=?")
        vals.append(store.dumps(_valid_refs(patch["reference_ids"])))
    if sets:
        sets.append("confirmed=0")          # sửa hồ sơ thì phải xác nhận lại
        with store.tx() as c:
            c.execute(f"UPDATE s2d_characters SET {','.join(sets)}, updated_at=? WHERE id=?", [*vals, store.now(), cid])
    return get(cid)


def set_confirmed(pid: str, cid: str | None, value: bool) -> list[dict]:
    with store.tx() as c:
        if cid:
            get(cid)
            c.execute("UPDATE s2d_characters SET confirmed=? WHERE id=? AND project_id=?", (int(value), cid, pid))
        else:
            c.execute("UPDATE s2d_characters SET confirmed=? WHERE project_id=?", (int(value), pid))
    return list_for_project(pid)


def delete(cid: str) -> None:
    get(cid)
    with store.tx() as c:
        c.execute("DELETE FROM s2d_characters WHERE id=?", (cid,))


def descriptor(ch: dict) -> str:
    """Khối mô tả cố định chèn vào mọi prompt ảnh có nhân vật này (đảm bảo nhất quán giữa các cảnh)."""
    parts = [("", ch["description"]), ("face: ", ch["facial_features"]), ("hair: ", ch["hair"]),
             ("outfit: ", ch["costume"]), ("main colors: ", ch["main_colors"]), ("weapons: ", ch["weapons"])]
    body = "; ".join(f"{p}{v}" for p, v in parts if v)
    rules = f" Rules: {ch['consistency_rules']}" if ch["consistency_rules"] else ""
    return f"{ch['name']} ({body}).{rules}"
