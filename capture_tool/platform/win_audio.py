"""Sound for screen recording on Windows through `soundcard` (WASAPI): the microphone, and the
computer's sound as the default speakers' loopback. Both hand over 48 kHz stereo float32 blocks."""
from __future__ import annotations

from .sound_common import SoundcardSource, import_soundcard


def _mic():
    return import_soundcard().default_microphone()


def _loopback():
    sc = import_soundcard()
    return sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)


def sources(mic: bool = True, system: bool = True) -> list:
    out = []
    import_soundcard()                                   # a missing library fails here, on the GUI side
    if mic:
        out.append(SoundcardSource("mic", _mic))
    if system:
        out.append(SoundcardSource("system", _loopback))
    return out


def mic_permission() -> str:
    """Windows asks per app in Settings > Privacy > Microphone; a denied microphone simply records
    silence, so there is nothing to check before recording."""
    return "granted"


def self_check() -> list[str]:
    try:
        import_soundcard()
        return []
    except Exception as e:  # noqa: BLE001
        return [f"soundcard: {e}"]
