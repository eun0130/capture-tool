"""A sound source for screen recording that both backends use: a `soundcard` device (microphone, or
on Windows the speakers' loopback = the computer's sound) read in short blocks on its own thread.
Blocks go to `on_block(float32 [n, 2], 48000)`. A device that fails is reported in `error`, never
raised into the recording; stopping waits at most a second (the loopback delivers nothing while the
computer is silent, so a read may hang until sound plays)."""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

import numpy as np

RATE = 48000
BLOCK = 4800                      # 0.1 s per read

log = logging.getLogger("capture_tool")


class SoundcardSource:
    def __init__(self, name: str, device: Callable):
        self.name, self._device = name, device
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, on_block: Callable[[np.ndarray, int], None]) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(on_block,), daemon=True, name=f"sound-{self.name}")
        self._thread.start()

    def _run(self, on_block) -> None:
        if sys.platform == "win32":                       # the WASAPI calls need COM on this thread
            import ctypes
            ctypes.WinDLL("ole32").CoInitializeEx(None, 0)
        try:
            dev = self._device()
            with dev.recorder(samplerate=RATE, channels=2) as rec:      # the device's own block size
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    if self._stop.is_set():
                        break
                    if len(data):
                        on_block(np.asarray(data, np.float32), RATE)
        except Exception as e:  # noqa: BLE001 - the recording goes on without this sound
            self.error = str(e) or type(e).__name__
            log.warning("sound source %s failed: %s", self.name, self.error)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
