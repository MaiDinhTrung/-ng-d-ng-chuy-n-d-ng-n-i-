"""Đo RTF thật qua API (server phải chạy). python tests/bench_rtf.py"""
import time

import httpx

B = "http://127.0.0.1:8000/api"
c = httpx.Client(timeout=600)
s = ["Hôm nay chúng ta cùng tìm hiểu một câu chuyện rất thú vị về làng quê Việt Nam.",
     "Ngày xưa, có một cậu bé sống bên dòng sông nhỏ, mỗi sáng đều dậy sớm ra đồng.",
     "Cậu thường nghe tiếng chim hót, tiếng gió thổi qua những ngọn tre xanh.",
     "Mọi người trong làng đều yêu quý cậu vì sự chăm chỉ và tốt bụng của cậu."]
text = " ".join(s * 10)
p = c.post(B + "/projects", json={"name": "bench", "text": text, "settings": {"voice": "maichi"}}).json()
print("segments", len(p["segments"]), "chars", len(text), flush=True)
t = time.time()
c.post(f"{B}/projects/{p['id']}/generate", json={})
while True:
    q = c.get(f"{B}/projects/{p['id']}").json()
    if all(x["status"] in ("completed", "failed") for x in q["segments"]):
        break
    time.sleep(1)
w = time.time() - t
d = sum(x["duration"] or 0 for x in q["segments"])
fails = sum(x["status"] == "failed" for x in q["segments"])
print("wall_s", round(w, 1), "audio_s", round(d, 1), "RTF", round(w / d, 2),
      "-> 1 gio audio ~", round(w / d * 60), "phut", "| failed:", fails, flush=True)
c.delete(B + "/projects/" + p["id"])
