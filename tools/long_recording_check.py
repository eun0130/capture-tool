"""A 2-hour screen recording, run about 9x faster than real time, through the app's own recorder
(`recording_ui.Recorder` -> `RecordingSession` -> the Mac's AVAssetWriter, real time mode), then checked
end to end. Only the screen and the sound devices are simulated:

- screen: PDF slides at 1920x1080 changing every ~113 s, a moving pointer with clicks, and a white box in
  the bottom-right corner (magenta) for 0.2 s at every full minute (a sync mark);
- microphone: a 1 kHz beep at every full minute (same moment as the box), its clock 60 ppm fast;
- computer sound: a steady 220 Hz tone, its clock 60 ppm slow; blocks arrive 0-150 ms late;
- a 5-minute break (paused, the slide stays) at 1:00:30 and the microphone muted 1:20-1:25.

Checks: frames and length, slides in order, beeps on the video's marks (from the WAV and the MP4's own
AAC track), no beep while muted, the tone without gaps, memory, then the result window on the long file,
a 60 s part from 1:30:00 with sound, a 10 s GIF, and one frame per slide saved for the 도형PPT check.

    python tools/long_recording_check.py PDF [PDF ...] [--minutes 130] [--speed 9] [--out DIR]
Writes DIR/report.json and DIR/frames/slide_NN.png (default DIR: $TMPDIR/rec-long)."""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

W, H = 1920, 1080
BREAK_AT, BREAK_LEN = 3630.0, 300.0           # active s, wall s
MUTE = (4800.0, 5100.0)                       # active s: mic muted
MARK_EVERY, MARK_LEN = 60.0, 0.2
BEEP_HZ, TONE_HZ = 1000.0, 220.0
RATE = 48000


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024      # bytes on macOS


def render_pages(pdfs: list[str]) -> list[np.ndarray]:
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtGui import QImage
    out = []
    for p in pdfs:
        d = QPdfDocument()
        d.load(p)
        for i in range(d.pageCount()):
            img = d.render(i, QSize(W, H)).convertToFormat(QImage.Format_RGB32)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine() // 4, 4)[:, :W].copy()
            a[..., 3] = 255
            out.append(a)                     # BGRA
    return out


class World:
    """The simulated screen and devices on one clock. `wall` runs on (breaks too); `active` is the
    time the recording sees (wall minus breaks)."""

    def __init__(self, pages, active_len: float, speed: float):
        self.pages, self.active_len, self.speed = pages, active_len, speed
        self.per_page = active_len / len(pages)
        self.wall = 0.0
        self.real0 = time.monotonic()
        self.buf = np.empty((H, W, 4), np.uint8)
        self.lock = threading.Lock()
        self.on_wall = []                        # callbacks(wall) run from sleep()

    def active(self, wall: float | None = None) -> float:
        w = self.wall if wall is None else wall
        if w < BREAK_AT:
            return w
        return max(BREAK_AT, w - BREAK_LEN)

    def paused(self, wall: float | None = None) -> bool:
        w = self.wall if wall is None else wall
        return BREAK_AT <= w < BREAK_AT + BREAK_LEN

    def page_at(self, active: float) -> int:
        return min(len(self.pages) - 1, int(active // self.per_page))

    # --- clock for the recorder (the recording thread) ------------------------------------------
    def clock(self) -> float:
        return self.wall

    def sleep(self, s: float) -> None:
        self.wall += s
        for cb in self.on_wall:
            cb(self.wall)
        ahead = self.wall / self.speed - (time.monotonic() - self.real0)
        if ahead > 0:
            time.sleep(ahead)

    # --- screen ------------------------------------------------------------------------------------
    def grab(self, rect):
        a = self.active()
        np.copyto(self.buf, self.pages[self.page_at(a)])
        if a % MARK_EVERY < MARK_LEN and a >= MARK_EVERY - 1e-9:
            self.buf[H - 180:H - 20, W - 180:W - 20, :3] = (255, 0, 255)       # magenta: no slide has it
        return self.buf

    def mouse(self):
        a = self.active()
        x = int(W / 2 + 500 * np.cos(a / 7.0))
        y = int(H / 2 + 300 * np.sin(a / 5.0))
        return x, y, (a % 30.0) < 0.1


class FakeSource:
    """A sound device: 0.1 s blocks of `signal(active)` at its own (drifting) rate, delivered late."""

    def __init__(self, name: str, world: World, signal, ppm: float, seed: int):
        self.name, self.world, self.signal, self.ppm = name, world, signal, ppm
        self.error = None
        self.rng = np.random.default_rng(seed)
        self.made = 0                      # samples made (device clock)
        self.pending: list[tuple[float, np.ndarray]] = []
        self.cb = None

    def start(self, cb) -> None:
        self.cb = cb
        self.world.on_wall.append(self.tick)

    def stop(self) -> None:
        if self.tick in self.world.on_wall:
            self.world.on_wall.remove(self.tick)

    def tick(self, wall: float) -> None:
        rate = RATE * (1 + self.ppm * 1e-6)                # samples per wall second
        while (self.made + 4800) / rate <= wall:
            t0 = self.made / rate                            # wall time of the block's first sample
            n = 4800
            walls = t0 + np.arange(n) / rate
            block = self.signal(walls)
            due = t0 + n / rate + float(self.rng.uniform(0.0, 0.15))
            if self.pending:
                due = max(due, self.pending[-1][0])             # a device delivers in order
            self.pending.append((due, block))
            self.made += n
        keep = []
        for due, block in self.pending:
            if due <= wall:
                self.cb(block, RATE)
            else:
                keep.append((due, block))
        self.pending = keep


def make_signals(world: World):
    def active_of(walls):
        return np.where(walls < BREAK_AT, walls, np.maximum(BREAK_AT, walls - BREAK_LEN))

    def mic(walls):
        a = active_of(walls)
        phase = a % MARK_EVERY
        on = (phase < 0.05) & (a >= MARK_EVERY - 1e-9) & ~((walls >= BREAK_AT) & (walls < BREAK_AT + BREAK_LEN))
        s = (0.5 * np.sin(2 * np.pi * BEEP_HZ * walls) * on).astype(np.float32)
        return np.stack([s, s], axis=1)

    def system(walls):
        s = (0.1 * np.sin(2 * np.pi * TONE_HZ * walls)).astype(np.float32)
        return np.stack([s, s], axis=1)
    return mic, system


# --- analysis -----------------------------------------------------------------------------------------
def goertzel_power(x: np.ndarray, hz: float, win: int) -> np.ndarray:
    """Power at `hz` in consecutive windows of `win` samples (mono float)."""
    n = len(x) // win
    if n == 0:
        return np.zeros(0)
    seg = x[:n * win].reshape(n, win)
    t = np.arange(win) / RATE
    c, s = np.cos(2 * np.pi * hz * t), np.sin(2 * np.pi * hz * t)
    return ((seg @ c) ** 2 + (seg @ s) ** 2) / win ** 2


def onsets(power: np.ndarray, win_s: float, thresh: float) -> list[float]:
    on = power > thresh
    starts = np.flatnonzero(on & ~np.concatenate([[False], on[:-1]]))
    return [float(i * win_s) for i in starts]


def wav_analysis(path: Path) -> dict:
    """Beep onsets and tone gaps, streamed 60 s at a time (the file is ~1.4 GB)."""
    win = 480                                              # 10 ms
    beeps, gaps, total = [], [], 0.0
    with wave.open(str(path)) as wf:
        n = wf.getnframes()
        pos = 0
        while pos < n:
            raw = wf.readframes(RATE * 60)
            x = np.frombuffer(raw, "<i2").astype(np.float32).reshape(-1, 2)[:, 0] / 32767
            p_beep = goertzel_power(x, BEEP_HZ, win)
            beeps += [pos / RATE + t for t in onsets(p_beep, 0.01, 0.01)]
            p_tone = goertzel_power(x, TONE_HZ, 4800)        # 100 ms windows: the tone is 0.1 -> power 0.0025
            gaps += [round(pos / RATE + i * 0.1, 1) for i in np.flatnonzero(p_tone < 0.0005)]
            pos += len(x)
        total = n / RATE
    merged = []
    for b in beeps:                                          # a beep cut by a 60 s chunk edge counts once
        if not merged or b - merged[-1] > 1.0:
            merged.append(b)
    return {"seconds": total, "beeps": merged, "tone_gaps": gaps}


def mp4_audio_beeps(path: Path) -> dict:
    """Decode the MP4's own AAC track (AVAssetReader) in pieces and find the beeps."""
    import AVFoundation as av
    import CoreAudio
    import CoreMedia
    from Foundation import NSURL
    asset = av.AVURLAsset.URLAssetWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
    tracks = asset.tracksWithMediaType_(av.AVMediaTypeAudio)
    if not tracks:
        return {"beeps": [], "seconds": 0.0}
    reader, _ = av.AVAssetReader.assetReaderWithAsset_error_(asset, None)
    out = av.AVAssetReaderTrackOutput.assetReaderTrackOutputWithTrack_outputSettings_(tracks[0], {
        av.AVFormatIDKey: CoreAudio.kAudioFormatLinearPCM, av.AVLinearPCMBitDepthKey: 32,
        av.AVLinearPCMIsFloatKey: True, av.AVLinearPCMIsNonInterleaved: False,
        av.AVSampleRateKey: RATE, av.AVNumberOfChannelsKey: 2})
    reader.addOutput_(out)
    reader.startReading()
    beeps, carry, pos = [], np.zeros(0, np.float32), 0
    while True:
        sb = out.copyNextSampleBuffer()
        if sb is None:
            break
        block = CoreMedia.CMSampleBufferGetDataBuffer(sb)
        _, data = CoreMedia.CMBlockBufferCopyDataBytes(block, 0, CoreMedia.CMBlockBufferGetDataLength(block), None)
        x = np.frombuffer(bytes(data), np.float32).reshape(-1, 2)[:, 0]
        carry = np.concatenate([carry, x])
        if len(carry) >= RATE * 10:
            k = (len(carry) // 480) * 480
            beeps += [pos / RATE + t for t in onsets(goertzel_power(carry[:k], BEEP_HZ, 480), 0.01, 0.01)]
            pos += k
            carry = carry[k:]
    if len(carry) >= 480:
        beeps += [pos / RATE + t for t in onsets(goertzel_power(carry, BEEP_HZ, 480), 0.01, 0.01)]
        pos += len(carry)
    merged = []
    for b in beeps:
        if not merged or b - merged[-1] > 1.0:
            merged.append(b)
    return {"beeps": merged, "seconds": pos / RATE}


def video_scan(path: Path, pages, per_page: float, frames_dir: Path) -> dict:
    """Every frame once: count, the box marks, which slide is shown; a frame from the middle of each
    slide's time is saved for the 도형PPT check."""
    import cv2
    thumbs = [cv2.resize(p[:, :, :3], (48, 27), interpolation=cv2.INTER_AREA).astype(np.int16) for p in pages]
    cap = cv2.VideoCapture(str(path))
    n, marks, prev_mark, seen, wrong, last_t = 0, [], False, [], 0, 0.0
    want = {k: (k + 0.5) * per_page for k in range(len(pages))}
    saved = set()
    frames_dir.mkdir(parents=True, exist_ok=True)
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        n, last_t = n + 1, t
        corner = img[H - 160:H - 40, W - 160:W - 40].reshape(-1, 3).mean(axis=0)
        mark = corner[0] > 200 and corner[2] > 200 and corner[1] < 60
        if mark and not prev_mark:
            marks.append(t)
        prev_mark = mark
        if n % 15 == 0 or mark:
            small = cv2.resize(img, (48, 27), interpolation=cv2.INTER_AREA).astype(np.int16)
            small[-6:, -6:] = thumbs[0][-6:, -6:]               # the mark corner is not the slide
            k = int(np.argmin([np.abs(small - th)[:-6].mean() for th in thumbs]))
            expect = min(len(pages) - 1, int(t // per_page))
            near_change = min(abs(t - expect * per_page), abs(t - (expect + 1) * per_page)) < 1.0
            if not near_change and k != expect:
                wrong += 1
            if not seen or seen[-1] != k:
                seen.append(k)
        for k, tw in list(want.items()):
            if k not in saved and t >= tw and not mark:
                cv2.imwrite(str(frames_dir / f"slide_{k + 1:02d}.png"), img)
                saved.add(k)
    cap.release()
    return {"frames": n, "last_t": last_t, "marks": marks, "slides_in_order": seen == list(range(len(pages))),
            "slides_seen": len(seen), "wrong_slide_samples": wrong, "frames_saved": len(saved)}


def pair_offsets(marks: list[float], beeps: list[float]) -> list[float]:
    """Each video mark with its nearest beep (s, beep - mark)."""
    out = []
    for m in marks:
        if not beeps:
            break
        b = min(beeps, key=lambda x: abs(x - m))
        if abs(b - m) < 2.0:
            out.append(round(b - m, 3))
        else:
            out.append(None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--minutes", type=float, default=130.0)
    ap.add_argument("--speed", type=float, default=9.0)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "rec-long"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QCoreApplication, QRect
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from capture_tool.app.recording_ui import Recorder
    from capture_tool.core.geometry import Rect
    from capture_tool.core.settings import Settings
    from capture_tool.platform.mac import recorder as mac_recorder
    report: dict = {"minutes": a.minutes, "speed": a.speed, "fps": a.fps, "size": [W, H]}
    t0 = time.monotonic()
    pages = render_pages(a.pdf)
    report["slides"] = len(pages)
    active_len = a.minutes * 60
    world = World(pages, active_len, a.speed)
    mic_sig, sys_sig = make_signals(world)
    sources = [FakeSource("mic", world, mic_sig, +60, 1), FakeSource("system", world, sys_sig, -60, 2)]
    writers = []

    class Screen:
        def recording_grabber(self, rect):
            return world.grab

        def mouse_reader(self, rect):
            return world.mouse

        def open_recorder(self, **kw):
            w = mac_recorder.open_writer(**kw)
            writers.append(w)
            return w

        def sound_sources(self, mic, system):
            return sources

        def exclude_from_capture(self, hwnd):
            return True

        def esc_pressed(self):
            return False

    s = Settings(record_countdown=False, record_fps=a.fps, record_max_minutes=240)
    path = out / "long.mp4"
    rec = Recorder(Screen(), s, Rect(0, 0, W, H), QRect(0, 0, 960, 540), QRect(0, 0, 1440, 900), 2.0, path,
                   clock=world.clock, sleep=world.sleep)
    ended = []
    rec.ended.connect(ended.append)
    events = {"paused": False, "muted": False}

    def control(wall: float) -> None:                        # break, mute and the end, on the clock
        ses = rec.session
        if ses is None:
            return
        if BREAK_AT <= wall < BREAK_AT + BREAK_LEN and not events["paused"]:
            ses.pause(wall)
            events["paused"] = True
        elif wall >= BREAK_AT + BREAK_LEN and events["paused"] is True:
            ses.resume(wall)
            events["paused"] = "done"
        act = world.active(wall)
        if MUTE[0] <= act < MUTE[1] and not events["muted"]:
            ses.mute("mic", True)
            events["muted"] = True
        elif act >= MUTE[1] and events["muted"] is True:
            ses.mute("mic", False)
            events["muted"] = "done"
        if act >= active_len:
            rec.stop()
    world.on_wall.insert(0, control)
    print(f"slides {len(pages)} rendered in {time.monotonic() - t0:.0f}s; recording {a.minutes:.0f} min at {a.speed}x",
          flush=True)
    rec_t0 = time.monotonic()
    rec.start()
    last_print = 0.0
    peak_rss = rss_mb()
    while not ended:
        QCoreApplication.processEvents()
        time.sleep(0.05)
        peak_rss = max(peak_rss, rss_mb())
        if time.monotonic() - last_print > 60:
            last_print = time.monotonic()
            ses = rec.session
            print(f"  wall {world.wall / 60:6.1f} min  frames {ses.frames if ses else 0}  dropped "
                  f"{ses.dropped if ses else 0}  rss {peak_rss:.0f} MB", flush=True)
    ses = ended[0]
    report["record"] = {"state": ses.state, "reason": ses.reason, "error": ses.error, "frames": ses.frames,
                        "dropped": ses.dropped, "elapsed_media_s": round(ses.elapsed, 2),
                        "wall_s": round(time.monotonic() - rec_t0, 1), "peak_rss_mb": round(peak_rss),
                        "mp4_mb": round(path.stat().st_size / 1e6, 1),
                        "wav_mb": round(ses.wav_path.stat().st_size / 1e6, 1) if ses.wav_path else None}
    print("recorded:", report["record"], flush=True)
    json.dump(report, open(out / "report.json", "w"), indent=1)

    # --- checks on the file -------------------------------------------------------------------
    from capture_tool.core.recording_export import video_info
    vw, vh, fps, length = video_info(path)
    report["file"] = {"w": vw, "h": vh, "fps": fps, "length_s": round(length, 2)}
    t = time.monotonic()
    report["video"] = video_scan(path, pages, world.per_page, out / "frames")
    report["video"]["scan_s"] = round(time.monotonic() - t, 1)
    marks = report["video"].pop("marks")
    t = time.monotonic()
    wav = wav_analysis(ses.wav_path)
    mp4a = mp4_audio_beeps(path)
    report["audio_scan_s"] = round(time.monotonic() - t, 1)
    expected_marks = int(active_len // MARK_EVERY) - (1 if active_len % MARK_EVERY < MARK_LEN else 0)
    muted_marks = [m for m in marks if MUTE[0] - 0.5 <= m < MUTE[1]]
    off_wav = pair_offsets(marks, wav["beeps"])
    off_mp4 = pair_offsets(marks, mp4a["beeps"])

    def stats(offs, skip):
        vals = [o for m, o in zip(marks, offs) if o is not None and m not in skip]
        missing = sum(1 for m, o in zip(marks, offs) if o is None and m not in skip)
        if not vals:
            return {"missing": missing}
        return {"n": len(vals), "missing": missing, "min": min(vals), "max": max(vals),
                "first10min": [o for m, o in zip(marks, offs) if m < 600 and o is not None],
                "last10min": [o for m, o in zip(marks, offs) if m > active_len - 600 and o is not None]}
    report["sync"] = {"marks": len(marks), "expected_marks": expected_marks,
                      "wav_vs_video": stats(off_wav, set(muted_marks)),
                      "mp4_audio_vs_video": stats(off_mp4, set(muted_marks)),
                      "beeps_while_muted_wav": sum(1 for m, o in zip(marks, off_wav) if m in muted_marks and o is not None),
                      "wav_seconds": round(wav["seconds"], 2), "mp4_audio_seconds": round(mp4a["seconds"], 2),
                      "tone_gaps_100ms": len(wav["tone_gaps"]), "tone_gap_at_s": wav["tone_gaps"][:20]}
    report["peak_rss_mb_after_scan"] = round(rss_mb())
    json.dump(report, open(out / "report.json", "w"), indent=1)
    print("sync:", json.dumps(report["sync"])[:600], flush=True)

    # --- the result window and exports on the long file -------------------------------------------
    from capture_tool.app.recording_result import RecordingResult
    from capture_tool.core.recording_export import export
    t = time.monotonic()
    deps = {k: (lambda *x, **y: None) for k in ("set_clipboard", "save_folder", "share_dir", "unique", "ask_path",
                                                 "open_folder", "notify", "again", "files_payload")}
    deps["open_writer"] = mac_recorder.open_writer
    win = RecordingResult(path, ses.wav_path, deps)
    win.show()
    QCoreApplication.processEvents()
    report["result_window_open_s"] = round(time.monotonic() - t, 2)
    t = time.monotonic()
    cut = round(active_len * 0.69)                          # 1:30:00 of a 2:10:00 recording
    win.timeline.set_range(cut, cut + 60.0)
    QCoreApplication.processEvents()
    report["result_window_seek_s"] = round(time.monotonic() - t, 2)
    report["result_window_size_label"] = win.size_label.text()
    win.close()
    t = time.monotonic()
    part = export(path, ses.wav_path, cut, cut + 60.0, "mp4", out / "part.mp4", mac_recorder.open_writer)
    pw, ph, pfps, plen = video_info(part)
    pa = mp4_audio_beeps(part)
    report["export_mp4"] = {"from_s": cut, "s": round(time.monotonic() - t, 1), "length_s": round(plen, 2), "w": pw, "h": ph,
                            "audio_s": round(pa["seconds"], 2), "beeps": [round(b, 2) for b in pa["beeps"]],
                            "mb": round(part.stat().st_size / 1e6, 2)}
    t = time.monotonic()
    gcut = round(active_len * 0.8)
    gif = export(path, None, gcut, gcut + 10.0, "gif", out / "part.gif", None, gif_fps=10, max_width=800)
    from PIL import Image
    im = Image.open(gif)
    report["export_gif"] = {"from_s": gcut, "s": round(time.monotonic() - t, 1), "size": list(im.size), "frames": im.n_frames,
                            "mb": round(gif.stat().st_size / 1e6, 2)}
    report["total_s"] = round(time.monotonic() - t0, 1)
    json.dump(report, open(out / "report.json", "w"), indent=1)
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
