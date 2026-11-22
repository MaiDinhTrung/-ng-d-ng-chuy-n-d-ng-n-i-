from __future__ import annotations

from .base import TTSProvider, VoiceCloningProvider
from .voice_clone_engine import UnavailableCloningProvider
from .zerotts_engine import ZeroTTSEngine

_engines: dict[str, TTSProvider] = {}
cloning_provider: VoiceCloningProvider = UnavailableCloningProvider()


def get_engines() -> dict[str, TTSProvider]:
    if not _engines:
        e = ZeroTTSEngine()
        _engines[e.id] = e
    return _engines


def get_engine(engine_id: str) -> TTSProvider:
    engines = get_engines()
    if engine_id not in engines:
        raise KeyError(f"Không có engine '{engine_id}'")
    return engines[engine_id]
