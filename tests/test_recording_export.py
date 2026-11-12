"""After a recording: cut off the start / end (a new MP4 through the same OS writer) and GIF."""
import numpy as np
from PIL import Image

from capture_tool.core.recording import RATE
from capture_tool.core.recording_export import gif_size_estimate, write_gif, write_trimmed


class FakeWriter:
    def __init__(self):
        self.frames, self.audio, self.closed = [], [], 0

    def add_frame(self, bgra, t):
        assert bgra.shape[2] == 4
        self.frames.append(t)
        return True

    def add_audio(self, pcm, t):
        self.audio.append((t, len(pcm)))
        return True

    def close(self):
        self.closed += 1


def frames(seconds=2.0, fps=10, w=80, h=60):
    for i in range(int(seconds * fps)):
        img = np.zeros((h, w, 3), np.uint8)
        img[:, : (i * 4) % w] = (0, 0, 255)
        yield i / fps, img


def test_EXP_01_trimming_keeps_the_middle_and_restarts_its_clock():
    w = FakeWriter()
    pcm = np.zeros((2 * RATE, 2), np.float32)
    write_trimmed(frames(), pcm, 0.5, 1.5, w)
    assert len(w.frames) == 10 and w.frames[0] == 0.0 and abs(w.frames[-1] - 0.9) < 1e-9
    assert sum(n for _, n in w.audio) == RATE and w.audio[0][0] == 0.0 and w.closed == 1


def test_EXP_02_no_sound_means_no_audio_written():
    w = FakeWriter()
    write_trimmed(frames(), None, 0.0, 1.0, w)
    assert len(w.frames) == 10 and w.audio == [] and w.closed == 1


def test_EXP_03_a_gif_of_the_kept_part_smaller_and_slower(tmp_path):
    out = tmp_path / "rec.gif"
    write_gif(frames(seconds=2.0, fps=10, w=1600, h=900), out, start=0.0, end=2.0, fps=5, max_width=800)
    im = Image.open(out)
    assert im.size == (800, 450) and im.n_frames == 10 and im.info.get("loop") == 0
    assert 150 <= im.info["duration"] <= 250                                  # ~200 ms per frame at 5 fps


def test_EXP_04_a_gif_estimate_grows_with_size_and_length():
    small = gif_size_estimate(400, 300, seconds=5, fps=10)
    assert gif_size_estimate(800, 600, seconds=5, fps=10) > small and gif_size_estimate(400, 300, 10, 10) > small


def _mp4(path, seconds=2.0, fps=10, w=80, h=60):
    import cv2
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for _, img in frames(seconds, fps, w, h):
        vw.write(img)
    vw.release()
    return path


def test_EXP_05_keeping_the_whole_recording_copies_the_file_as_it_is(tmp_path):
    from capture_tool.core.recording_export import export
    src = _mp4(tmp_path / "rec.mp4")
    opened = []
    out = export(src, None, 0.0, 2.0, "mp4", tmp_path / "out.mp4", lambda **kw: opened.append(kw))
    assert out.read_bytes() == src.read_bytes() and opened == []          # no second encode


def test_EXP_06_a_trimmed_mp4_goes_through_the_os_writer_without_real_time(tmp_path):
    import wave
    from capture_tool.core.recording_export import export
    src = _mp4(tmp_path / "rec.mp4")
    wav = tmp_path / "rec.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(np.zeros((2 * RATE, 2), "<i2").tobytes())
    box = {}

    def open_writer(**kw):
        box["kw"], box["w"] = kw, FakeWriter()
        return box["w"]
    export(src, wav, 0.5, 1.5, "mp4", tmp_path / "out.mp4", open_writer)
    kw = box["kw"]
    assert kw["realtime"] is False and kw["width"] == 80 and kw["height"] == 60 and kw["fps"] == 10
    assert kw["audio"] == {"rate": RATE, "channels": 2} and str(kw["path"]).endswith("out.mp4")
    assert 9 <= len(box["w"].frames) <= 11 and box["w"].closed == 1


def test_EXP_07_a_gif_export(tmp_path):
    from capture_tool.core.recording_export import export
    src = _mp4(tmp_path / "rec.mp4", w=160, h=120)
    out = export(src, None, 0.0, 1.0, "gif", tmp_path / "out.gif", None, gif_fps=5, max_width=80)
    im = Image.open(out)
    assert im.size == (80, 60) and im.info.get("loop") == 0
