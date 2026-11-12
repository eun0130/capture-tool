"""Screen recording on Windows: H.264 video + AAC sound into an MP4 through Media Foundation's Sink
Writer - the encoder that comes with Windows (no GPL parts; a hardware encoder when there is one).
Frames are BGRA numpy arrays, sound 48 kHz stereo float32 blocks; times are seconds on the
recording's timeline. Create, use and close a writer on one thread (COM is initialised there).

Media Foundation is called through each object's function table. The method lists below are copied
from the Windows SDK headers (mfobjects.idl, mfreadwrite.idl - checked against Wine's copies); a
method's slot is its position after IUnknown's three, so the slots follow from the lists."""
from __future__ import annotations

import ctypes
import uuid
from pathlib import Path

import numpy as np

IUNKNOWN = ["QueryInterface", "AddRef", "Release"]
IMFATTRIBUTES = ["GetItem", "GetItemType", "CompareItem", "Compare", "GetUINT32", "GetUINT64", "GetDouble",
                 "GetGUID", "GetStringLength", "GetString", "GetAllocatedString", "GetBlobSize", "GetBlob",
                 "GetAllocatedBlob", "GetUnknown", "SetItem", "DeleteItem", "DeleteAllItems", "SetUINT32",
                 "SetUINT64", "SetDouble", "SetGUID", "SetString", "SetBlob", "SetUnknown", "LockStore",
                 "UnlockStore", "GetCount", "GetItemByIndex", "CopyAllItems"]
IMFMEDIATYPE = IMFATTRIBUTES + ["GetMajorType", "IsCompressedFormat", "IsEqual", "GetRepresentation",
                                "FreeRepresentation"]
IMFSAMPLE = IMFATTRIBUTES + ["GetSampleFlags", "SetSampleFlags", "GetSampleTime", "SetSampleTime",
                             "GetSampleDuration", "SetSampleDuration", "GetBufferCount", "GetBufferByIndex",
                             "ConvertToContiguousBuffer", "AddBuffer", "RemoveBufferByIndex", "RemoveAllBuffers",
                             "GetTotalLength", "CopyToBuffer"]
IMFMEDIABUFFER = ["Lock", "Unlock", "GetCurrentLength", "SetCurrentLength", "GetMaxLength"]
IMFSINKWRITER = ["AddStream", "SetInputMediaType", "BeginWriting", "WriteSample", "SendStreamTick", "PlaceMarker",
                 "NotifyEndOfSegment", "Flush", "Finalize", "GetServiceForStream", "GetStatistics"]


def slot(methods: list[str], name: str) -> int:
    return len(IUNKNOWN) + methods.index(name)


def _media_guid(code: int) -> uuid.UUID:
    """DEFINE_MEDIATYPE_GUID: the format code then the fixed tail 0000-0010-8000-00AA00389B71."""
    return uuid.UUID(f"{code:08x}-0000-0010-8000-00aa00389b71")


# mfapi.h (values checked against Wine's include/mfapi.h)
MF_VERSION = 0x00020070                 # Windows 7 and later: MF_SDK_VERSION 2, MF_API_VERSION 0x70
MFSTARTUP_FULL = 0
MF_MT_MAJOR_TYPE = uuid.UUID("48eba18e-f8c9-4687-bf11-0a74c9f96a8f")
MF_MT_SUBTYPE = uuid.UUID("f7e34c9a-42e8-4714-b74b-cb29d72c35e5")
MF_MT_AVG_BITRATE = uuid.UUID("20332624-fb0d-4d9e-bd0d-cbf6786c102e")
MF_MT_INTERLACE_MODE = uuid.UUID("e2724bb8-e676-4806-b4b2-a8d6efb44ccd")
MF_MT_FRAME_SIZE = uuid.UUID("1652c33d-d6b2-4012-b834-72030849a37d")
MF_MT_FRAME_RATE = uuid.UUID("c459a2e8-3d2c-4e44-b132-fee5156c7bb0")
MF_MT_PIXEL_ASPECT_RATIO = uuid.UUID("c6376a1e-8d0a-4027-be45-6d9a0ad39bb6")
MF_MT_DEFAULT_STRIDE = uuid.UUID("644b4e48-1e02-4516-b0eb-c01ca9d49ac6")
MF_MT_AUDIO_SAMPLES_PER_SECOND = uuid.UUID("5faeeae7-0290-4c31-9e8a-c534f68d9dba")
MF_MT_AUDIO_NUM_CHANNELS = uuid.UUID("37e48bf5-645e-4c5b-89de-ada9e29b696a")
MF_MT_AUDIO_BITS_PER_SAMPLE = uuid.UUID("f2deb57f-40fa-4764-aa33-ed4f2d1ff669")
MF_MT_AUDIO_AVG_BYTES_PER_SECOND = uuid.UUID("1aab75c8-cfef-451c-ab95-ac034b8e1731")
MF_MT_AUDIO_BLOCK_ALIGNMENT = uuid.UUID("322de230-9eeb-43bd-ab7a-ff412251541d")
MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS = uuid.UUID("a634a91c-822b-41b9-a494-4de4643612b0")
MFMediaType_Video = uuid.UUID("73646976-0000-0010-8000-00aa00389b71")
MFMediaType_Audio = uuid.UUID("73647561-0000-0010-8000-00aa00389b71")
MFVideoFormat_RGB32 = _media_guid(22)                                   # D3DFMT_X8R8G8B8 = BGRA bytes
MFVideoFormat_H264 = _media_guid(int.from_bytes(b"H264", "little"))     # MAKEFOURCC('H','2','6','4')
MFAudioFormat_PCM = _media_guid(0x0001)                                 # WAVE_FORMAT_PCM
MFAudioFormat_AAC = _media_guid(0x1610)                                 # WAVE_FORMAT_MPEG_HEAAC
MFVideoInterlace_Progressive = 2
AAC_BYTES_PER_SECOND = 16000                                            # 128 kbit/s (one of 12/16/20/24 k)


def bitrate(width: int, height: int, fps: int) -> int:
    """About 0.1 bits per pixel per frame: crisp text, small files (1080p 15 fps ~ 3 Mbit/s)."""
    return int(min(20_000_000, max(500_000, width * height * fps * 0.1)))


def pack(hi: int, lo: int) -> int:
    """Two UINT32 in one UINT64 (frame size: width, height; rates: numerator, denominator)."""
    return (int(hi) << 32) | int(lo)


def _even(n: int) -> int:
    return max(2, n - n % 2)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, u: uuid.UUID) -> "_GUID":
        b = u.bytes_le
        g = cls()
        ctypes.memmove(ctypes.byref(g), b, 16)
        return g


class _Com:
    """A COM object pointer with calls by function-table slot."""

    def __init__(self, ptr: ctypes.c_void_p, methods: list[str]):
        self.ptr, self.methods = ptr, methods

    def call(self, name: str, *args, argtypes=()):
        vtbl = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[slot(self.methods, name)])
        hr = fn(self.ptr, *args)
        if hr < 0:
            raise OSError(f"Media Foundation {name} failed: 0x{hr & 0xFFFFFFFF:08X}")
        return hr

    def release(self) -> None:
        if self.ptr:
            vtbl = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)(vtbl[2])(self.ptr)
            self.ptr = None

    # IMFAttributes setters (media types, samples and attribute stores share them)
    def set_u32(self, key: uuid.UUID, v: int) -> None:
        self.call("SetUINT32", ctypes.byref(_GUID.of(key)), ctypes.c_uint32(v),
                  argtypes=(ctypes.c_void_p, ctypes.c_uint32))

    def set_u64(self, key: uuid.UUID, v: int) -> None:
        self.call("SetUINT64", ctypes.byref(_GUID.of(key)), ctypes.c_uint64(v),
                  argtypes=(ctypes.c_void_p, ctypes.c_uint64))

    def set_guid(self, key: uuid.UUID, v: uuid.UUID) -> None:
        self.call("SetGUID", ctypes.byref(_GUID.of(key)), ctypes.byref(_GUID.of(v)),
                  argtypes=(ctypes.c_void_p, ctypes.c_void_p))


_started = False


def _mf():
    global _started
    mfplat = ctypes.WinDLL("mfplat")
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx(None, 0)                       # COINIT_MULTITHREADED on this thread (or already set)
    if not _started:
        hr = mfplat.MFStartup(ctypes.c_uint32(MF_VERSION), ctypes.c_uint32(MFSTARTUP_FULL))
        if hr < 0:
            raise OSError(f"Media Foundation is not available (0x{hr & 0xFFFFFFFF:08X}) - "
                          "Windows N/KN needs the Media Feature Pack")
        _started = True
    return mfplat, ctypes.WinDLL("mfreadwrite")


def _new(fn, methods: list[str], *args) -> _Com:
    p = ctypes.c_void_p()
    hr = fn(*args, ctypes.byref(p))
    if hr < 0 or not p:
        raise OSError(f"Media Foundation {getattr(fn, '__name__', 'create')} failed: 0x{hr & 0xFFFFFFFF:08X}")
    return _Com(p, methods)


class MFWriter:
    def __init__(self, path, width: int, height: int, fps: int, audio: dict | None):
        self.mfplat, mfrw = _mf()
        self.path = Path(path)
        self.path.unlink(missing_ok=True)
        self.w, self.h, self.fps = _even(width), _even(height), int(fps)
        attrs = self._attributes()
        try:
            self.writer = _new(mfrw.MFCreateSinkWriterFromURL, IMFSINKWRITER, ctypes.c_wchar_p(str(self.path)),
                               None, attrs.ptr)
        finally:
            attrs.release()
        self.video = self._add_video()
        self.audio = self._add_audio(audio) if audio else None
        self.writer.call("BeginWriting")

    def _attributes(self) -> _Com:
        p = ctypes.c_void_p()
        hr = self.mfplat.MFCreateAttributes(ctypes.byref(p), ctypes.c_uint32(1))
        if hr < 0:
            raise OSError(f"MFCreateAttributes failed: 0x{hr & 0xFFFFFFFF:08X}")
        a = _Com(p, IMFATTRIBUTES)
        a.set_u32(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1)
        return a

    def _type(self) -> _Com:
        return _new(self.mfplat.MFCreateMediaType, IMFMEDIATYPE)

    def _stream(self, out: _Com, inp: _Com) -> int:
        index = ctypes.c_uint32()
        try:
            self.writer.call("AddStream", out.ptr, ctypes.byref(index), argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            self.writer.call("SetInputMediaType", ctypes.c_uint32(index.value), inp.ptr, None,
                             argtypes=(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p))
        finally:
            out.release()
            inp.release()
        return index.value

    def _add_video(self) -> int:
        out, inp = self._type(), self._type()
        for t, sub in ((out, MFVideoFormat_H264), (inp, MFVideoFormat_RGB32)):
            t.set_guid(MF_MT_MAJOR_TYPE, MFMediaType_Video)
            t.set_guid(MF_MT_SUBTYPE, sub)
            t.set_u32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive)
            t.set_u64(MF_MT_FRAME_SIZE, pack(self.w, self.h))
            t.set_u64(MF_MT_FRAME_RATE, pack(self.fps, 1))
            t.set_u64(MF_MT_PIXEL_ASPECT_RATIO, pack(1, 1))
        out.set_u32(MF_MT_AVG_BITRATE, bitrate(self.w, self.h, self.fps))
        inp.set_u32(MF_MT_DEFAULT_STRIDE, self.w * 4)          # positive: rows top to bottom, like numpy
        return self._stream(out, inp)

    def _add_audio(self, audio: dict) -> int:
        self.rate, self.channels = int(audio["rate"]), int(audio["channels"])
        out, inp = self._type(), self._type()
        for t, sub in ((out, MFAudioFormat_AAC), (inp, MFAudioFormat_PCM)):
            t.set_guid(MF_MT_MAJOR_TYPE, MFMediaType_Audio)
            t.set_guid(MF_MT_SUBTYPE, sub)
            t.set_u32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16)
            t.set_u32(MF_MT_AUDIO_SAMPLES_PER_SECOND, self.rate)
            t.set_u32(MF_MT_AUDIO_NUM_CHANNELS, self.channels)
        out.set_u32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, AAC_BYTES_PER_SECOND)
        inp.set_u32(MF_MT_AUDIO_BLOCK_ALIGNMENT, 2 * self.channels)
        inp.set_u32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 2 * self.channels * self.rate)
        return self._stream(out, inp)

    def _write(self, stream: int, data: bytes, t: float, duration: float) -> None:
        buf = _new(self.mfplat.MFCreateMemoryBuffer, IMFMEDIABUFFER, ctypes.c_uint32(len(data)))
        sample = None
        try:
            ptr = ctypes.c_void_p()
            buf.call("Lock", ctypes.byref(ptr), None, None, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
            try:
                ctypes.memmove(ptr, data, len(data))
            finally:
                buf.call("Unlock")
            buf.call("SetCurrentLength", ctypes.c_uint32(len(data)), argtypes=(ctypes.c_uint32,))
            sample = _new(self.mfplat.MFCreateSample, IMFSAMPLE)
            sample.call("AddBuffer", buf.ptr, argtypes=(ctypes.c_void_p,))
            sample.call("SetSampleTime", ctypes.c_longlong(int(round(t * 1e7))), argtypes=(ctypes.c_longlong,))
            sample.call("SetSampleDuration", ctypes.c_longlong(int(round(duration * 1e7))), argtypes=(ctypes.c_longlong,))
            self.writer.call("WriteSample", ctypes.c_uint32(stream), sample.ptr, argtypes=(ctypes.c_uint32, ctypes.c_void_p))
        finally:
            buf.release()
            if sample is not None:
                sample.release()

    def add_frame(self, bgra: np.ndarray, t: float) -> bool:
        frame = np.ascontiguousarray(bgra[:self.h, :self.w, :4])
        if frame.shape[:2] != (self.h, self.w):
            frame = np.ascontiguousarray(np.pad(frame, ((0, self.h - frame.shape[0]), (0, self.w - frame.shape[1]), (0, 0))))
        self._write(self.video, frame.tobytes(), t, 1.0 / self.fps)
        return True

    def add_audio(self, pcm: np.ndarray, t: float) -> bool:
        if self.audio is None or len(pcm) == 0:
            return True
        data = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        self._write(self.audio, data, t, len(pcm) / self.rate)
        return True

    def close(self) -> None:
        try:
            self.writer.call("Finalize")
        finally:
            self.writer.release()


def open_writer(path, width: int, height: int, fps: int, audio: dict | None = None, realtime: bool = True) -> MFWriter:
    """`realtime` matches the Mac writer; the Sink Writer always waits for its encoder (never drops)."""
    return MFWriter(path, width, height, fps, audio)
