"""Image Generation Manager: kiến trúc adapter nhiều nhà cung cấp + lưu mọi lần tạo ảnh.

Hiện CHƯA có adapter thật nào được đăng ký (chưa chọn nhà cung cấp, chưa có khóa). Thêm nhà cung cấp = viết một lớp
ImageProvider và gọi register(); lõi hệ thống không phải sửa. Người dùng vẫn có thể tự tải ảnh lên cho từng cảnh.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import cost, director, projects, references, scenes, store


@dataclass
class ImageCapabilities:
    text_to_image: bool = True
    image_to_image: bool = False
    reference_images: bool = False
    max_images: int = 4
    sizes: list[str] = field(default_factory=lambda: ["1024x1024"])
    qualities: list[str] = field(default_factory=lambda: ["standard"])
    negative_prompt: bool = False
    models: list[str] = field(default_factory=list)


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    n: int = 1
    quality: str = "standard"
    model: str | None = None
    reference_images: list[Path] = field(default_factory=list)     # chỉ có khi provider hỗ trợ
    init_image: Path | None = None                                   # image-to-image


@dataclass
class ImageResult:
    images: list[bytes]
    cost_usd: float | None = None
    model: str | None = None


class ImageProvider(ABC):
    id: str
    name: str

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def capabilities(self) -> ImageCapabilities: ...

    @abstractmethod
    def generate(self, req: ImageRequest) -> ImageResult:
        """Gọi API thật. Lỗi nên ném ngoại lệ có thông điệp rõ ràng."""


_providers: dict[str, ImageProvider] = {}


def register(p: ImageProvider) -> None:
    _providers[p.id] = p


def unregister(pid: str) -> None:
    _providers.pop(pid, None)


def list_providers() -> list[dict]:
    return [{"id": p.id, "name": p.name, "configured": p.is_configured(), "capabilities": p.capabilities().__dict__}
            for p in _providers.values()]


class NoProvider(RuntimeError):
    pass


def _save_image(pid: str, data: bytes) -> tuple[str, str, int, int]:
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format or ""
        w, h = im.size
        im.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Dữ liệu ảnh không hợp lệ") from e
    ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(fmt)
    if not ext:
        raise ValueError(f"Định dạng {fmt or 'không rõ'} không được hỗ trợ (PNG, JPEG, WEBP)")
    gid = store.new_id()
    d = projects.project_dir(pid) / "images"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{gid}.{ext}").write_bytes(data)
    return gid, f"images/{gid}.{ext}", w, h


def _record(pid: str, sid: str | None, gid: str, provider: str, model: str | None, prompt: str, neg: str, refs: list[str],
            params: dict, status: str, cost_usd: float | None, ms: int, file: str | None, sha: str | None,
            error: str | None) -> None:
    with store.tx() as c:
        c.execute("""INSERT INTO s2d_generations(id,project_id,scene_id,kind,provider,model,prompt,negative_prompt,reference_ids,
                     params,status,cost_usd,duration_ms,file,sha256,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (gid, pid, sid, "image", provider, model, prompt, neg, store.dumps(refs), store.dumps(params), status,
                   cost_usd, ms, file, sha, error, store.now()))


def add_manual_image(sid: str, data: bytes, select: bool = True) -> dict:
    """Người dùng tự tải ảnh cho cảnh (không qua nhà cung cấp, không tốn chi phí)."""
    sc = scenes.get(sid)
    pid = sc["project_id"]
    gid, rel, w, h = _save_image(pid, data)
    _record(pid, sid, gid, "manual", None, "", "", [], {"width": w, "height": h}, "completed", 0.0, 0, rel,
            hashlib.sha256(data).hexdigest(), None)
    if select:
        select_image(sid, gid)
    return get_generation(gid)


def get_generation(gid: str) -> dict:
    rows = store.query("SELECT * FROM s2d_generations WHERE id=?", (gid,))
    if not rows:
        raise scenes.NotFound(f"Không có lần tạo ảnh {gid}")
    d = dict(rows[0])
    d["reference_ids"] = json.loads(d["reference_ids"])
    d["params"] = json.loads(d["params"])
    return d


def list_generations(sid: str) -> list[dict]:
    return [get_generation(r["id"]) for r in store.query(
        "SELECT id FROM s2d_generations WHERE scene_id=? ORDER BY created_at DESC, id", (sid,))]


def select_image(sid: str, gid: str) -> dict:
    g = get_generation(gid)
    if g["scene_id"] != sid or g["status"] != "completed" or not g["file"]:
        raise ValueError("Ảnh này không thuộc cảnh hoặc chưa tạo thành công")
    with store.tx() as c:
        c.execute("UPDATE s2d_scenes SET image_gen_id=?, updated_at=? WHERE id=?", (gid, store.now(), sid))
    return scenes.get(sid)


def image_path(gid: str) -> Path | None:
    g = get_generation(gid)
    return (projects.project_dir(g["project_id"]) / g["file"]) if g["file"] else None


def generate_for_scene(sid: str, provider_id: str, n: int = 1, quality: str = "standard", model: str | None = None,
                       size: str | None = None) -> list[dict]:
    """Tạo ảnh qua nhà cung cấp. Prompt cuối gồm hồ sơ nhân vật (nhất quán); ảnh tham chiếu chỉ đính kèm nếu API hỗ trợ."""
    prov = _providers.get(provider_id)
    if not prov:
        raise NoProvider("Chưa có nhà cung cấp tạo ảnh nào được cấu hình." if not _providers
                         else f"Không có nhà cung cấp '{provider_id}'")
    if not prov.is_configured():
        raise NoProvider(f"Nhà cung cấp '{provider_id}' chưa có khóa API trong .env")
    cap = prov.capabilities()
    sc = scenes.get(sid)
    pid = sc["project_id"]
    n = max(1, min(n, cap.max_images))
    if size and size not in cap.sizes:
        raise ValueError(f"Kích thước {size} không được hỗ trợ ({', '.join(cap.sizes)})")
    w, h = map(int, (size or cap.sizes[0]).split("x"))
    comp = director.compose_image_request(sid)
    ref_paths: list[Path] = []
    used_refs: list[str] = []
    if cap.reference_images:
        for rid in comp["reference_ids"]:
            try:
                p, _ = references.file_path(rid)
            except references.NotFound:
                continue
            if p.exists():
                ref_paths.append(p)
                used_refs.append(rid)
    cost.check_budget(pid)
    req = ImageRequest(prompt=comp["prompt"], negative_prompt=comp["negative_prompt"] if cap.negative_prompt else "",
                       width=w, height=h, n=n, quality=quality, model=model, reference_images=ref_paths)
    params = {"size": f"{w}x{h}", "n": n, "quality": quality}
    t0 = time.time()
    try:
        res = prov.generate(req)
    except Exception as e:  # noqa: BLE001 - mọi lỗi của nhà cung cấp đều được ghi lại
        gid = store.new_id()
        _record(pid, sid, gid, provider_id, model, comp["prompt"], comp["negative_prompt"], used_refs, params, "failed",
                None, int((time.time() - t0) * 1000), None, None, f"{type(e).__name__}: {e}"[:500])
        raise
    ms = int((time.time() - t0) * 1000)
    per = None if res.cost_usd is None else res.cost_usd / max(1, len(res.images))
    out = []
    for data in res.images:
        gid, rel, w2, h2 = _save_image(pid, data)
        _record(pid, sid, gid, provider_id, res.model or model, comp["prompt"], comp["negative_prompt"], used_refs,
                {**params, "width": w2, "height": h2}, "completed", per, ms, rel, hashlib.sha256(data).hexdigest(), None)
        cost.record(pid, "image", provider_id, res.model or model, "generate_scene_image", 0, 0, per)
        out.append(get_generation(gid))
    if out and not sc["image_gen_id"]:
        select_image(sid, out[0]["id"])
    return out
