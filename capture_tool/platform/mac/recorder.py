"""Screen recording on the Mac: H.264 video + AAC sound into an MP4 through AVAssetWriter - the
encoder that comes with macOS (no GPL parts, hardware accelerated). Frames are BGRA numpy arrays,
sound 48 kHz stereo float32 blocks; times are seconds on the recording's timeline."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

TIMESCALE = 600           # CMTime units per second (divides 15, 24, 25, 30, 60 fps)


def _even(n: int) -> int:
    return max(2, n - n % 2)              # H.264 wants even sizes


def bitrate(width: int, height: int, fps: int) -> int:
    """About 0.1 bits per pixel per frame: crisp text, small files (1080p 15 fps ~ 3 Mbit/s)."""
    return int(min(20_000_000, max(500_000, width * height * fps * 0.1)))


class AVWriter:
    def __init__(self, path, width: int, height: int, fps: int, audio: dict | None, realtime: bool = True):
        import AVFoundation as av
        import Quartz
        from Foundation import NSURL
        self.path = Path(path)
        self.path.unlink(missing_ok=True)                 # the writer refuses an existing file
        self.w, self.h = _even(width), _even(height)
        writer, err = av.AVAssetWriter.assetWriterWithURL_fileType_error_(
            NSURL.fileURLWithPath_(str(self.path)), av.AVFileTypeMPEG4, None)
        if writer is None:
            raise OSError(f"AVAssetWriter: {err}")
        self.writer = writer
        video = {av.AVVideoCodecKey: av.AVVideoCodecTypeH264, av.AVVideoWidthKey: self.w,
                 av.AVVideoHeightKey: self.h,
                 av.AVVideoCompressionPropertiesKey: {av.AVVideoAverageBitRateKey: bitrate(self.w, self.h, fps),
                                                      av.AVVideoExpectedSourceFrameRateKey: fps}}
        self.vin = av.AVAssetWriterInput.assetWriterInputWithMediaType_outputSettings_(av.AVMediaTypeVideo, video)
        self.realtime = realtime                          # recording: drop a late frame; export: wait for it
        self.vin.setExpectsMediaDataInRealTime_(realtime)
        attrs = {Quartz.kCVPixelBufferPixelFormatTypeKey: Quartz.kCVPixelFormatType_32BGRA,
                 Quartz.kCVPixelBufferWidthKey: self.w, Quartz.kCVPixelBufferHeightKey: self.h}
        self.adaptor = av.AVAssetWriterInputPixelBufferAdaptor.assetWriterInputPixelBufferAdaptorWithAssetWriterInput_sourcePixelBufferAttributes_(  # noqa: E501
            self.vin, attrs)
        writer.addInput_(self.vin)
        self.ain = None
        self._audio_ended = False
        if audio:
            import CoreAudio
            self.rate, self.channels = int(audio["rate"]), int(audio["channels"])
            sound = {av.AVFormatIDKey: CoreAudio.kAudioFormatMPEG4AAC, av.AVSampleRateKey: self.rate,
                     av.AVNumberOfChannelsKey: self.channels, av.AVEncoderBitRateKey: 128_000}
            self.ain = av.AVAssetWriterInput.assetWriterInputWithMediaType_outputSettings_(av.AVMediaTypeAudio, sound)
            self.ain.setExpectsMediaDataInRealTime_(realtime)
            writer.addInput_(self.ain)
            self._fmt = self._audio_format()
        if not writer.startWriting():
            raise OSError(f"AVAssetWriter could not start: {writer.error()}")
        import CoreMedia
        writer.startSessionAtSourceTime_(CoreMedia.CMTimeMake(0, TIMESCALE))

    # --- picture ----------------------------------------------------------------------------------
    def add_frame(self, bgra: np.ndarray, t: float) -> bool:
        """False when the encoder is still busy with earlier frames (this one is dropped)."""
        import CoreMedia
        import Quartz
        if not self.vin.isReadyForMoreMediaData():
            if self.realtime:
                return False
            for _ in range(500):                          # exporting: wait (<= 5 s), never drop
                time.sleep(0.01)
                if self.vin.isReadyForMoreMediaData():
                    break
            else:
                raise OSError("the video encoder stopped taking frames")
        err, pb = Quartz.CVPixelBufferPoolCreatePixelBuffer(None, self.adaptor.pixelBufferPool(), None)
        if err != 0 or pb is None:
            raise OSError(f"no pixel buffer ({err})")
        Quartz.CVPixelBufferLockBaseAddress(pb, 0)
        try:
            stride = Quartz.CVPixelBufferGetBytesPerRow(pb)
            base = Quartz.CVPixelBufferGetBaseAddress(pb)
            dst = np.frombuffer(base.as_buffer(stride * self.h), np.uint8).reshape(self.h, stride)
            src = np.ascontiguousarray(bgra[:self.h, :self.w, :4])
            dst[:src.shape[0], :src.shape[1] * 4] = src.reshape(src.shape[0], -1)
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)
        ok = self.adaptor.appendPixelBuffer_withPresentationTime_(pb, CoreMedia.CMTimeMakeWithSeconds(t, TIMESCALE))
        if not ok:
            raise OSError(f"could not add a frame: {self.writer.error()}")
        return True

    # --- sound ------------------------------------------------------------------------------------
    def _audio_format(self):
        import CoreAudio
        import CoreMedia
        asbd = CoreAudio.AudioStreamBasicDescription()
        asbd.mSampleRate = float(self.rate)
        asbd.mFormatID = CoreAudio.kAudioFormatLinearPCM
        asbd.mFormatFlags = CoreAudio.kAudioFormatFlagIsFloat | CoreAudio.kAudioFormatFlagIsPacked
        asbd.mBytesPerPacket = asbd.mBytesPerFrame = 4 * self.channels
        asbd.mFramesPerPacket = 1
        asbd.mChannelsPerFrame = self.channels
        asbd.mBitsPerChannel = 32
        err, fmt = CoreMedia.CMAudioFormatDescriptionCreate(None, asbd, 0, None, 0, None, None, None)
        if err != 0:
            raise OSError(f"audio format ({err})")
        return fmt

    def add_audio(self, pcm: np.ndarray, t: float) -> bool:
        import CoreMedia
        if self.ain is None or len(pcm) == 0:
            return True
        for _ in range(100):                          # sound is never dropped: wait for the encoder (<= 1 s)
            if self.ain.isReadyForMoreMediaData():
                break
            time.sleep(0.01)
        else:
            raise OSError("the sound encoder stopped taking data")
        data = np.ascontiguousarray(pcm, np.float32).tobytes()
        err, block = CoreMedia.CMBlockBufferCreateWithMemoryBlock(
            None, None, len(data), None, None, 0, len(data), CoreMedia.kCMBlockBufferAssureMemoryNowFlag, None)
        if err != 0:
            raise OSError(f"audio buffer ({err})")
        CoreMedia.CMBlockBufferReplaceDataBytes(data, block, 0, len(data))
        pts = CoreMedia.CMTimeMake(int(round(t * self.rate)), self.rate)
        err, sample = CoreMedia.CMAudioSampleBufferCreateReadyWithPacketDescriptions(
            None, block, self._fmt, len(pcm), pts, None, None)
        if err != 0:
            raise OSError(f"audio sample ({err})")
        if not self.ain.appendSampleBuffer_(sample):
            raise OSError(f"could not add sound: {self.writer.error()}")
        return True

    # --- end --------------------------------------------------------------------------------------
    def end_audio(self) -> None:
        """No more sound will come (export): the encoder stops holding pictures back for it."""
        if self.ain is not None and not self._audio_ended:
            self.ain.markAsFinished()
            self._audio_ended = True

    def close(self, timeout: float = 30.0) -> None:
        self.vin.markAsFinished()
        self.end_audio()
        done = threading.Event()
        self.writer.finishWritingWithCompletionHandler_(lambda: done.set())
        if not done.wait(timeout):
            raise OSError("the video file was not finished in time")
        if self.writer.status() != 2:                     # AVAssetWriterStatusCompleted
            raise OSError(f"the video file was not finished: {self.writer.error()}")


def open_writer(path, width: int, height: int, fps: int, audio: dict | None = None, realtime: bool = True) -> AVWriter:
    return AVWriter(path, width, height, fps, audio, realtime)


def self_check() -> list[str]:
    problems = []
    for name in ("AVFoundation", "CoreMedia", "CoreAudio", "Quartz"):
        try:
            __import__(name)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name}: {e}")
    return problems
