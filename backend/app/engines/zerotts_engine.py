"""Adapter cho ZeroTTS (MIT, ONNX, CPU). API đã đối chiếu với source zerotts 0.1.5."""
from __future__ import annotations

import threading

import numpy as np

from .. import config
from .base import Capabilities, TTSProvider, VoiceInfo


def _patch_zerotts_utf8() -> None:
    """zerotts 0.1.5 đọc meta.json bằng read_text() không encoding → trên Windows dùng cp1252
    và lỗi với tên tiếng Việt (huuduc, kimoanh, tiendat). Thay bằng bản đọc UTF-8."""
    import json
    from pathlib import Path

    from zerotts import voices as zv

    if getattr(zv, "_utf8_patched", False):
        return

    def load_voice_dir(vdir, name=None, expect_queries=None):
        vdir = Path(vdir)
        name = name or vdir.name
        npz = vdir / "voice.npz"
        if not npz.exists():
            raise FileNotFoundError(f"{vdir} is not a voice pack: no voice.npz in it")
        data = np.load(npz)
        emb = np.asarray(data["voice_emb"], dtype=np.float32)
        if emb.ndim == 2:
            emb = emb[None, :, :]
        stored_q = int(data["n_voice_queries"]) if "n_voice_queries" in data else int(emb.shape[1])
        if stored_q != emb.shape[1]:
            raise ValueError(f"voice {name!r} inconsistent: n_voice_queries={stored_q} vs {emb.shape[1]}")
        if expect_queries is not None and stored_q != expect_queries:
            raise ValueError(f"voice {name!r} built for n_voice_queries={stored_q}, model uses {expect_queries}")
        mp = vdir / "meta.json"
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        prev = vdir / "preview.wav"
        return zv.Voice(name=name, emb=emb, meta=meta, preview_path=str(prev) if prev.exists() else None)

    zv.load_voice_dir = load_voice_dir
    zv._utf8_patched = True


class ZeroTTSEngine(TTSProvider):
    id = "zerotts"
    name = "ZeroTTS (tiếng Việt, CPU)"
    license = "Mã nguồn + trọng số: MIT. Giọng đi kèm: 'for evaluation and demos' theo model card."

    def __init__(self, repo_id: str = "zeroweight-ai/ZeroTTS"):
        self.repo_id = repo_id
        self._tts = None
        self._state = "idle"          # idle | loading | ready | error
        self._error: str | None = None
        self._lock = threading.Lock()  # ONNX session: chỉ chạy 1 yêu cầu một lúc
        self._load_lock = threading.Lock()

    # ---- vòng đời ----
    def start_loading(self) -> None:
        with self._load_lock:
            if self._state in ("loading", "ready"):
                return
            self._state = "loading"
        threading.Thread(target=self._load, daemon=True, name="zerotts-load").start()

    def _load(self) -> None:
        try:
            _patch_zerotts_utf8()
            from zerotts import ZeroTTS

            self._tts = ZeroTTS.from_pretrained(self.repo_id, intra_op_num_threads=config.TTS_THREADS)
            self._state, self._error = "ready", None
        except Exception as e:  # noqa: BLE001 - báo nguyên nhân thật lên UI
            self._state, self._error = "error", f"{type(e).__name__}: {e}"

    def is_available(self) -> bool:
        return self._state == "ready"

    def status(self) -> dict:
        return {"state": self._state, "error": self._error}

    # ---- giọng ----
    def get_voices(self) -> list[VoiceInfo]:
        if not self._tts:
            return []
        custom = set(self._tts._extra_voices)  # noqa: SLF001 - không có API công khai
        out = []
        for name in self._tts.list_voices():
            try:
                v = self._tts.load_voice(name)
            except Exception:  # noqa: BLE001
                continue
            out.append(VoiceInfo(
                id=name, name=v.display_name, gender=v.gender,
                region=str(v.meta.get("region", v.meta.get("accent", ""))),
                description=v.description, tags=v.tags,
                source="custom" if name in custom else "builtin",
                has_preview=bool(v.preview_path),
            ))
        return out

    def voice_preview_path(self, voice_id: str) -> str | None:
        if not self._tts:
            return None
        return self._tts.load_voice(voice_id).preview_path

    def add_voice_zip(self, path: str) -> list[str]:
        if not self._tts:
            raise RuntimeError("Engine chưa sẵn sàng")
        with self._lock:
            return self._tts.add_voices(path)

    def remove_custom_voice(self, voice_id: str) -> None:
        import shutil

        if not self._tts:
            raise RuntimeError("Engine chưa sẵn sàng")
        vdir = self._tts._extra_voices.get(voice_id)  # noqa: SLF001
        if vdir is None:
            raise KeyError("Chỉ xóa được giọng do người dùng thêm")
        shutil.rmtree(vdir, ignore_errors=True)
        self._tts._extra_voices.pop(voice_id, None)  # noqa: SLF001

    # ---- tổng hợp ----
    def synthesize(self, text: str, voice: str | None, **options) -> tuple[np.ndarray, int]:
        if not self._tts:
            raise RuntimeError(f"Engine chưa sẵn sàng (state={self._state}: {self._error})")
        if options.get("normalize", True):
            from zerotts import normalize_vi_text
            from zerotts.chunking import clean_segment_punctuation

            text = clean_segment_punctuation(normalize_vi_text(text))
        if not text.strip():
            raise ValueError("Đoạn rỗng sau khi chuẩn hóa")
        with self._lock:
            audio = self._tts.synthesize(text, voice=voice)
        return np.asarray(audio, dtype=np.float32).reshape(-1), self._tts.sample_rate

    def get_capabilities(self) -> Capabilities:
        return Capabilities(
            speed_control=False, voice_cloning=False, streaming=True,
            sample_rate=48000,
            notes="ZeroTTS không có tham số tốc độ: tốc độ được áp dụng bằng FFmpeg atempo sau khi tạo. "
                  "Chưa có voice encoder nên không clone từ file audio; chỉ nạp voice pack có sẵn.",
        )
