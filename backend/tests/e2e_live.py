"""Chạy: python tests/e2e_live.py  (server phải đang chạy ở :8000, model thật)."""
import io
import sys
import time
from pathlib import Path

import httpx
import soundfile as sf

B = "http://127.0.0.1:8000/api"
c = httpx.Client(timeout=300)


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        sys.exit(1)


r = c.get(f"{B}/voices").json()
names = [v["id"] for v in r["voices"]]
ok(len(names) == 8, f"8 giọng: {names}")
ok(r["cloning"]["available"] is False, f"clone báo: {r['cloning']['reason']}")
ok(c.post(f"{B}/voices/clone").status_code == 501, "POST /voices/clone -> 501")

# preview
t = time.time()
w = c.post(f"{B}/tts/preview", json={"text": "Xin chào các bạn.", "voice": "maichi", "speed": 1.0})
ok(w.status_code == 200, f"preview 200 ({time.time()-t:.1f}s)")
d, sr = sf.read(io.BytesIO(w.content))
ok(sr == 48000 and len(d) > 48000 * 0.5, f"preview wav {len(d)/sr:.2f}s")
w2 = c.post(f"{B}/tts/preview", json={"text": "Xin chào các bạn.", "voice": "maichi", "speed": 1.5})
d2, _ = sf.read(io.BytesIO(w2.content))
ok(len(d2) < len(d) * 0.85, f"speed 1.5 ngắn hơn ({len(d2)/sr:.2f}s < {len(d)/sr:.2f}s)")

# project
text = "Xin chào các bạn. [pause=1000] Hôm nay trời đẹp quá...\nChúc mọi người một ngày vui vẻ."
p = c.post(f"{B}/projects", json={"name": "Test e2e", "text": text, "settings": {"voice": "maichi"}}).json()
segs = p["segments"]
print([(s["text"], s["pause_before"], s["pause_after"]) for s in segs])
ok(len(segs) == 3, "3 đoạn")
ok(all("pause" not in s["text"].lower() for s in segs), "thẻ pause không nằm trong text")
ok(segs[0]["pause_after"] == 1000, "pause=1000 đặt cho đoạn 1")
ok(segs[1]["pause_after"] == 800 or segs[1]["pause_after"] == 800, "ellipsis/newline nghỉ dài")
pid = p["id"]

# export khi chưa tạo -> lỗi rõ ràng
ok(c.post(f"{B}/projects/{pid}/export", json={"format": "wav"}).status_code == 400, "export trước khi tạo -> 400")

ok(c.post(f"{B}/projects/{pid}/generate", json={}).json()["queued"] == 3, "queued 3")


def wait_all(pid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        pr = c.get(f"{B}/projects/{pid}").json()
        if all(s["status"] in ("completed", "failed") for s in pr["segments"]):
            return pr
        time.sleep(1)
    raise SystemExit("timeout")


pr = wait_all(pid)
ok(all(s["status"] == "completed" for s in pr["segments"]), f"tất cả completed: {[s['status'] for s in pr['segments']]} {[s['error'] for s in pr['segments']]}")
for s in pr["segments"]:
    a = c.get(f"{B}/segments/{s['id']}/audio")
    ok(a.status_code == 200 and sf.info(io.BytesIO(a.content)).duration > 0.3, f"audio đoạn {s['idx']+1} {s['duration']:.2f}s")

# tạo lại 1 đoạn, đoạn khác không đổi
before = {s["id"]: (s["updated_at"], Path(f"data/audio/{s['id']}.wav").stat().st_mtime_ns) for s in pr["segments"]}
time.sleep(1.1)
target = pr["segments"][1]["id"]
c.post(f"{B}/segments/{target}/regenerate")
time.sleep(0.5)
pr2 = wait_all(pid)
for s in pr2["segments"]:
    m = Path(f"data/audio/{s['id']}.wav").stat().st_mtime_ns
    if s["id"] == target:
        ok(m != before[s["id"]][1], "đoạn 2 được tạo lại")
    else:
        ok(m == before[s["id"]][1], f"đoạn {s['idx']+1} không bị tạo lại")

# đổi tốc độ 1 đoạn: tái dựng từ raw, không gọi model
s0 = pr2["segments"][0]
u = c.patch(f"{B}/segments/{s0['id']}", json={"speed": 1.25}).json()
ok(u["status"] == "completed" and u["duration"] < s0["duration"] * 0.9, f"speed đoạn 1: {s0['duration']:.2f}->{u['duration']:.2f}s")

# sửa text -> pending, chỉ đoạn đó
u = c.patch(f"{B}/segments/{pr2['segments'][2]['id']}", json={"text": "Chúc các bạn một ngày thật vui."}).json()
ok(u["status"] == "pending", "sửa text -> pending")
ok(c.patch(f"{B}/segments/{pr2['segments'][2]['id']}", json={"text": "a [pause=5] b"}).status_code == 400, "text chứa thẻ pause bị từ chối")
c.post(f"{B}/projects/{pid}/generate", json={})
pr3 = wait_all(pid)
ok(all(s["status"] == "completed" for s in pr3["segments"]), "tạo lại phần pending xong")

# refresh: dữ liệu còn nguyên
ok(len(c.get(f"{B}/projects").json()["projects"]) >= 1, "list projects")

# export merged
tmp = Path("data/e2e_out")


def do_export(body):
    e = c.post(f"{B}/projects/{pid}/export", json=body)
    ok(e.status_code == 200, f"export {body['format']}/{body['mode']} nhận job: {e.text[:100]}")
    while True:
        j = c.get(f"{B}/jobs/{e.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.5)
    ok(j["status"] == "done", f"job xong: {j['error']}")
    return j["result"]


for fmt in ("wav", "mp3"):
    res = do_export({"format": fmt, "mode": "merged", "output_dir": str(tmp.resolve())})
    f = Path(res["files"][0])
    info = sf.info(str(f))
    segs3 = pr3["segments"]
    expected = sum(s["duration"] for s in segs3) + (segs3[0]["pause_before"] + sum(s["pause_after"] + segs3[i + 1]["pause_before"] for i, s in enumerate(segs3[:-1])) + segs3[-1]["pause_after"]) / 1000
    ok(abs(info.duration - expected) < 0.15, f"{fmt} dài {info.duration:.2f}s ≈ kỳ vọng {expected:.2f}s (đoạn + khoảng lặng)")
e = do_export({"format": "wav", "mode": "segments", "output_dir": str(tmp.resolve())})
ok(len(e["files"]) == 3 and all(Path(x).exists() for x in e["files"]), "xuất từng đoạn 3 file")

# xóa đoạn + xóa project dọn audio
sid = pr3["segments"][0]["id"]
c.delete(f"{B}/segments/{sid}")
ok(not Path(f"data/audio/{sid}.wav").exists(), "xóa đoạn xóa file audio")
ids = [s["id"] for s in c.get(f"{B}/projects/{pid}").json()["segments"]]
c.delete(f"{B}/projects/{pid}")
ok(c.get(f"{B}/projects/{pid}").status_code == 404, "xóa project")
ok(not any(Path(f"data/audio/{i}.wav").exists() for i in ids), "xóa project xóa audio liên quan")
print("ALL OK")
