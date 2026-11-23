"""Giai đoạn 2-5 của phân hệ 2D.

LƯU Ý QUAN TRỌNG: Claude trong file này là MÁY CHỦ GIẢ LẬP (httpx.MockTransport) để kiểm tra logic của chúng ta
(phân tích JSON, kiểm tra id, cache, đếm token, ngân sách, retry). Nó KHÔNG chứng minh API Anthropic thật hoạt động.
Nhà cung cấp ảnh cũng là một test double. FFmpeg và các bảng DB là thật.
"""
import io
import json
import subprocess

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import audio_service
from app.studio2d import audio_bridge, cost, imaging, llm, store, video, workflow

client = TestClient(app)
calls: list[dict] = []
SCRIPT = "Tào Tháo đứng trên thành. Ông nhìn quân địch kéo đến.\n\nLưu Bị rút kiếm. Trận chiến bắt đầu!"


def claude_reply(text: str, in_t=100, out_t=50, stop="end_turn", status=200):
    return httpx.Response(status, json={"content": [{"type": "text", "text": text}], "usage": {"input_tokens": in_t, "output_tokens": out_t},
                                        "model": "claude-test", "stop_reason": stop})


def fake_claude(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    calls.append(body)
    assert request.headers["x-api-key"] == "sk-test-key"
    s = body["system"]
    if "screenwriter" in s:
        return claude_reply(SCRIPT)
    if "character designer" in s:
        user = body["messages"][0]["content"]
        rid = user.split("id=")[1].split(" ")[0] if "id=" in user else "zzz"
        return claude_reply("Đây là kết quả:\n```json\n" + json.dumps({"characters": [
            {"name": "Tào Tháo", "description": "Quân phiệt", "hair": "đen", "costume": "giáp đen", "main_colors": "đen, đỏ",
             "reference_ids": [rid, "khongco"]},
            {"name": "Lưu Bị", "description": "Chủ công", "weapons": "song kiếm"}, {"name": ""}]}) + "\n```")
    if "Redesign the visuals of ONE scene" in s:
        return claude_reply(json.dumps({"scene": {"title": "Mới", "narration": "SẼ BỊ GHI ĐÈ", "image_prompt": "new prompt",
                                                    "camera_movement": "zoom_out", "character_ids": ["khongco"]}}))
    if "storyboard director" in s:
        chars = {l.split("| ")[1].split(":")[0]: l.split("id=")[1].split(" ")[0]
                 for l in body["messages"][0]["content"].splitlines() if l.startswith("- id=") and "| " in l and "character" not in l.split("|")[1]}
        tt = chars.get("Tào Tháo")
        return claude_reply(json.dumps({"scenes": [
            {"title": "Thành cao", "narration": "Tào Tháo đứng trên thành.", "character_ids": [tt, "khongco"], "environment": "thành trì",
             "camera_movement": "zoom_in", "duration": 4, "transition": "fade", "effect": "vignette", "image_prompt": "Cao Cao on the wall",
             "reference_ids": ["khongco"]},
            {"title": "Địch đến", "narration": "Ông nhìn quân địch kéo đến.", "character_ids": [tt], "camera_movement": "bay_len_troi",
             "duration": 999, "transition": "lạ", "effect": "lạ", "image_prompt": "army approaching"},
            {"title": "", "narration": "", "image_prompt": "bị bỏ vì không có lời dẫn"}]}))
    return claude_reply("{}")


@pytest.fixture(autouse=True)
def claude(monkeypatch):
    calls.clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.delenv("ANTHROPIC_PRICE_IN_PER_MTOK", raising=False)
    monkeypatch.delenv("ANTHROPIC_PRICE_OUT_PER_MTOK", raising=False)
    llm.set_transport(httpx.MockTransport(fake_claude))
    with store.tx() as c:
        c.execute("DELETE FROM s2d_llm_cache")
    yield
    llm.set_transport(None)


def mk_project(**kw) -> str:
    return client.post("/api/2d/projects", json={"name": "T", "topic": "Hồ Lô Cốc", "visual_style": "thủy mặc", **kw}).json()["id"]


def drain():
    n = 0
    while workflow.run_one():
        n += 1
    return n


def tasks(pid):
    return client.get(f"/api/2d/projects/{pid}/tasks").json()["tasks"]


def png(color=(200, 30, 30), size=(320, 180)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


# ---------------- Claude client ----------------

def test_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr("app.services.secret_store._ENV_FILES", ())
    pid = mk_project()
    r = client.post(f"/api/2d/projects/{pid}/stage/script")
    assert r.status_code == 412 and "ANTHROPIC_API_KEY" in r.text
    assert calls == []


def test_extract_json_variants():
    assert llm.extract_json('lời dẫn {"a": 1} đuôi') == {"a": 1}
    assert llm.extract_json("```json\n[1,2]\n```") == [1, 2]
    with pytest.raises(llm.LLMError):
        llm.extract_json("không có json")
    with pytest.raises(llm.LLMError):
        llm.extract_json("{hỏng")


def test_retry_on_429_then_success_and_truncation_error():
    seq = iter([httpx.Response(429, json={"error": {"message": "slow"}}), claude_reply("ok")])
    llm.set_transport(httpx.MockTransport(lambda r: next(seq)))
    assert llm.complete("s", "u1", project_id=None, purpose="t") == "ok"
    llm.set_transport(httpx.MockTransport(lambda r: claude_reply("cắt", stop="max_tokens")))
    with pytest.raises(llm.LLMError, match="cắt cụt"):
        llm.complete("s", "u2", project_id=None, purpose="t")
    llm.set_transport(httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})))
    with pytest.raises(llm.LLMError, match="401"):
        llm.complete("s", "u3", project_id=None, purpose="t")


# ---------------- Visual Director + Character + Storyboard ----------------

def test_full_planning_flow_validates_model_output_and_caches():
    ref = client.post("/api/2d/references", data={"category": "character", "description": "Tào Tháo mặt trước"},
                      files=[("files", ("a.png", png(), "image/png"))]).json()["uploaded"][0]
    pid = mk_project()
    client.put(f"/api/2d/projects/{pid}/references/{ref['id']}")
    r = client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    assert r.json()["phase"] == "planning"
    drain()
    ts = tasks(pid)
    assert [t["kind"] for t in ts] == ["script", "characters", "storyboard"]
    assert [t["status"] for t in ts] == ["completed"] * 3, [t["error"] for t in ts]
    assert client.get(f"/api/2d/projects/{pid}").json()["script"] == SCRIPT

    chars = client.get(f"/api/2d/projects/{pid}/characters").json()["characters"]
    assert [c["name"] for c in chars] == ["Tào Tháo", "Lưu Bị"]          # tên rỗng bị bỏ
    tt = chars[0]
    assert tt["reference_ids"] == [ref["id"]] and not tt["confirmed"]    # id lạ "khongco" bị loại

    sc = client.get(f"/api/2d/projects/{pid}/scenes").json()
    assert sc["approved"] is False and len(sc["scenes"]) == 2             # cảnh không có lời dẫn bị bỏ
    s1, s2 = sc["scenes"]
    assert s1["character_ids"] == [tt["id"]]                              # id nhân vật lạ bị loại
    assert s1["reference_ids"] == [ref["id"]]                             # ảnh tham chiếu nhân vật được tự thêm; "khongco" bị loại
    assert (s1["camera_movement"], s1["effect"], s1["duration"]) == ("zoom_in", "vignette", 4.0)
    assert (s2["camera_movement"], s2["transition"], s2["effect"], s2["duration"]) == ("static", "fade", "none", 60.0)

    # token được ghi nhận; chưa cấu hình giá -> không bịa chi phí
    c = client.get(f"/api/2d/projects/{pid}/cost").json()
    assert c["by_kind"]["llm"]["calls"] == 3 and c["by_kind"]["llm"]["input_tokens"] == 300
    assert c["prices_configured"] is False and c["unpriced_calls"] == 3 and c["spent_usd"] == 0

    # chạy lại cùng đầu vào -> không gọi API (cache)
    n = len(calls)
    workflow.enqueue(pid, "characters")
    drain()
    assert len(calls) == n


def test_prices_give_cost_and_budget_blocks_calls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_PRICE_IN_PER_MTOK", "3")
    monkeypatch.setenv("ANTHROPIC_PRICE_OUT_PER_MTOK", "15")
    llm.set_transport(httpx.MockTransport(lambda r: claude_reply("x", 1_000_000, 100_000)))
    pid = mk_project()
    assert client.put(f"/api/2d/projects/{pid}/budget", json={"budget_usd": 5}).json()["budget_usd"] == 5
    llm.complete("s", "a", project_id=pid, purpose="t")
    s = client.get(f"/api/2d/projects/{pid}/cost").json()
    assert s["spent_usd"] == pytest.approx(4.5) and s["warning"] is True and s["exceeded"] is False and s["budget_enforceable"]
    llm.complete("s", "b", project_id=pid, purpose="t")                     # vẫn gọi được (chưa vượt tại thời điểm kiểm tra)
    assert client.get(f"/api/2d/projects/{pid}/cost").json()["exceeded"] is True
    with pytest.raises(cost.BudgetExceeded):
        llm.complete("s", "c", project_id=pid, purpose="t")
    assert cost.llm_cost(1_000_000, 0) == 3


def test_estimate_before_run():
    pid = mk_project(duration_sec=60)
    e = client.get(f"/api/2d/projects/{pid}/estimate", params={"stage": "script"}).json()
    assert e["is_estimate"] and e["input_tokens"] > 0 and e["cost_usd"] is None
    assert client.get(f"/api/2d/projects/{pid}/estimate", params={"stage": "x"}).status_code == 400


def test_character_edit_requires_reconfirm_and_prompt_injects_profile():
    pid = mk_project(visual_style="thủy mặc")
    ch = client.post(f"/api/2d/projects/{pid}/characters", json={"name": "Quan Vũ", "hair": "râu dài", "costume": "áo xanh",
                                                                "consistency_rules": "luôn có râu"}).json()
    sc1 = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "A", "narration": "Quan Vũ cưỡi ngựa.",
                                                              "character_ids": [ch["id"]], "image_prompt": "rides a horse"}).json()
    sc2 = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "B", "narration": "Quan Vũ rút đao.",
                                                              "character_ids": [ch["id"]], "image_prompt": "draws blade"}).json()
    r1, r2 = (client.get(f"/api/2d/scenes/{s['id']}/image-request").json() for s in (sc1, sc2))
    for r in (r1, r2):
        assert "Quan Vũ" in r["prompt"] and "áo xanh" in r["prompt"] and "luôn có râu" in r["prompt"] and "thủy mặc" in r["prompt"]
    desc = lambda p: p[p.index("Quan Vũ ("): p.index("luôn có râu")]
    assert desc(r1["prompt"]) == desc(r2["prompt"])                         # cùng một khối mô tả ở mọi cảnh

    client.post(f"/api/2d/projects/{pid}/characters/confirm")
    assert client.get(f"/api/2d/projects/{pid}/characters").json()["characters"][0]["confirmed"] is True
    client.patch(f"/api/2d/characters/{ch['id']}", json={"costume": "áo đỏ"})
    assert client.get(f"/api/2d/projects/{pid}/characters").json()["characters"][0]["confirmed"] is False


def test_scene_crud_move_approve_and_regenerate_one_scene():
    pid = mk_project()
    a = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "A", "narration": "một"}).json()
    b = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "B", "narration": "hai"}).json()
    c = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "C", "narration": "ba", "after_idx": 0}).json()
    titles = lambda: [s["title"] for s in client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"]]
    assert titles() == ["A", "C", "B"]
    client.post(f"/api/2d/scenes/{b['id']}/move", params={"direction": -1})
    assert titles() == ["A", "B", "C"]
    assert client.post(f"/api/2d/projects/{pid}/storyboard/approve").json()["approved"] is True
    client.patch(f"/api/2d/scenes/{a['id']}", json={"lighting": "đèn lồng"})
    assert client.get(f"/api/2d/projects/{pid}/scenes").json()["approved"] is False       # sửa -> phải duyệt lại
    client.delete(f"/api/2d/scenes/{c['id']}")
    assert titles() == ["A", "B"]
    idx = [s["idx"] for s in client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"]]
    assert idx == [0, 1]
    assert client.post(f"/api/2d/projects/{pid}/scenes", json={"duration": 0}).status_code == 422

    # tạo lại 1 cảnh: chỉ cảnh đó đổi, lời dẫn được giữ nguyên, id lạ bị loại
    client.post(f"/api/2d/scenes/{b['id']}/regenerate", json={"instruction": "đổi sang ban đêm"})
    drain()
    nb = client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"][1]
    assert nb["title"] == "Mới" and nb["narration"] == "hai" and nb["camera_movement"] == "zoom_out" and nb["character_ids"] == []
    assert client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"][0]["title"] == "A"


# ---------------- Image manager ----------------

class FakeProvider(imaging.ImageProvider):
    id, name = "fake", "Test double"
    seen: list[imaging.ImageRequest] = []

    def is_configured(self):
        return True

    def capabilities(self):
        return imaging.ImageCapabilities(reference_images=True, max_images=3, sizes=["64x64", "128x72"], negative_prompt=True)

    def generate(self, req):
        FakeProvider.seen.append(req)
        if "FAIL" in req.prompt:
            raise RuntimeError("provider down")
        return imaging.ImageResult([png((i * 40, 0, 0), (req.width, req.height)) for i in range(req.n)], cost_usd=0.06 * req.n, model="m1")


def test_image_generation_adapter_records_everything_and_handles_errors():
    pid = mk_project()
    sc = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": "A", "narration": "x", "image_prompt": "a hero",
                                                             "negative_prompt": "blurry"}).json()
    r = client.post(f"/api/2d/scenes/{sc['id']}/images/generate", json={"provider_id": "fake"})
    assert r.status_code == 409 and "Chưa có nhà cung cấp" in r.text                  # chưa đăng ký provider nào

    imaging.register(FakeProvider())
    try:
        assert client.get("/api/2d/image-providers").json()["providers"][0]["capabilities"]["reference_images"] is True
        r = client.post(f"/api/2d/scenes/{sc['id']}/images/generate", json={"provider_id": "fake", "n": 2, "size": "128x72"})
        assert r.status_code == 200, r.text
        imgs = r.json()["images"]
        assert len(imgs) == 2 and all(i["status"] == "completed" and i["provider"] == "fake" and i["model"] == "m1" for i in imgs)
        assert imgs[0]["cost_usd"] == pytest.approx(0.06) and "a hero" in imgs[0]["prompt"] and imgs[0]["negative_prompt"] == "blurry"
        assert FakeProvider.seen[-1].width == 128 and FakeProvider.seen[-1].n == 2
        assert client.get(f"/api/2d/generations/{imgs[0]['id']}/file").status_code == 200
        scn = client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"][0]
        assert scn["image_gen_id"] == imgs[0]["id"]                                    # ảnh đầu tự được chọn
        client.post(f"/api/2d/scenes/{sc['id']}/image/select", json={"generation_id": imgs[1]["id"]})
        assert client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"][0]["image_gen_id"] == imgs[1]["id"]
        assert client.get(f"/api/2d/projects/{pid}/cost").json()["by_kind"]["image"]["cost_usd"] == pytest.approx(0.12)

        assert client.post(f"/api/2d/scenes/{sc['id']}/images/generate", json={"provider_id": "fake", "size": "9x9"}).status_code == 400
        client.patch(f"/api/2d/scenes/{sc['id']}", json={"image_prompt": "FAIL"})
        with pytest.raises(RuntimeError, match="provider down"):
            TestClient(app, raise_server_exceptions=True).post(f"/api/2d/scenes/{sc['id']}/images/generate", json={"provider_id": "fake"})
        gens = client.get(f"/api/2d/scenes/{sc['id']}/images").json()["images"]
        assert gens[0]["status"] == "failed" and "provider down" in gens[0]["error"]    # lỗi cũng được lưu
    finally:
        imaging.unregister("fake")


def test_manual_image_upload_and_validation():
    pid = mk_project()
    sc = client.post(f"/api/2d/projects/{pid}/scenes", json={"narration": "x"}).json()
    r = client.post(f"/api/2d/scenes/{sc['id']}/image", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 200 and r.json()["provider"] == "manual" and r.json()["cost_usd"] == 0
    assert client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"][0]["has_image"] is True
    assert client.post(f"/api/2d/scenes/{sc['id']}/image", files={"file": ("a.png", b"junk", "image/png")}).status_code == 400


# ---------------- Video / Audio bridge / Workflow (FFmpeg thật) ----------------

class FakeEngine:
    id = "zerotts"
    calls = 0

    def is_available(self):
        return True

    def status(self):
        return {"state": "ready"}

    def synthesize(self, text, voice, **kw):
        FakeEngine.calls += 1
        sr = 48000
        t = np.arange(int(sr * (0.4 + 0.02 * len(text)))) / sr
        return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr


def probe(path) -> dict:
    exe = audio_service.ffmpeg_path()
    p = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    import re
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    size = re.search(r"Video: .*? (\d{2,5})x(\d{2,5})", p.stderr)
    return {"duration": int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]), "w": int(size[1]), "h": int(size[2]),
            "has_audio": "Audio:" in p.stderr, "has_video": "Video:" in p.stderr}


@pytest.fixture
def ready_project(monkeypatch):
    if not audio_service.ffmpeg_path():
        pytest.skip("Cần FFmpeg")
    monkeypatch.setattr(audio_bridge, "get_engine", lambda _id: FakeEngine())
    monkeypatch.setattr(workflow, "SIZE_OVERRIDE", (192, 108, 10))
    FakeEngine.calls = 0
    pid = mk_project(voice_engine="zerotts", voice_id="v1", aspect_ratio="16:9")
    ids = []
    for i, (txt, mv, tr) in enumerate([("Cảnh một. Có hai câu.", "zoom_in", "fade"), ("Cảnh hai.", "pan_left", "dissolve"),
                                       ("Cảnh ba kết thúc.", "shake", "cut")]):
        s = client.post(f"/api/2d/projects/{pid}/scenes", json={"title": f"S{i}", "narration": txt, "camera_movement": mv,
                                                                "transition": tr, "effect": ["none", "warm", "flash"][i]}).json()
        client.post(f"/api/2d/scenes/{s['id']}/image", files={"file": (f"{i}.png", png((60 * i + 30, 100, 150)), "image/png")})
        ids.append(s["id"])
    return pid, ids


def test_produce_blocks_until_approved_confirmed_and_images():
    pid = mk_project()
    s = client.post(f"/api/2d/projects/{pid}/scenes", json={"narration": "x"}).json()
    client.post(f"/api/2d/projects/{pid}/characters", json={"name": "Nv"})
    r = client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    assert r.status_code == 400
    for expect in ("Storyboard chưa được duyệt", "Nhân vật chưa xác nhận: Nv", "Cảnh chưa có ảnh: 1"):
        assert expect in r.text
    assert s


def test_end_to_end_render_with_caching_and_per_scene_rerun(ready_project):
    pid, ids = ready_project
    client.post(f"/api/2d/projects/{pid}/storyboard/approve")
    client.patch(f"/api/2d/projects/{pid}/meta", json={"subtitles": True})
    r = client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    assert r.json()["phase"] == "producing", r.text
    drain()
    ts = tasks(pid)
    assert all(t["status"] == "completed" for t in ts), [(t["kind"], t["error"]) for t in ts if t["error"]]
    assert FakeEngine.calls >= 3
    renders = client.get(f"/api/2d/projects/{pid}/renders").json()["renders"]
    assert len(renders) == 1
    v = client.get(renders[0]["url"])
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    from app import config
    info = probe(config.STUDIO2D_DIR / "projects" / pid / renders[0]["file"])
    assert info["has_video"] and info["has_audio"] and (info["w"], info["h"]) == (192, 108)
    expected = sum(video.scene_length(s) for s in client.get(f"/api/2d/projects/{pid}/scenes").json()["scenes"])
    assert info["duration"] == pytest.approx(expected, abs=0.3)
    assert all(client.get(f"/api/2d/scenes/{i}/audio").status_code == 200 for i in ids)

    # chạy lại không đổi gì: mọi công đoạn bỏ qua, không đọc lại TTS, không dựng lại
    calls_before = FakeEngine.calls
    client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    drain()
    new = tasks(pid)[len(ts):]
    assert new and all("Bỏ qua" in t["log"] for t in new), [t["log"] for t in new]
    assert FakeEngine.calls == calls_before
    assert len(client.get(f"/api/2d/projects/{pid}/renders").json()["renders"]) == 1

    # sửa duy nhất cảnh 2 (chuyển động): chỉ clip cảnh 2 + bản ghép được dựng lại
    client.patch(f"/api/2d/scenes/{ids[1]}", json={"camera_movement": "zoom_out"})
    client.post(f"/api/2d/projects/{pid}/storyboard/approve")
    n_before = len(tasks(pid))
    client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    drain()
    new = tasks(pid)[n_before:]
    clips = {t["scene_id"]: ("Bỏ qua" in t["log"]) for t in new if t["kind"] == "scene_clip"}
    assert clips == {ids[0]: True, ids[1]: False, ids[2]: True}
    assert all("Bỏ qua" in t["log"] for t in new if t["kind"] == "scene_audio")
    assert [("Bỏ qua" in t["log"]) for t in new if t["kind"] == "render"] == [False]
    assert len(client.get(f"/api/2d/projects/{pid}/renders").json()["renders"]) == 2

    # sửa lời dẫn cảnh 3 -> chỉ đọc lại cảnh 3
    client.patch(f"/api/2d/scenes/{ids[2]}", json={"narration": "Lời dẫn mới hoàn toàn."})
    client.post(f"/api/2d/projects/{pid}/storyboard/approve")
    n_before, c_before = len(tasks(pid)), FakeEngine.calls
    client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
    drain()
    audio = {t["scene_id"]: ("Bỏ qua" in t["log"]) for t in tasks(pid)[n_before:] if t["kind"] == "scene_audio"}
    assert audio == {ids[0]: True, ids[1]: True, ids[2]: False}
    assert FakeEngine.calls == c_before + 1


def test_background_music_and_aspect_ratios(ready_project, monkeypatch):
    pid, ids = ready_project
    # nhạc nền tạo bằng FFmpeg thật
    from app import config
    bgm = config.DATA_DIR / "bgm_test.wav"
    audio_service.write_wav(bgm, (0.3 * np.sin(np.arange(48000) / 20)).astype(np.float32), 48000)
    r = client.put(f"/api/2d/projects/{pid}/bgm", files={"file": ("m.wav", bgm.read_bytes(), "audio/wav")})
    assert r.json()["bgm_file"] == "bgm.wav"
    assert client.put(f"/api/2d/projects/{pid}/bgm", files={"file": ("m.exe", b"x", "x/y")}).status_code == 400
    client.post(f"/api/2d/projects/{pid}/storyboard/approve")
    for ratio, wh in (("9:16", (108, 192)), ("1:1", (108, 108))):
        client.patch(f"/api/2d/projects/{pid}", json={"aspect_ratio": ratio})
        monkeypatch.setattr(workflow, "SIZE_OVERRIDE", (*wh, 10))
        client.post(f"/api/2d/projects/{pid}/produce", json={"kind": "preview"})
        drain()
        assert all(t["status"] == "completed" for t in tasks(pid)), [t["error"] for t in tasks(pid) if t["error"]]
        latest = client.get(f"/api/2d/projects/{pid}/renders").json()["renders"][0]
        info = probe(config.STUDIO2D_DIR / "projects" / pid / latest["file"])
        assert (info["w"], info["h"]) == wh and info["has_audio"]


def test_srt_generation():
    srt = video.make_srt([(0.0, 4.0, "Câu một. Câu hai dài hơn một chút!"), (4.0, 2.0, "Cảnh sau.")])
    assert srt.count("-->") == 3 and "00:00:00,000 -->" in srt and "Cảnh sau." in srt


# ---------------- Workflow bền vững ----------------

def test_task_failure_retry_and_resume_after_restart():
    pid = mk_project()                                   # chưa có kịch bản/chủ đề đủ -> script chạy được; dùng characters để lỗi
    t_fail = workflow.enqueue(pid, "characters")         # không có kịch bản -> lỗi
    drain()
    t = next(x for x in tasks(pid) if x["id"] == t_fail)
    assert t["status"] == "failed" and "kịch bản" in t["error"] and t["attempts"] == 1
    client.patch(f"/api/2d/projects/{pid}", json={"script": SCRIPT})
    assert client.post(f"/api/2d/tasks/{t_fail}/retry").status_code == 200
    drain()
    t = next(x for x in tasks(pid) if x["id"] == t_fail)
    assert t["status"] == "completed" and t["attempts"] == 2

    # mô phỏng app bị đóng khi task đang chạy: running -> pending khi khởi động lại, rồi chạy tiếp
    tid = workflow.enqueue(pid, "script")
    with store.tx() as c:
        c.execute("UPDATE s2d_tasks SET status='running' WHERE id=?", (tid,))
    assert workflow.recover() >= 1
    assert next(x for x in tasks(pid) if x["id"] == tid)["status"] == "pending"
    drain()
    assert next(x for x in tasks(pid) if x["id"] == tid)["status"] == "completed"

    # trùng lặp & hủy
    a, b = workflow.enqueue(pid, "storyboard"), workflow.enqueue(pid, "storyboard")
    assert a == b
    assert client.post(f"/api/2d/projects/{pid}/tasks/cancel").json()["cancelled"] == 1
    assert next(x for x in tasks(pid) if x["id"] == a)["error"] == "Đã hủy"
    assert client.post(f"/api/2d/tasks/{a}/retry").status_code == 200       # task đã hủy vẫn thử lại được


def test_deleting_project_removes_all_2d_data():
    pid = mk_project()
    s = client.post(f"/api/2d/projects/{pid}/scenes", json={"narration": "x"}).json()
    client.post(f"/api/2d/scenes/{s['id']}/image", files={"file": ("a.png", png(), "image/png")})
    client.post(f"/api/2d/projects/{pid}/characters", json={"name": "X"})
    workflow.enqueue(pid, "script")
    client.delete(f"/api/2d/projects/{pid}")
    for tbl in ("s2d_scenes", "s2d_characters", "s2d_generations", "s2d_tasks", "s2d_meta"):
        assert store.query(f"SELECT COUNT(*) AS n FROM {tbl} WHERE project_id=?", (pid,))[0]["n"] == 0, tbl
