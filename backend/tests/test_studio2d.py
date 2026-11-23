"""Giai đoạn 1: Project Manager + Reference Library của phân hệ 2D, và smoke test Audio không bị ảnh hưởng.
Dùng TestClient không bật lifespan (không nạp model TTS); dữ liệu nằm trong thư mục tạm của conftest."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.main import app
from app.services import secret_store

client = TestClient(app)


def png(color=(200, 30, 30), size=(64, 48), fmt="PNG") -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return b.getvalue()


def upload(files, category="character", **form):
    return client.post("/api/2d/references", data={"category": category, **form},
                       files=[("files", f) for f in files])


# ---------------- Project Manager ----------------

def test_project_crud_and_revisions():
    r = client.post("/api/2d/projects", json={"name": "Tam Quốc", "topic": "Hồ Lô Cốc", "aspect_ratio": "9:16",
                                              "duration_sec": 90, "voice_engine": "zerotts", "voice_id": "huuduc"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["aspect_ratio"] == "9:16" and p["status"] == "draft" and p["references"] == []
    pid = p["id"]
    assert (config.STUDIO2D_DIR / "projects" / pid).is_dir()

    r = client.patch(f"/api/2d/projects/{pid}", json={"name": "Tam Quốc 2", "script": "Kịch bản dài " * 100})
    assert r.json()["name"] == "Tam Quốc 2"
    # đổi cùng giá trị -> không sinh lịch sử mới
    client.patch(f"/api/2d/projects/{pid}", json={"name": "Tam Quốc 2"})
    # xóa trường tùy chọn bằng null
    r = client.patch(f"/api/2d/projects/{pid}", json={"duration_sec": None})
    assert r.json()["duration_sec"] is None and r.json()["topic"] == "Hồ Lô Cốc"

    revs = client.get(f"/api/2d/projects/{pid}/revisions").json()["revisions"]
    assert [x["kind"] for x in revs] == ["update", "update", "create"]
    script_change = next(x for x in revs if "script" in x["changes"])["changes"]["script"]
    assert len(script_change[1]) <= 501                      # kịch bản dài bị cắt trong lịch sử

    assert any(x["id"] == pid for x in client.get("/api/2d/projects").json()["projects"])
    assert client.delete(f"/api/2d/projects/{pid}").status_code == 200
    assert client.get(f"/api/2d/projects/{pid}").status_code == 404
    assert not (config.STUDIO2D_DIR / "projects" / pid).exists()


def test_project_validation():
    assert client.post("/api/2d/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/2d/projects", json={"name": "x", "aspect_ratio": "4:3"}).status_code == 422
    assert client.post("/api/2d/projects", json={"name": "x", "duration_sec": 0}).status_code == 422
    assert client.patch("/api/2d/projects/khongco", json={"name": "a"}).status_code == 404


# ---------------- Reference Library ----------------

def test_upload_multiple_with_metadata_and_files_on_disk():
    r = upload([("a.png", png(), "image/png"), ("b.jpg", png(fmt="JPEG"), "image/jpeg")],
               description="Tào Tháo, giáp đen", tags="giáp, mặt trước, giáp")
    assert r.status_code == 200, r.text
    up = r.json()["uploaded"]
    assert len(up) == 2 and not r.json()["failed"]
    a = up[0]
    assert a["id"] and a["category"] == "character" and a["description"] == "Tào Tháo, giáp đen"
    assert a["tags"] == ["giáp", "mặt trước"]                 # bỏ khoảng trắng và trùng lặp
    assert (a["width"], a["height"]) == (64, 48) and len(a["sha256"]) == 64
    assert a["name"] == "a"
    assert (config.S2D_REF_DIR / f"{a['id']}.png").is_file()
    assert (config.S2D_THUMB_DIR / f"{a['id']}.jpg").is_file()
    assert up[1]["id"] != a["id"]
    f = client.get(a["url"])
    assert f.status_code == 200 and f.headers["content-type"] == "image/png" and f.content == png()
    assert client.get(a["thumb_url"]).headers["content-type"] == "image/jpeg"


def test_upload_rejects_bad_files_but_keeps_good_ones():
    r = upload([("good.png", png(), "image/png"), ("fake.png", b"khong phai anh", "image/png"),
                ("empty.png", b"", "image/png")])
    body = r.json()
    assert len(body["uploaded"]) == 1 and len(body["failed"]) == 2
    only_bad = upload([("fake.png", b"xxx", "image/png")])
    assert only_bad.status_code == 400


def test_upload_rejects_unsupported_format_and_bad_category():
    bmp = io.BytesIO()
    Image.new("RGB", (4, 4)).save(bmp, "BMP")
    r = upload([("x.bmp", bmp.getvalue(), "image/bmp")])
    assert r.status_code == 400 and "không được hỗ trợ" in r.text
    assert upload([("a.png", png(), "image/png")], category="hack").status_code == 422


def test_filename_cannot_escape_storage():
    r = upload([("../../evil.png", png(), "image/png")])
    ref = r.json()["uploaded"][0]
    assert ref["name"] == "evil"
    assert (config.S2D_REF_DIR / f"{ref['id']}.png").is_file()
    assert not (config.DATA_DIR.parent / "evil.png").exists()


def test_filter_search_update_delete():
    env = upload([("c.png", png((0, 0, 200)), "image/png")], category="environment",
                 description="Thành trì ban đêm", tags="thành")
    rid = env.json()["uploaded"][0]["id"]
    got = client.get("/api/2d/references", params={"category": "environment"}).json()["references"]
    assert rid in [x["id"] for x in got] and all(x["category"] == "environment" for x in got)
    assert rid in [x["id"] for x in client.get("/api/2d/references", params={"q": "thành trì"}).json()["references"]]
    assert client.get("/api/2d/references", params={"q": "zzzkhongco"}).json()["references"] == []

    r = client.patch(f"/api/2d/references/{rid}", json={"name": "Thành đêm", "category": "style", "tags": ["lạnh"]})
    assert r.json()["name"] == "Thành đêm" and r.json()["category"] == "style" and r.json()["tags"] == ["lạnh"]

    assert client.delete(f"/api/2d/references/{rid}").status_code == 200
    assert client.get(f"/api/2d/references/{rid}").status_code == 404
    assert not (config.S2D_REF_DIR / f"{rid}.png").exists()
    assert not (config.S2D_THUMB_DIR / f"{rid}.jpg").exists()


def test_link_reference_to_projects_and_reuse():
    ref = upload([("r.png", png(), "image/png")], category="style").json()["uploaded"][0]
    p1 = client.post("/api/2d/projects", json={"name": "P1"}).json()["id"]
    p2 = client.post("/api/2d/projects", json={"name": "P2"}).json()["id"]
    r = client.put(f"/api/2d/projects/{p1}/references/{ref['id']}", json={"note": "màu chủ đạo"})
    assert r.json()["references"][0]["note"] == "màu chủ đạo"
    client.put(f"/api/2d/projects/{p2}/references/{ref['id']}")          # dùng lại ở dự án khác, cùng ID
    client.put(f"/api/2d/projects/{p2}/references/{ref['id']}")          # lặp lại không tạo trùng
    assert len(client.get(f"/api/2d/projects/{p2}").json()["references"]) == 1
    assert client.get("/api/2d/references", params={"project_id": p1}).json()["references"][0]["id"] == ref["id"]
    assert client.get("/api/2d/references").json()["references"][0]["used_by"] >= 0
    assert client.put(f"/api/2d/projects/{p1}/references/khongco").status_code == 404

    # xóa dự án KHÔNG xóa tư liệu dùng chung
    client.delete(f"/api/2d/projects/{p1}")
    assert client.get(f"/api/2d/references/{ref['id']}").status_code == 200
    # gỡ liên kết
    assert client.delete(f"/api/2d/projects/{p2}/references/{ref['id']}").json()["references"] == []
    # xóa tư liệu đang gắn với dự án: liên kết biến mất, dự án vẫn còn
    client.put(f"/api/2d/projects/{p2}/references/{ref['id']}")
    client.delete(f"/api/2d/references/{ref['id']}")
    assert client.get(f"/api/2d/projects/{p2}").json()["references"] == []


def test_upload_directly_into_project():
    pid = client.post("/api/2d/projects", json={"name": "Up"}).json()["id"]
    r = upload([("a.png", png(), "image/png")], project_id=pid)
    assert r.status_code == 200
    assert len(client.get(f"/api/2d/projects/{pid}").json()["references"]) == 1
    assert upload([("a.png", png(), "image/png")], project_id="khongco").status_code == 404


# ---------------- Khóa API / .env ----------------

def test_status_never_leaks_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-1234567890abcd")
    body = client.get("/api/2d/status")
    assert body.status_code == 200
    assert "SECRET" not in body.text and "sk-ant" not in body.text
    c = body.json()["providers"]["claude"]
    assert c["configured"] is True and c["masked"].endswith("abcd") and c["verified"] is False
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/2d/status").json()["providers"]["claude"]["configured"] is False


def test_env_file_parsing_does_not_override_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nFOO_S2D=bar\nexport QUOTED_S2D="a b"\nKEEP_S2D=file\n\nbad line\n', encoding="utf-8-sig")
    monkeypatch.setenv("KEEP_S2D", "env")
    for k in ("FOO_S2D", "QUOTED_S2D"):
        monkeypatch.delenv(k, raising=False)
    secret_store.load_env((f,), force=True)
    import os
    assert os.environ["FOO_S2D"] == "bar" and os.environ["QUOTED_S2D"] == "a b" and os.environ["KEEP_S2D"] == "env"
    for k in ("FOO_S2D", "QUOTED_S2D"):
        os.environ.pop(k, None)
    assert secret_store.mask("abcdefghijkl") == "••••••ijkl" and secret_store.mask(None) is None


# ---------------- Smoke test Audio: không bị ảnh hưởng ----------------

def test_audio_routes_still_work_and_are_independent():
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/engines").status_code == 200
    r = client.post("/api/segmenter/parse", json={"text": "Xin chào. Hôm nay trời đẹp!"})
    assert [s["text"] for s in r.json()["segments"]] == ["Xin chào.", "Hôm nay trời đẹp!"]

    p = client.post("/api/projects", json={"name": "Audio test", "text": "Một. Hai. Ba."}).json()
    assert len(p["segments"]) == 3
    # dự án 2D tạo sau đó không lọt vào danh sách / lịch sử Audio, và ngược lại
    p2d = client.post("/api/2d/projects", json={"name": "Chỉ 2D"}).json()
    ids_audio = [x["id"] for x in client.get("/api/projects").json()["projects"]]
    assert p["id"] in ids_audio and p2d["id"] not in ids_audio
    assert all(i["project_name"] != "Chỉ 2D" for i in client.get("/api/history").json()["items"])
    assert p["id"] not in [x["id"] for x in client.get("/api/2d/projects").json()["projects"]]

    assert client.patch(f"/api/projects/{p['id']}", json={"name": "Audio đổi tên"}).json()["name"] == "Audio đổi tên"
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    client.delete(f"/api/2d/projects/{p2d['id']}")


def test_audio_tables_unchanged():
    from app.storage import db
    cols = {r["name"] for r in db.query("PRAGMA table_info(projects)")}
    assert cols == {"id", "name", "source_text", "settings", "created_at", "updated_at"}
    scols = {r["name"] for r in db.query("PRAGMA table_info(segments)")}
    assert {"id", "project_id", "idx", "text", "voice", "speed", "status", "raw_hash"} <= scols
