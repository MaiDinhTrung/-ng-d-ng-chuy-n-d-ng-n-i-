"""Interface cho TTS engine và voice cloning. Engine mới chỉ cần implement lớp này."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class VoiceInfo:
    id: str
    name: str
    gender: str = ""
    region: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"          # builtin | custom
    has_preview: bool = False


@dataclass
class Capabilities:
    speed_control: bool = False       # engine tự hỗ trợ tốc độ (nếu False: hậu kỳ bằng FFmpeg)
    voice_cloning: bool = False
    streaming: bool = False
    languages: list[str] = field(default_factory=lambda: ["vi"])
    sample_rate: int = 48000
    notes: str = ""


class TTSProvider(ABC):
    id: str
    name: str
    license: str = ""

    @abstractmethod
    def is_available(self) -> bool: ...

    def status(self) -> dict:
        return {"state": "ready" if self.is_available() else "unavailable", "error": None}

    @abstractmethod
    def get_voices(self) -> list[VoiceInfo]: ...

    @abstractmethod
    def synthesize(self, text: str, voice: str | None, **options) -> tuple[np.ndarray, int]:
        """Trả về (mono float32 1-D, sample_rate)."""

    @abstractmethod
    def get_capabilities(self) -> Capabilities: ...


class CloneNotSupported(RuntimeError):
    pass


class VoiceCloningProvider(ABC):
    id: str
    name: str

    @abstractmethod
    def check_availability(self) -> dict:
        """{'available': bool, 'reason': str}"""

    @abstractmethod
    def validate_reference_audio(self, path: str) -> dict: ...

    @abstractmethod
    def create_voice(self, name: str, reference_audio: str, consent_confirmed: bool, **meta) -> VoiceInfo: ...

    @abstractmethod
    def list_custom_voices(self) -> list[VoiceInfo]: ...

    @abstractmethod
    def delete_voice(self, voice_id: str) -> None: ...

    @abstractmethod
    def synthesize_with_voice(self, text: str, voice_id: str, **options) -> tuple[np.ndarray, int]: ...
