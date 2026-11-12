"""Sound for screen recording on Windows through `soundcard` (WASAPI): the microphone, and the
computer's sound as the default speakers' loopback. Both hand over 48 kHz stereo float32 blocks."""
from __future__ import annotations

from .sound_common import SoundcardSource


def _loopback():
    import soundcard
    return soundcard.get_microphone(str(soundcard.default_speaker().name), include_loopback=True)


def sources(mic: bool = True, system: bool = True) -> list:
    out = []
    if mic:
        import soundcard
        out.append(SoundcardSource("mic", soundcard.default_microphone))
    if system:
        out.append(SoundcardSource("system", _loopback))
    return out


def mic_permission() -> str:
    """Windows asks per app in Settings > Privacy > Microphone; a denied microphone simply records
    silence, so there is nothing to check before recording."""
    return "granted"


def self_check() -> list[str]:
    try:
        import soundcard  # noqa: F401
        return []
    except Exception as e:  # noqa: BLE001
        return [f"soundcard: {e}"]
