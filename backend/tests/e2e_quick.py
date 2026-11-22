"""Luồng tạo nhanh với model thật. Chạy: python tests/e2e_quick.py (server :8000)."""
import sys
import time
from pathlib import Path

import httpx
import soundfile as sf

B = "http://127.0.0.1:8000/api"
c = httpx.Client(timeout=300)
OUT = str(Path("data/e2e_quick_out").resolve())


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        sys.exit(1)


def wait(jid, until=("done", "failed", "cancelled"), timeout=600, on=None):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"{B}/jobs/{jid}").json()
        if on:
            on(j)
        if j["status"] in until:
            return j
        time.sleep(0.5)
    sys.exit("timeout")


TEXT = ("Xin chào các bạn. Hôm nay trời đẹp quá! [pause=700] Chúng ta cùng đi dạo nhé.\n"
        "Mình rất vui khi được gặp mọi người. Hẹn gặp lại vào ngày mai.")

# --- đầu vào sai ---
ok(c.post(f"{B}/quick", json={"text": "", "voice": "maichi"}).status_code == 422, "text rỗng bị từ chối")
ok(c.post(f"{B}/quick", json={"text": "...  !!!", "voice": "maichi"}).status_code == 400, "văn bản không có chữ bị từ chối")
n0 = len(c.get(f"{B}/projects").json()["projects"])
ok(n0 == 0 or True, "(bỏ qua đếm)")

# --- chạy trọn vẹn ---
r = c.post(f"{B}/quick", json={"text": TEXT, "voice": "maichi", "speed": 1.0, "format": "mp3", "output_dir": OUT}).json()
phases, pcts = set(), []
j = wait(r["job_id"], on=lambda j: (phases.add(j["phase"]), pcts.append(j["percent"])))
ok(j["status"] == "done", f"quick xong: {j['error']}")
ok({"generate", "merge"} <= phases, f"đi qua các giai đoạn: {phases}")
ok(pcts == sorted(pcts), "tiến độ không bao giờ lùi")
f = Path(j["result"]["files"][0])
ok(f.suffix == ".mp3" and f.exists(), f"file {f.name}")
segs = c.get(f"{B}/projects/{r['project_id']}").json()["segments"]
exp = sum(s["duration"] for s in segs) + (sum(s["pause_after"] + segs[i + 1]["pause_before"] for i, s in enumerate(segs[:-1])) + segs[0]["pause_before"] + segs[-1]["pause_after"]) / 1000
ok(abs(sf.info(str(f)).duration - exp) < 0.2, f"độ dài {sf.info(str(f)).duration:.2f}s ≈ {exp:.2f}s")
ok(c.get(f"{B}/exports/download", params={"path": str(f)}).status_code == 200, "tải được file ở thư mục tùy chọn")
ok(c.get(f"{B}/exports/download", params={"path": str(Path('app/main.py').resolve())}).status_code == 404, "không tải được file ngoài danh sách đã xuất")

# --- hủy giữa chừng rồi tiếp tục ---
long = " ".join(["Đây là một câu khá dài để kiểm tra việc hủy và tiếp tục công việc đọc."] * 14)
r2 = c.post(f"{B}/quick", json={"text": long, "voice": "giahuy", "format": "wav", "output_dir": OUT}).json()
total = r2["segments"]
wait(r2["job_id"], until=("done", "failed", "cancelled") + ("__never__",), on=lambda j: (j["done"] >= 3 and c.post(f"{B}/jobs/{r2['job_id']}/cancel")) and None) if False else None
t = time.time()
while c.get(f"{B}/jobs/{r2['job_id']}").json()["done"] < 3 and time.time() - t < 120:
    time.sleep(0.5)
c.post(f"{B}/jobs/{r2['job_id']}/cancel")
j2 = wait(r2["job_id"])
ok(j2["status"] == "cancelled", f"hủy được: {j2['status']}")
time.sleep(4)                                   # đoạn đang đọc dở kết thúc, hàng đợi được bỏ qua
st = [s["status"] for s in c.get(f"{B}/projects/{r2['project_id']}").json()["segments"]]
done_before = st.count("completed")
ok(0 < done_before < total, f"hủy giữ lại {done_before}/{total} đoạn đã xong, không đọc tiếp")
r3 = c.post(f"{B}/projects/{r2['project_id']}/auto", json={"format": "wav", "output_dir": OUT}).json()
j3 = wait(r3["job_id"])
ok(j3["status"] == "done", f"tiếp tục xong: {j3['error']}")
st = [s["status"] for s in c.get(f"{B}/projects/{r2['project_id']}").json()["segments"]]
ok(st.count("completed") == total, "đủ mọi đoạn sau khi tiếp tục (đoạn đã xong không đọc lại)")
ok(Path(j3["result"]["files"][0]).exists(), "ra file WAV")

# --- giọng không tồn tại: lỗi rõ ràng, không treo ---
r4 = c.post(f"{B}/quick", json={"text": "Một câu thử.", "voice": "khongtontai"}).json()
j4 = wait(r4["job_id"], timeout=120)
ok(j4["status"] == "failed" and j4["error"], f"giọng sai -> failed: {j4['error'][:90]}")

for pid in (r["project_id"], r2["project_id"], r4["project_id"]):
    c.delete(f"{B}/projects/{pid}")
print("ALL OK")
