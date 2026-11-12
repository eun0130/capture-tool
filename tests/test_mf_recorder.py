"""Windows screen recording writer (Media Foundation Sink Writer), the parts that run anywhere:
function-table slots from the SDK method lists, media type GUIDs, packed sizes. The real writer is
tested on Windows (test_platform_win.py PWIN-33)."""
import uuid

from capture_tool.platform import mf_recorder as mf


def test_MF_01_function_table_slots_follow_the_sdk_method_order():
    # IUnknown takes slots 0-2; then the interface's own methods in header order (Wine/SDK idl)
    assert mf.slot(mf.IMFATTRIBUTES, "SetUINT32") == 21 and mf.slot(mf.IMFATTRIBUTES, "SetUINT64") == 22
    assert mf.slot(mf.IMFATTRIBUTES, "SetGUID") == 24
    assert mf.slot(mf.IMFMEDIATYPE, "SetGUID") == 24                     # a media type is attributes first
    assert mf.slot(mf.IMFSAMPLE, "SetSampleTime") == 36 and mf.slot(mf.IMFSAMPLE, "AddBuffer") == 42
    assert mf.slot(mf.IMFMEDIABUFFER, "Lock") == 3 and mf.slot(mf.IMFMEDIABUFFER, "SetCurrentLength") == 6
    assert [mf.slot(mf.IMFSINKWRITER, n) for n in ("AddStream", "SetInputMediaType", "BeginWriting",
                                                   "WriteSample", "Finalize")] == [3, 4, 5, 6, 11]
    assert len(mf.IMFATTRIBUTES) == 30 and len(mf.IMFSAMPLE) == 44 and len(mf.IMFSINKWRITER) == 11


def test_MF_02_media_type_guids_are_the_published_ones():
    tail = "-0000-0010-8000-00aa00389b71"
    assert mf.MFVideoFormat_H264 == uuid.UUID("34363248" + tail)             # 'H264'
    assert mf.MFVideoFormat_RGB32 == uuid.UUID("00000016" + tail)            # D3DFMT_X8R8G8B8
    assert mf.MFAudioFormat_AAC == uuid.UUID("00001610" + tail)
    assert mf.MFAudioFormat_PCM == uuid.UUID("00000001" + tail)
    assert mf.MFMediaType_Video == uuid.UUID("73646976" + tail) and mf.MFMediaType_Audio == uuid.UUID("73647561" + tail)
    assert mf.MF_VERSION == 0x00020070


def test_MF_03_sizes_and_rates_are_packed_high_low_and_guids_go_in_as_bytes_le():
    assert mf.pack(1920, 1080) == (1920 << 32) | 1080 and mf.pack(15, 1) == (15 << 32) | 1
    g = mf._GUID.of(mf.MF_MT_SUBTYPE)
    assert (g.Data1, g.Data2, g.Data3, bytes(g.Data4)) == (0xF7E34C9A, 0x42E8, 0x4714, bytes.fromhex("b74bcb29d72c35e5"))
    assert mf._even(321) == 320 and mf._even(240) == 240
