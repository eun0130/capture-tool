"""Sound for screen recording on the Mac: the microphone through `soundcard` (CoreAudio; macOS asks
for the Microphone permission), the computer's sound through ScreenCaptureKit (macOS 13+; uses the
Screen Recording permission the app already has). Both hand over 48 kHz stereo float32 blocks.

ScreenCaptureKit turns a Python error inside its callbacks into a crash of the whole app, so every
callback here catches everything and keeps it in `error`."""
from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from ..sound_common import RATE, SoundcardSource

log = logging.getLogger("capture_tool")
_AUTHORIZED = 3                       # AVAuthorizationStatusAuthorized


def interleave(data: bytes, frames: int, channels: int, non_interleaved: bool) -> np.ndarray:
    """float32 bytes of one sample buffer as [frames, 2] (planar = every channel's block in turn)."""
    a = np.frombuffer(data, np.float32)
    if non_interleaved:
        a = a[:frames * channels].reshape(channels, frames).T
    else:
        a = a[:frames * channels].reshape(frames, channels)
    if channels == 1:
        a = np.repeat(a, 2, axis=1)
    return np.ascontiguousarray(a[:, :2], np.float32)


class ScreenAudioSource:
    """The computer's sound (everything it plays, except this app) through ScreenCaptureKit."""

    def __init__(self, name: str = "system"):
        self.name, self.error = name, None
        self._stream = self._out = None

    def start(self, on_block: Callable[[np.ndarray, int], None]) -> None:
        try:
            self._start(on_block)
        except Exception as e:  # noqa: BLE001 - the recording goes on without this sound
            self.error = str(e) or type(e).__name__
            log.warning("computer sound not recorded: %s", self.error)

    def _start(self, on_block) -> None:
        import objc
        import CoreMedia
        import ScreenCaptureKit as sck
        from Foundation import NSObject
        src = self

        class Out(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
            def stream_didOutputSampleBuffer_ofType_(self, stream, sbuf, kind):
                try:
                    if kind != sck.SCStreamOutputTypeAudio:
                        return
                    frames = CoreMedia.CMSampleBufferGetNumSamples(sbuf)
                    asbd = CoreMedia.CMAudioFormatDescriptionGetStreamBasicDescription(
                        CoreMedia.CMSampleBufferGetFormatDescription(sbuf))
                    rate, flags, channels = asbd[0], asbd[2], asbd[6]
                    block = CoreMedia.CMSampleBufferGetDataBuffer(sbuf)
                    _, data = CoreMedia.CMBlockBufferCopyDataBytes(
                        block, 0, CoreMedia.CMBlockBufferGetDataLength(block), None)
                    on_block(interleave(bytes(data), frames, channels, bool(flags & 32)), int(rate))
                except Exception as e:  # noqa: BLE001 - never raise into ScreenCaptureKit
                    src.error = str(e) or type(e).__name__

        done, box = threading.Event(), {}

        def have(content, err):
            box["content"], box["err"] = content, err
            done.set()
        sck.SCShareableContent.getShareableContentWithCompletionHandler_(have)
        if not done.wait(5) or box.get("content") is None:
            raise OSError(f"no screen to take the sound from ({box.get('err')})")
        display = box["content"].displays()[0]
        flt = sck.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
        cfg = sck.SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setExcludesCurrentProcessAudio_(True)
        cfg.setSampleRate_(RATE)
        cfg.setChannelCount_(2)
        cfg.setWidth_(2)                                    # the picture is not used: as small as possible
        cfg.setHeight_(2)
        cfg.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, 1))
        self._stream = sck.SCStream.alloc().initWithFilter_configuration_delegate_(flt, cfg, None)
        self._out = Out.alloc().init()
        ok, err = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._out, sck.SCStreamOutputTypeAudio, None, None)
        if not ok:
            raise OSError(f"sound output: {err}")
        started, res = threading.Event(), {}

        def on_start(err):
            res["err"] = err
            started.set()
        self._stream.startCaptureWithCompletionHandler_(on_start)
        if not started.wait(5) or res.get("err") is not None:
            raise OSError(f"the computer's sound could not be started ({res.get('err')})")

    def stop(self) -> None:
        if self._stream is None:
            return
        stopped = threading.Event()

        def on_stop(err):
            stopped.set()
        try:
            self._stream.stopCaptureWithCompletionHandler_(on_stop)
            stopped.wait(2)
        except Exception:  # noqa: BLE001
            pass
        self._stream = self._out = None


def sources(mic: bool = True, system: bool = True) -> list:
    out = []
    if mic:
        import soundcard
        out.append(SoundcardSource("mic", soundcard.default_microphone))
    if system:
        out.append(ScreenAudioSource("system"))
    return out


def mic_permission() -> str:
    """'granted', 'denied' or 'ask' (macOS has not asked yet)."""
    import AVFoundation
    status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeAudio)
    return "granted" if status == _AUTHORIZED else ("ask" if status == 0 else "denied")


def self_check() -> list[str]:
    problems = []
    for name in ("soundcard", "ScreenCaptureKit"):
        try:
            __import__(name)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name}: {e}")
    return problems
