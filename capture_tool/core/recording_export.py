"""After a recording: keep a part of it (cut off the start / end) as a new MP4 through the same OS
writer, or make a GIF. Frames are read back from the MP4 with OpenCV (its decoder reads the H.264 the
OS wrote); the sound comes from the WAV the recording kept, so no audio decoder is needed."""
from __future__ import annotations

import shutil
import wave
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from .recording import RATE

AUDIO_CHUNK = RATE // 2                   # 0.5 s per audio write
SOUND_LEAD = 2.0                          # s the sound is written ahead of the pictures (see write_trimmed)


def read_frames(path, start: float = 0.0) -> Iterator[tuple[float, np.ndarray]]:
    """(time in s, BGR picture) for every frame of a video file - from about `start` on: the reader
    jumps there (a part from late in a 2-hour recording is not decoded from the beginning). The
    first frame given is at or before `start`."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if start > 1.0:
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000.0 * (start - 1.0))
        while True:
            ok, img = cap.read()
            if not ok:
                return
            yield cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, img
    finally:
        cap.release()


def video_info(path) -> tuple[int, int, float, float]:
    """(width, height, frames per second, length in s) of a video file."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        return w, h, fps, (n / fps if n and fps else 0.0)
    finally:
        cap.release()


def read_wav(path, start: float = 0.0, end: float | None = None) -> np.ndarray | None:
    """The recording's sound in [start, end) as float32 [n, 2], or None when there is no WAV. Only that
    range is read (2 hours of sound are 1.4 GB on disk, twice that as float)."""
    if path is None or not Path(path).exists():
        return None
    with wave.open(str(path)) as wf:
        rate, ch, total = wf.getframerate(), wf.getnchannels(), wf.getnframes()
        a = min(total, max(0, int(round(start * rate))))
        b = total if end is None else min(total, max(a, int(round(end * rate))))
        wf.setpos(a)
        raw = wf.readframes(b - a)
    return (np.frombuffer(raw, "<i2").astype(np.float32) / 32767).reshape(-1, ch)


def write_trimmed(frames: Iterable[tuple[float, np.ndarray]], pcm: np.ndarray | None, start: float, end: float,
                  writer, pcm_start: float = 0.0) -> None:
    """The part [start, end) of a recording into `writer` (opened with sound when pcm is given; pcm
    begins at `pcm_start` of the recording). The sound goes in SOUND_LEAD ahead of the pictures: the
    Mac encoder, when not in real time, stops taking pictures that run ahead of the sound (all
    pictures first, then the sound, stalled every part longer than a second or two)."""
    part = None
    if pcm is not None and len(pcm):
        part = pcm[max(0, int(round((start - pcm_start) * RATE))):max(0, int(round((end - pcm_start) * RATE)))]
    done, ended = 0, False                                # samples of `part` written; sound marked ended

    def sound_until(t: float) -> None:
        nonlocal done, ended
        if part is None or ended:
            return
        upto = min(len(part), int(round(t * RATE)))
        while done < upto:
            n = min(AUDIO_CHUNK, upto - done)
            writer.add_audio(np.ascontiguousarray(part[done:done + n], np.float32), done / RATE)
            done += n
        if done >= len(part) and hasattr(writer, "end_audio"):
            writer.end_audio()          # all of it is in: the last pictures must not wait for more sound
            ended = True
    try:
        for t, bgr in frames:
            if t < start - 1e-9:
                continue
            if t >= end - 1e-9:
                break
            sound_until(t - start + SOUND_LEAD)
            bgra = np.dstack([bgr, np.full(bgr.shape[:2], 255, np.uint8)])
            writer.add_frame(bgra, t - start)
        sound_until(end - start)
    finally:
        writer.close()


def write_gif(frames: Iterable[tuple[float, np.ndarray]], dst, start: float, end: float, fps: int = 10,
              max_width: int = 800) -> Path:
    """A looping GIF of [start, end): `fps` pictures a second, at most `max_width` px wide."""
    from PIL import Image
    pics, step, next_t = [], 1.0 / fps, start
    for t, bgr in frames:
        if t < next_t - 1e-9 or t < start - 1e-9:
            continue
        if t >= end - 1e-9:
            break
        h, w = bgr.shape[:2]
        im = Image.fromarray(bgr[:, :, ::-1])
        if w > max_width:
            im = im.resize((max_width, round(h * max_width / w)), Image.LANCZOS)
        pics.append(im.convert("P", palette=Image.ADAPTIVE, colors=256))
        next_t += step
        while next_t <= t:
            next_t += step
    if not pics:
        raise ValueError("no picture in the chosen part")
    dst = Path(dst)
    pics[0].save(dst, save_all=True, append_images=pics[1:], duration=int(round(1000 / fps)), loop=0, optimize=True)
    return dst


def gif_size_estimate(width: int, height: int, seconds: float, fps: int) -> int:
    """A rough GIF size in bytes (screen content compresses to ~0.15 byte per pixel per frame)."""
    return int(width * height * max(1, round(seconds * fps)) * 0.15)


def mp4_size_estimate(width: int, height: int, seconds: float, fps: int, sound: bool) -> int:
    """MP4 bytes from the writers' bit rate (~0.1 bit per pixel per frame) plus 128 kbit/s of sound."""
    video = min(20_000_000, max(500_000, width * height * fps * 0.1))
    return int((video + (128_000 if sound else 0)) * seconds / 8)


def export(src, wav, start: float, end: float, kind: str, dst, open_writer, gif_fps: int = 10,
           max_width: int = 800) -> Path:
    """The kept part [start, end) of recording `src` as `dst`: the file itself when nothing was cut
    off (no second encode), a new MP4 through the OS writer (`open_writer(**kw)`, not real-time: it
    waits for the encoder) or a GIF."""
    src, dst = Path(src), Path(dst)
    w, h, fps, length = video_info(src)
    if kind == "gif":
        return write_gif(read_frames(src, start), dst, start, end, gif_fps, max_width)
    if start <= 0.05 and (length <= 0 or end >= length - 0.05):
        shutil.copyfile(src, dst)
        return dst
    pcm = read_wav(wav, start, end)
    writer = open_writer(path=dst, width=w, height=h, fps=int(round(fps)),
                         audio={"rate": RATE, "channels": 2} if pcm is not None else None, realtime=False)
    write_trimmed(read_frames(src, start), pcm, start, end, writer, pcm_start=start)
    return dst
