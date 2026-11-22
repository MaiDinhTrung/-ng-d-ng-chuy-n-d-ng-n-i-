"""WAV/MP3, đổi tốc độ (atempo) và ghép đoạn bằng khoảng lặng thật (mẫu 0)."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import config


class AudioError(RuntimeError):
    pass


def ffmpeg_path() -> str | None:
    return config.find_ffmpeg()


def _run_ffmpeg(args: list[str]) -> None:
    exe = ffmpeg_path()
    if not exe:
        raise AudioError("Không tìm thấy FFmpeg. Cài bằng: winget install Gyan.FFmpeg (hoặc đặt FFMPEG_PATH).")
    proc = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"FFmpeg lỗi: {proc.stderr.strip()[:500]}")


def _tmp_wav(directory: Path) -> Path:
    """File tạm; phải đóng fd ngay vì Windows khóa file đang mở."""
    fd, name = tempfile.mkstemp(suffix=".wav", dir=directory)
    os.close(fd)
    return Path(name)


def write_wav(path: Path, audio: np.ndarray, sr: int) -> float:
    audio = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    sf.write(str(path), audio, sr, subtype="PCM_16")
    return len(audio) / sr


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def apply_speed(src: Path, dst: Path, speed: float) -> float:
    """Áp dụng tốc độ (giữ cao độ) bằng atempo. Trả về thời lượng (giây)."""
    if not 0.5 <= speed <= 2.0:
        raise AudioError("Tốc độ phải trong khoảng 0.5–2.0")
    if abs(speed - 1.0) < 1e-3:
        data, sr = read_wav(src)
        return write_wav(dst, data, sr)
    tmp = _tmp_wav(dst.parent)
    try:
        _run_ffmpeg(["-i", str(src), "-filter:a", f"atempo={speed:.4f}", "-c:a", "pcm_s16le", str(tmp)])
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    info = sf.info(str(dst))
    return info.duration


def silence(ms: int, sr: int) -> np.ndarray:
    return np.zeros(int(round(sr * max(0, ms) / 1000.0)), dtype=np.float32)


def merge_with_pauses(items: list[tuple[Path, int, int]]) -> tuple[np.ndarray, int]:
    """items: [(wav_path, pause_before_ms, pause_after_ms)].

    Khoảng nghỉ giữa hai đoạn = pause_after(đoạn trước) + pause_before(đoạn sau).
    Nghỉ đầu = pause_before đoạn đầu; nghỉ cuối chỉ thêm nếu người dùng đặt tường minh
    (pause_after > 0 ở đoạn cuối).
    """
    if not items:
        raise AudioError("Không có đoạn nào để ghép")
    parts: list[np.ndarray] = []
    sr0: int | None = None
    prev_after = 0
    for i, (path, before, after) in enumerate(items):
        data, sr = read_wav(path)
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            raise AudioError(f"Sample rate không khớp ({sr} ≠ {sr0}) ở {path.name}")
        gap = (before if i == 0 else prev_after + before)
        if gap > 0:
            parts.append(silence(gap, sr0))
        parts.append(data)
        prev_after = after
    if prev_after > 0:
        parts.append(silence(prev_after, sr0))
    return np.concatenate(parts), sr0  # type: ignore[return-value]


class _Sink:
    """Ghi PCM theo luồng vào WAV (RF64 nếu >3.5GB) hoặc MP3 qua ffmpeg stdin."""

    def __init__(self, dst: Path, fmt: str, sr: int, total_frames: int, mp3_kbps: int):
        self.fmt, self.proc, self.sf = fmt, None, None
        if fmt == "wav":
            big = total_frames * 2 > 3_500_000_000   # PCM_16 mono
            self.sf = sf.SoundFile(str(dst), "w", samplerate=sr, channels=1, subtype="PCM_16",
                                   format="RF64" if big else "WAV")
        elif fmt == "mp3":
            exe = ffmpeg_path()
            if not exe:
                raise AudioError("Không tìm thấy FFmpeg (cần để xuất MP3).")
            self.proc = subprocess.Popen(
                [exe, "-y", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                 "-i", "-", "-codec:a", "libmp3lame", "-b:a", f"{mp3_kbps}k", "-f", "mp3", str(dst)],
                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            raise AudioError(f"Định dạng không hỗ trợ: {fmt}")

    def write(self, x: np.ndarray) -> None:
        if self.sf is not None:
            self.sf.write(np.clip(x, -1.0, 1.0))
        else:
            pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            try:
                self.proc.stdin.write(pcm)          # type: ignore[union-attr]
            except BrokenPipeError as e:
                raise AudioError(f"FFmpeg dừng giữa chừng: {self.proc.stderr.read().decode(errors='replace')[:300]}") from e  # type: ignore[union-attr]

    def close(self) -> None:
        if self.sf is not None:
            self.sf.close()
        elif self.proc is not None:
            self.proc.stdin.close()                  # type: ignore[union-attr]
            err = self.proc.stderr.read().decode(errors="replace")  # type: ignore[union-attr]
            if self.proc.wait() != 0:
                raise AudioError(f"FFmpeg lỗi: {err.strip()[:400]}")

    def abort(self) -> None:
        try:
            if self.sf is not None:
                self.sf.close()
            elif self.proc is not None:
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


def merge_to_file(items: list[tuple[Path, int, int]], dst: Path, fmt: str, mp3_kbps: int = 192,
                  progress=None) -> float:
    """Ghép theo luồng (bộ nhớ không đổi dù dài 10 giờ). Cùng quy tắc nghỉ với merge_with_pauses.
    Trả về thời lượng (giây). `progress(done, total)` được gọi sau mỗi đoạn."""
    if not items:
        raise AudioError("Không có đoạn nào để ghép")
    fmt = fmt.lower()
    infos = [sf.info(str(p)) for p, _, _ in items]
    sr = infos[0].samplerate
    for (p, _, _), inf in zip(items, infos):
        if inf.samplerate != sr:
            raise AudioError(f"Sample rate không khớp ({inf.samplerate} ≠ {sr}) ở {p.name}")
    gaps: list[int] = []
    prev_after = 0
    for i, (_, before, after) in enumerate(items):
        gaps.append(before if i == 0 else prev_after + before)
        prev_after = after
    tail = prev_after
    total = sum(i.frames for i in infos) + sum(int(sr * g / 1000) for g in gaps) + int(sr * tail / 1000)

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")          # ghi dở không đè lên file cũ
    sink = _Sink(tmp, fmt, sr, total, mp3_kbps)
    ok = False
    try:
        def put_silence(ms: int) -> None:
            n = int(round(sr * ms / 1000.0))
            while n > 0:
                k = min(n, sr * 10)
                sink.write(np.zeros(k, dtype=np.float32)); n -= k

        for i, ((path, _, _), gap) in enumerate(zip(items, gaps)):
            if gap > 0:
                put_silence(gap)
            with sf.SoundFile(str(path)) as f:
                while True:
                    blk = f.read(1 << 20, dtype="float32", always_2d=True)
                    if len(blk) == 0:
                        break
                    sink.write(blk.mean(axis=1))
            if progress:
                progress(i + 1, len(items))
        if tail > 0:
            put_silence(tail)
        sink.close(); ok = True
    finally:
        if not ok:
            sink.abort(); tmp.unlink(missing_ok=True)
    tmp.replace(dst)
    return total / sr


def save_as(audio: np.ndarray, sr: int, dst: Path, fmt: str, mp3_kbps: int = 192) -> None:
    fmt = fmt.lower()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "wav":
        write_wav(dst, audio, sr)
    elif fmt == "mp3":
        tmp = _tmp_wav(dst.parent)
        try:
            write_wav(tmp, audio, sr)
            _run_ffmpeg(["-i", str(tmp), "-codec:a", "libmp3lame", "-b:a", f"{mp3_kbps}k", str(dst)])
        finally:
            tmp.unlink(missing_ok=True)
    else:
        raise AudioError(f"Định dạng không hỗ trợ: {fmt}")


def convert_file(src: Path, dst: Path, fmt: str, mp3_kbps: int = 192) -> None:
    data, sr = read_wav(src)
    save_as(data, sr, dst, fmt, mp3_kbps)
