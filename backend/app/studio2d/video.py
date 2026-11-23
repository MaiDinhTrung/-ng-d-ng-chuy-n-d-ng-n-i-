"""Animation Director + Video Editor bằng FFmpeg: pan/zoom/rung camera, hiệu ứng ánh sáng, chuyển cảnh, phụ đề, nhạc nền.

Chưa có: parallax (cần ảnh tách lớp), âm thanh hiệu ứng (SFX), video generation API. Xem docs/2D_AGENT.md.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from pathlib import Path

import numpy as np

from ..services import audio_service
from . import imaging, projects, scenes, store

SIZES = {  # (rộng, cao, fps, crf, preset)
    ("final", "16:9"): (1920, 1080, 30, 20, "medium"), ("final", "9:16"): (1080, 1920, 30, 20, "medium"),
    ("final", "1:1"): (1080, 1080, 30, 20, "medium"),
    ("preview", "16:9"): (640, 360, 15, 30, "ultrafast"), ("preview", "9:16"): (360, 640, 15, 30, "ultrafast"),
    ("preview", "1:1"): (480, 480, 15, 30, "ultrafast"),
}
TAIL = 0.3          # giây lặng sau lời dẫn
TRANS_D = 0.6       # thời lượng chuyển cảnh
MIN_SCENE = 1.5
SR = 48000


class RenderError(RuntimeError):
    pass


def _ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    exe = audio_service.ffmpeg_path()
    if not exe:
        raise RenderError("Không tìm thấy FFmpeg")
    p = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=cwd)
    if p.returncode != 0:
        raise RenderError(f"FFmpeg lỗi: {p.stderr.strip()[-600:]}")


def scene_length(sc: dict) -> float:
    """Thời lượng 'chiếm' trên timeline: theo lời dẫn nếu đã có audio, ngược lại theo thời lượng dự kiến."""
    if sc["audio_file"] and sc["audio_duration"]:
        return max(MIN_SCENE, sc["audio_duration"] + TAIL)
    return max(MIN_SCENE, float(sc["duration"]))


def trans_d(next_scene: dict | None, fps: int) -> float:
    if not next_scene:
        return 0.0
    return 2.0 / fps if next_scene["transition"] == "cut" else TRANS_D


def motion_filter(move: str, frames: int, w: int, h: int) -> str:
    n = max(2, frames)
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if move == "zoom_in":
        z, x, y = f"1+0.14*on/{n}", cx, cy
    elif move == "zoom_out":
        z, x, y = f"1.14-0.14*on/{n}", cx, cy
    elif move == "pan_left":
        z, x, y = "1.15", f"(iw-iw/zoom)*(1-on/{n})", cy
    elif move == "pan_right":
        z, x, y = "1.15", f"(iw-iw/zoom)*on/{n}", cy
    elif move == "pan_up":
        z, x, y = "1.15", cx, f"(ih-ih/zoom)*(1-on/{n})"
    elif move == "pan_down":
        z, x, y = "1.15", cx, f"(ih-ih/zoom)*on/{n}"
    elif move == "shake":
        z, x, y = "1.07", f"{cx}+sin(on*1.9)*iw*0.007", f"{cy}+cos(on*2.7)*ih*0.007"
    else:
        z, x, y = "1", cx, cy
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}"      # d=1 + loop: mỗi khung hình đầu vào -> 1 khung ra


def effect_filter(effect: str) -> str:
    return {"vignette": "vignette=PI/5", "warm": "colorbalance=rs=.08:gs=.02:bs=-.08",
            "cool": "colorbalance=rs=-.06:bs=.1", "flash": "fade=t=in:st=0:d=0.35:color=white"}.get(effect, "")


def clip_hash(sc: dict, img_sha: str, length: float, w: int, h: int, fps: int) -> str:
    key = f"{img_sha}|{sc['camera_movement']}|{sc['effect']}|{length:.3f}|{w}x{h}|{fps}|v1"
    return hashlib.sha1(key.encode()).hexdigest()


def clip_path(pid: str, sid: str, w: int, h: int) -> Path:
    return projects.project_dir(pid) / "clips" / f"{sid}_{w}x{h}.mp4"


def scene_image(sc: dict) -> tuple[Path, str]:
    if not sc["image_gen_id"]:
        raise RenderError(f"Cảnh {sc['idx'] + 1} chưa có ảnh")
    g = imaging.get_generation(sc["image_gen_id"])
    path = projects.project_dir(sc["project_id"]) / g["file"]
    if not path.exists():
        raise RenderError(f"File ảnh của cảnh {sc['idx'] + 1} không còn trên đĩa")
    return path, g["sha256"] or ""


def render_clip(sid: str, kind: str, size_override: tuple[int, int, int] | None = None, force: bool = False) -> dict:
    """Dựng clip chuyển động cho 1 cảnh. Bỏ qua nếu ảnh/chuyển động/thời lượng không đổi (cache theo hash)."""
    sc = scenes.get(sid)
    pid = sc["project_id"]
    p = projects.get_project(pid)
    w, h, fps, crf, preset = SIZES[(kind, p["aspect_ratio"])]
    if size_override:
        w, h, fps = size_override
    scs = scenes.list_for_project(pid)
    nxt = scs[sc["idx"] + 1] if sc["idx"] + 1 < len(scs) else None
    length = scene_length(sc) + trans_d(nxt, fps)
    img, sha = scene_image(sc)
    h_new = clip_hash(sc, sha, length, w, h, fps)
    dst = clip_path(pid, sid, w, h)
    meta = dst.with_suffix(".hash")
    if not force and dst.exists() and meta.exists() and meta.read_text() == h_new:
        return {"skipped": True, "file": dst, "hash": h_new, "length": length}
    dst.parent.mkdir(parents=True, exist_ok=True)
    frames = int(round(length * fps))
    vf = [f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase", f"crop={w * 2}:{h * 2}",
          motion_filter(sc["camera_movement"], frames, w, h), f"fps={fps}"]
    ef = effect_filter(sc["effect"])
    if ef:
        vf.append(ef)
    vf.append("format=yuv420p")
    tmp = dst.with_suffix(".tmp.mp4")
    _ffmpeg(["-loop", "1", "-framerate", str(fps), "-i", str(img), "-vf", ",".join(vf), "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-an", str(tmp)])
    tmp.replace(dst)
    meta.write_text(h_new)
    return {"skipped": False, "file": dst, "hash": h_new, "length": length}


# ---------------- phụ đề ----------------

def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def make_srt(items: list[tuple[float, float, str]], max_chars: int = 70) -> str:
    out, n = [], 1
    for start, dur, text in items:
        parts = [x.strip() for x in re.split(r"(?<=[.!?…])\s+|\n", text) if x.strip()]
        chunks: list[str] = []
        for part in parts:
            while len(part) > max_chars:
                cut = part.rfind(" ", 0, max_chars)
                cut = cut if cut > 20 else max_chars
                chunks.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                chunks.append(part)
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = dur * len(c) / total
            out.append(f"{n}\n{_ts(t)} --> {_ts(t + d)}\n{c}\n")
            n += 1
            t += d
    return "\n".join(out)


# ---------------- ghép video ----------------

def _speech_track(scs: list[dict], pid: str, lengths: list[float]) -> Path:
    parts = []
    for sc, L in zip(scs, lengths):
        buf = np.zeros(int(round(L * SR)), dtype=np.float32)
        if sc["audio_file"]:
            f = projects.project_dir(pid) / sc["audio_file"]
            if f.exists():
                data, sr = audio_service.read_wav(f)
                if sr != SR:
                    raise RenderError(f"Sample rate của audio cảnh {sc['idx'] + 1} là {sr}, cần {SR}")
                data = data[: len(buf)]
                buf[: len(data)] = data
        parts.append(buf)
    out = projects.project_dir(pid) / "renders" / f"speech_{uuid.uuid4().hex[:6]}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_service.write_wav(out, np.concatenate(parts), SR)
    return out


def render_hash(scs: list[dict], clip_hashes: list[str], kind: str, meta: dict, w: int, h: int, bgm_sig: str) -> str:
    key = "|".join([kind, f"{w}x{h}", str(meta["subtitles"]), bgm_sig, str(meta["bgm_volume"]),
                    *[f"{c}:{s['transition']}:{s['audio_hash']}:{s['narration']}" for c, s in zip(clip_hashes, scs)]])
    return hashlib.sha1(key.encode()).hexdigest()


def assemble(pid: str, kind: str, clip_files: list[Path], clip_hashes: list[str],
             size_override: tuple[int, int, int] | None = None, ctx=None) -> dict:
    scs = scenes.list_for_project(pid)
    p = projects.get_project(pid)
    w, h, fps, crf, preset = SIZES[(kind, p["aspect_ratio"])]
    if size_override:
        w, h, fps = size_override
    meta = dict(store.query("SELECT * FROM s2d_meta WHERE project_id=?", (pid,))[0])
    bgm = projects.project_dir(pid) / meta["bgm_file"] if meta["bgm_file"] else None
    if bgm and not bgm.exists():
        bgm = None
    rh = render_hash(scs, clip_hashes, kind, meta, w, h, f"{bgm.name}:{bgm.stat().st_size}" if bgm else "")
    existing = store.query("SELECT * FROM s2d_renders WHERE project_id=? AND hash=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                           (pid, rh, kind))
    if existing and (projects.project_dir(pid) / existing[0]["file"]).exists():
        return {"skipped": True, **dict(existing[0])}

    lengths = [scene_length(s) for s in scs]
    trans = [trans_d(scs[i + 1] if i + 1 < len(scs) else None, fps) for i in range(len(scs))]
    rid = uuid.uuid4().hex[:12]
    rdir = projects.project_dir(pid) / "renders"
    rdir.mkdir(parents=True, exist_ok=True)
    out_rel = f"renders/{rid}_{kind}.mp4"
    speech = _speech_track(scs, pid, lengths)
    srt_name = None
    try:
        starts = [sum(lengths[:i]) for i in range(len(scs))]
        if meta["subtitles"]:
            srt_name = f"{rid}.srt"
            (rdir / srt_name).write_text(make_srt([(starts[i], lengths[i] - TAIL, s["narration"]) for i, s in enumerate(scs)
                                                   if s["narration"].strip()]), encoding="utf-8")
        args: list[str] = []
        for f in clip_files:
            args += ["-i", str(f)]
        args += ["-i", str(speech)]
        n = len(clip_files)
        a_idx = n
        parts = []
        if n == 1:
            last = "[0:v]"
        else:
            last = "[0:v]"
            for i in range(1, n):
                nm = scs[i]["transition"] if scs[i]["transition"] != "cut" else "fade"
                parts.append(f"{last}[{i}:v]xfade=transition={nm}:duration={trans[i - 1]:.3f}:offset={starts[i]:.3f}[v{i}]")
                last = f"[v{i}]"
        if srt_name:
            style = f"FontName=Arial,FontSize={max(10, int(h / 38))},Outline=2,Shadow=0,MarginV={int(h / 18)}"
            parts.append(f"{last}subtitles={srt_name}:force_style='{style}'[vs]")
            last = "[vs]"
        if bgm:
            args += ["-stream_loop", "-1", "-i", str(bgm)]
            parts.append(f"[{a_idx + 1}:a]volume={meta['bgm_volume']}[bg]")
            parts.append(f"[{a_idx}:a][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
            amap = "[aout]"
        else:
            amap = f"{a_idx}:a"
        filt = ";".join(parts) if parts else None
        cmd = args[:]
        if filt:
            cmd += ["-filter_complex", filt, "-map", last]
        else:
            cmd += ["-map", last.strip("[]") if last != "[0:v]" else "0:v"]
        cmd += ["-map", amap, "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-t", f"{sum(lengths):.3f}", "-movflags", "+faststart",
                out_rel.split("/")[-1]]
        if ctx:
            ctx.log(f"FFmpeg ghép {n} cảnh → {out_rel} ({w}x{h}, {fps}fps)")
        _ffmpeg(cmd, cwd=rdir)            # chạy trong thư mục renders: tên .srt tương đối, tránh lỗi đường dẫn Windows
    finally:
        speech.unlink(missing_ok=True)
        if srt_name:
            (rdir / srt_name).unlink(missing_ok=True)
    total = sum(lengths)
    with store.tx() as c:
        c.execute("INSERT INTO s2d_renders(id,project_id,kind,file,hash,duration,width,height,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (rid, pid, kind, out_rel, rh, total, w, h, store.now()))
    return {"skipped": False, "id": rid, "file": out_rel, "hash": rh, "duration": total, "width": w, "height": h}
