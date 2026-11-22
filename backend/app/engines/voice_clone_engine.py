"""Provider clone tạm thời: báo rõ là chưa có engine tương thích.

ZeroTTS 0.1.x không công bố voice encoder nên không thể tạo giọng từ file audio
(xem zerotts/voices.py). Chỉ nạp được voice pack (.zip/.npz) đã có sẵn. Khi có engine
clone tiếng Việt với giấy phép phù hợp, hãy viết một VoiceCloningProvider thật và
đăng ký trong engines/__init__.py.
"""
from __future__ import annotations

from .base import CloneNotSupported, VoiceCloningProvider, VoiceInfo

REASON = "Chưa có engine clone tương thích"


class UnavailableCloningProvider(VoiceCloningProvider):
    id = "none"
    name = "Không có"

    def check_availability(self) -> dict:
        return {"available": False, "reason": REASON}

    def validate_reference_audio(self, path: str) -> dict:
        raise CloneNotSupported(REASON)

    def create_voice(self, name, reference_audio, consent_confirmed, **meta) -> VoiceInfo:
        raise CloneNotSupported(REASON)

    def list_custom_voices(self) -> list[VoiceInfo]:
        return []

    def delete_voice(self, voice_id: str) -> None:
        raise CloneNotSupported(REASON)

    def synthesize_with_voice(self, text, voice_id, **options):
        raise CloneNotSupported(REASON)
