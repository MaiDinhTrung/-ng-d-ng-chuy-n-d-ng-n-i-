from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..services import audio_service, secret_store
from . import (audio_bridge, characters, cost, director, imaging, llm, projects, references, scenes, store, video,
               workflow)
from .schemas import (CATEGORY_LABELS, BudgetIn, Category, CharacterIn, CharacterPatch, GenerateImageIn, LinkIn,
                      MetaPatch, ProduceIn, ProjectIn, ProjectPatch, ReferencePatch, RegenIn, SceneIn, ScenePatch,
                      SelectImageIn)

router = APIRouter(prefix="/api/2d")


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (projects.NotFound, references.NotFound, characters.NotFound, scenes.NotFound) as e:
        raise HTTPException(404, str(e.args[0])) from e
    except imaging.NoProvider as e:
        raise HTTPException(409, str(e)) from e
    except llm.NotConfigured as e:
        raise HTTPException(412, str(e)) from e
    except cost.BudgetExceeded as e:
        raise HTTPException(402, str(e)) from e
    except (llm.LLMError, video.RenderError) as e:
        raise HTTPException(502, str(e)) from e
    except (references.InvalidImage, workflow.Invalid, ValueError) as e:
        raise HTTPException(400, str(e)) from e


# ---------------- hệ thống ----------------

@router.get("/status")
def status():
    """Trạng thái cấu hình. Chỉ trả cờ 'đã cấu hình' và bản che; không bao giờ trả khóa thật.
    `verified` luôn False ở giai đoạn 1: chưa gọi thử API thật nên không khẳng định khóa dùng được."""
    store.ensure_schema()
    return {
        "categories": CATEGORY_LABELS,
        "ffmpeg": {"available": bool(audio_service.ffmpeg_path())},
        "providers": {
            "claude": {**secret_store.status("ANTHROPIC_API_KEY"), "role": "Phân tích, kịch bản, storyboard, prompt",
                       "verified": False, "model": llm.model(), "prices_configured": cost.llm_prices() is not None},
            "image": {"configured": any(p["configured"] for p in imaging.list_providers()), "role": "Tạo ảnh",
                      "providers": imaging.list_providers(),
                      "note": "" if imaging.list_providers() else
                      "Chưa có nhà cung cấp nào được đăng ký; vẫn có thể tự tải ảnh lên cho từng cảnh"},
            "video": {"configured": False, "role": "Tạo chuyển động",
                      "note": "Chưa có nhà cung cấp; chuyển động hiện dùng FFmpeg (pan/zoom/rung) chạy local"},
        },
    }


# ---------------- dự án ----------------

@router.get("/projects")
def list_projects():
    return {"projects": projects.list_projects()}


@router.post("/projects")
def create_project(body: ProjectIn):
    return _wrap(projects.create_project, body.model_dump())


@router.get("/projects/{pid}")
def get_project(pid: str):
    return _wrap(projects.get_project, pid)


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectPatch):
    patch = body.model_dump(exclude_unset=True)
    for k in ("name", "language", "aspect_ratio", "description", "topic", "script", "target_audience",
              "video_type", "visual_style"):
        if k in patch and patch[k] is None:
            patch.pop(k)                      # các trường văn bản không nhận null; duration/voice thì có
    return _wrap(projects.update_project, pid, patch)


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    _wrap(projects.delete_project, pid)
    return {"deleted": pid}


@router.get("/projects/{pid}/revisions")
def project_revisions(pid: str):
    return {"revisions": _wrap(projects.revisions, pid)}


@router.put("/projects/{pid}/references/{rid}")
def link_reference(pid: str, rid: str, body: LinkIn | None = None):
    return _wrap(projects.link_reference, pid, rid, body.note if body else "")


@router.delete("/projects/{pid}/references/{rid}")
def unlink_reference(pid: str, rid: str):
    return _wrap(projects.unlink_reference, pid, rid)


# ---------------- thư viện tư liệu ----------------

@router.get("/references")
def list_references(category: Category | None = None, project_id: str | None = None, q: str | None = None):
    return {"references": references.list_refs(category, project_id, q)}


@router.post("/references")
async def upload_references(files: list[UploadFile] = File(...), category: Category = Form(...),
                            description: str = Form(""), tags: str = Form(""), project_id: str | None = Form(None)):
    """Tải nhiều ảnh một lần. Mỗi ảnh được kiểm tra riêng; ảnh lỗi không làm hỏng các ảnh còn lại."""
    if project_id:
        _wrap(projects.get_project, project_id)
    tag_list = [t for t in tags.split(",") if t.strip()]
    ok, failed = [], []
    for f in files:
        data = await f.read()
        try:
            ref = references.add_image(data, f.filename or "", category, description.strip(), tag_list)
            if project_id:
                projects.link_reference(project_id, ref["id"])
            ok.append(ref)
        except references.InvalidImage as e:
            failed.append({"filename": f.filename, "error": str(e)})
    if not ok and failed:
        raise HTTPException(400, failed[0]["error"])
    return {"uploaded": ok, "failed": failed}


@router.get("/references/{rid}")
def get_reference(rid: str):
    return _wrap(references.get, rid)


@router.patch("/references/{rid}")
def update_reference(rid: str, body: ReferencePatch):
    return _wrap(references.update, rid, body.model_dump(exclude_unset=True))


@router.delete("/references/{rid}")
def delete_reference(rid: str):
    _wrap(references.delete, rid)
    return {"deleted": rid}


def _serve(rid: str, thumb: bool):
    p, mime = _wrap(references.file_path, rid, thumb)
    if not p.exists():
        raise HTTPException(404, "File ảnh không còn trên đĩa")
    return FileResponse(p, media_type=mime)


@router.get("/references/{rid}/file")
def reference_file(rid: str):
    return _serve(rid, False)


@router.get("/references/{rid}/thumb")
def reference_thumb(rid: str):
    return _serve(rid, True)


# ================= Giai đoạn 2: nhân vật, storyboard =================

@router.get("/projects/{pid}/meta")
def get_meta(pid: str):
    _wrap(projects.get_project, pid)
    cost.ensure_meta(pid)
    return dict(store.query("SELECT * FROM s2d_meta WHERE project_id=?", (pid,))[0])


@router.patch("/projects/{pid}/meta")
def patch_meta(pid: str, body: MetaPatch):
    _wrap(projects.get_project, pid)
    cost.ensure_meta(pid)
    d = body.model_dump(exclude_unset=True)
    d = {k: (int(v) if isinstance(v, bool) else v) for k, v in d.items() if v is not None}
    if d:
        with store.tx() as c:
            c.execute(f"UPDATE s2d_meta SET {','.join(k + '=?' for k in d)} WHERE project_id=?", [*d.values(), pid])
    return get_meta(pid)


@router.get("/projects/{pid}/characters")
def list_characters(pid: str):
    _wrap(projects.get_project, pid)
    return {"characters": characters.list_for_project(pid)}


@router.post("/projects/{pid}/characters")
def create_character(pid: str, body: CharacterIn):
    _wrap(projects.get_project, pid)
    return _wrap(characters.create, pid, body.model_dump())


@router.patch("/characters/{cid}")
def patch_character(cid: str, body: CharacterPatch):
    return _wrap(characters.update, cid, body.model_dump(exclude_unset=True))


@router.delete("/characters/{cid}")
def delete_character(cid: str):
    _wrap(characters.delete, cid)
    return {"deleted": cid}


@router.post("/projects/{pid}/characters/confirm")
def confirm_characters(pid: str, character_id: str | None = None, value: bool = True):
    _wrap(projects.get_project, pid)
    return {"characters": _wrap(characters.set_confirmed, pid, character_id, value)}


@router.get("/projects/{pid}/scenes")
def list_scenes(pid: str):
    _wrap(projects.get_project, pid)
    cost.ensure_meta(pid)
    meta = store.query("SELECT storyboard_approved FROM s2d_meta WHERE project_id=?", (pid,))[0]
    return {"scenes": scenes.list_for_project(pid), "approved": bool(meta["storyboard_approved"])}


@router.post("/projects/{pid}/scenes")
def create_scene(pid: str, body: SceneIn):
    _wrap(projects.get_project, pid)
    d = body.model_dump(exclude={"after_idx"}, exclude_unset=True)
    return _wrap(scenes.insert, pid, d, body.after_idx)


@router.patch("/scenes/{sid}")
def patch_scene(sid: str, body: ScenePatch):
    return _wrap(scenes.update, sid, body.model_dump(exclude_unset=True))


@router.delete("/scenes/{sid}")
def delete_scene(sid: str):
    _wrap(scenes.delete, sid)
    return {"deleted": sid}


@router.post("/scenes/{sid}/move")
def move_scene(sid: str, direction: int):
    if direction not in (-1, 1):
        raise HTTPException(400, "direction phải là -1 hoặc 1")
    return {"scenes": _wrap(scenes.move, sid, direction)}


@router.post("/projects/{pid}/storyboard/approve")
def approve_storyboard(pid: str, value: bool = True):
    _wrap(projects.get_project, pid)
    _wrap(scenes.set_approved, pid, value)
    return {"approved": value}


@router.get("/projects/{pid}/estimate")
def estimate(pid: str, stage: str):
    _wrap(projects.get_project, pid)
    return _wrap(director.estimate, pid, stage)


@router.post("/projects/{pid}/stage/{stage}")
def run_stage(pid: str, stage: str):
    """Xếp một công đoạn Claude (script | characters | storyboard). Chạy nền; theo dõi ở /tasks."""
    if stage not in ("script", "characters", "storyboard"):
        raise HTTPException(400, "stage không hợp lệ")
    _wrap(projects.get_project, pid)
    if not llm.is_configured():
        raise HTTPException(412, "Chưa có ANTHROPIC_API_KEY trong .env, nên chưa gọi được Claude.")
    return {"task_id": _wrap(workflow.enqueue, pid, stage)}


@router.post("/scenes/{sid}/regenerate")
def regenerate_scene(sid: str, body: RegenIn | None = None):
    sc = _wrap(scenes.get, sid)
    if not llm.is_configured():
        raise HTTPException(412, "Chưa có ANTHROPIC_API_KEY trong .env, nên chưa gọi được Claude.")
    return {"task_id": workflow.enqueue(sc["project_id"], "scene_regen", sid, instruction=(body.instruction if body else ""))}


# ================= Giai đoạn 3: ảnh =================

@router.get("/image-providers")
def image_providers():
    return {"providers": imaging.list_providers()}


@router.get("/scenes/{sid}/images")
def scene_images(sid: str):
    _wrap(scenes.get, sid)
    return {"images": imaging.list_generations(sid)}


@router.post("/scenes/{sid}/image")
async def upload_scene_image(sid: str, file: UploadFile = File(...)):
    """Người dùng tự tải ảnh cho cảnh (không tốn chi phí, không cần nhà cung cấp)."""
    data = await file.read()
    if len(data) > references.MAX_BYTES:
        raise HTTPException(400, "Ảnh quá lớn")
    return _wrap(imaging.add_manual_image, sid, data)


@router.post("/scenes/{sid}/images/generate")
def generate_images(sid: str, body: GenerateImageIn):
    return {"images": _wrap(imaging.generate_for_scene, sid, body.provider_id, body.n, body.quality, body.model, body.size)}


@router.post("/scenes/{sid}/image/select")
def select_image(sid: str, body: SelectImageIn):
    return _wrap(imaging.select_image, sid, body.generation_id)


@router.get("/scenes/{sid}/image-request")
def image_request(sid: str):
    """Prompt cuối cùng (đã chèn hồ sơ nhân vật + ảnh tham chiếu) sẽ gửi cho nhà cung cấp ảnh."""
    _wrap(scenes.get, sid)
    return _wrap(director.compose_image_request, sid)


@router.get("/generations/{gid}/file")
def generation_file(gid: str):
    _wrap(imaging.get_generation, gid)
    p = imaging.image_path(gid)
    if not p or not p.exists():
        raise HTTPException(404, "File ảnh không còn trên đĩa")
    return FileResponse(p)


# ================= Giai đoạn 4: audio, video =================

@router.post("/scenes/{sid}/audio")
def make_scene_audio(sid: str, force: bool = False):
    sc = _wrap(scenes.get, sid)
    return {"task_id": workflow.enqueue(sc["project_id"], "scene_audio", sid, **({"force": True} if force else {}))}


@router.get("/scenes/{sid}/audio")
def scene_audio_file(sid: str):
    sc = _wrap(scenes.get, sid)
    p = audio_bridge.scene_audio_path(sc["project_id"], sid)
    if not sc["audio_file"] or not p.exists():
        raise HTTPException(404, "Cảnh chưa có audio")
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.put("/projects/{pid}/bgm")
async def upload_bgm(pid: str, file: UploadFile = File(...)):
    _wrap(projects.get_project, pid)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "wav", "m4a", "ogg", "flac"):
        raise HTTPException(400, "Nhạc nền phải là mp3, wav, m4a, ogg hoặc flac")
    data = await file.read()
    if not data or len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "File nhạc rỗng hoặc quá lớn (tối đa 100 MB)")
    d = projects.project_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    rel = f"bgm.{ext}"
    for old in d.glob("bgm.*"):
        old.unlink(missing_ok=True)
    (d / rel).write_bytes(data)
    cost.ensure_meta(pid)
    with store.tx() as c:
        c.execute("UPDATE s2d_meta SET bgm_file=? WHERE project_id=?", (rel, pid))
    return get_meta(pid)


@router.delete("/projects/{pid}/bgm")
def delete_bgm(pid: str):
    _wrap(projects.get_project, pid)
    for old in projects.project_dir(pid).glob("bgm.*"):
        old.unlink(missing_ok=True)
    cost.ensure_meta(pid)
    with store.tx() as c:
        c.execute("UPDATE s2d_meta SET bgm_file=NULL WHERE project_id=?", (pid,))
    return get_meta(pid)


@router.post("/projects/{pid}/produce")
def produce(pid: str, body: ProduceIn | None = None):
    if not audio_service.ffmpeg_path():
        raise HTTPException(422, "Cần FFmpeg để dựng video")
    return _wrap(workflow.produce, pid, body.kind if body else "preview")


@router.get("/projects/{pid}/tasks")
def list_tasks(pid: str):
    _wrap(projects.get_project, pid)
    return {"tasks": workflow.list_tasks(pid)}


@router.post("/tasks/{tid}/retry")
def retry_task(tid: int):
    _wrap(workflow.retry, tid)
    return {"retried": tid}


@router.post("/projects/{pid}/tasks/cancel")
def cancel_tasks(pid: str):
    _wrap(projects.get_project, pid)
    return {"cancelled": workflow.cancel_pending(pid)}


@router.get("/projects/{pid}/renders")
def list_renders(pid: str):
    _wrap(projects.get_project, pid)
    rows = store.query("SELECT * FROM s2d_renders WHERE project_id=? ORDER BY created_at DESC", (pid,))
    return {"renders": [{**dict(r), "url": f"/api/2d/renders/{r['id']}/file"} for r in rows]}


@router.get("/renders/{rid}/file")
def render_file(rid: str, download: bool = False):
    rows = store.query("SELECT * FROM s2d_renders WHERE id=?", (rid,))
    if not rows:
        raise HTTPException(404, "Không có bản dựng")
    p = projects.project_dir(rows[0]["project_id"]) / rows[0]["file"]
    if not p.exists():
        raise HTTPException(404, "File video không còn trên đĩa")
    return FileResponse(p, media_type="video/mp4", filename=f"{rows[0]['kind']}_{rid}.mp4" if download else None)


# ================= Giai đoạn 5: chi phí =================

@router.get("/cost")
def global_cost():
    return cost.summary(None)


@router.get("/projects/{pid}/cost")
def project_cost(pid: str):
    _wrap(projects.get_project, pid)
    cost.ensure_meta(pid)
    return cost.summary(pid)


@router.put("/projects/{pid}/budget")
def set_budget(pid: str, body: BudgetIn):
    _wrap(projects.get_project, pid)
    cost.set_budget(pid, body.budget_usd)
    return cost.summary(pid)
