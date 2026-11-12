"""After a recording: keep a part of it (cut off the start / end) as a new MP4 through the same OS
writer, or make a GIF. Frames are read back from the MP4 with OpenCV (its decoder reads the H.264 the
OS wrote); the sound comes from the WAV the recording kept, so no audio decoder is needed."""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from .recording import RATE

AUDIO_CHUNK = RATE // 2                   # 0.5 s per audio write


def read_frames(path) -> Iterator[tuple[float, np.ndarray]]:
    """(time in s, BGR picture) for every frame of a video file."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
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


def read_wav(path) -> np.ndarray | None:
    """The recording's sound as float32 [n, 2], or None when there is no WAV."""
    if path is None or not Path(path).exists():
        return None
    with wave.open(str(path)) as wf:
        raw = wf.readframes(wf.getnframes())
        ch = wf.getnchannels()
    return (np.frombuffer(raw, "<i2").astype(np.float32) / 32767).reshape(-1, ch)


def write_trimmed(frames: Iterable[tuple[float, np.ndarray]], pcm: np.ndarray | None, start: float, end: float,
                  writer) -> None:
    """The part [start, end) of a recording into `writer` (opened with sound when pcm is given)."""
    try:
        for t, bgr in frames:
            if t < start - 1e-9:
                continue
            if t >= end - 1e-9:
                break
            bgra = np.dstack([bgr, np.full(bgr.shape[:2], 255, np.uint8)])
            writer.add_frame(bgra, t - start)
        if pcm is not None and len(pcm):
            part = pcm[int(round(start * RATE)):int(round(end * RATE))]
            for k in range(0, len(part), AUDIO_CHUNK):
                writer.add_audio(np.ascontiguousarray(part[k:k + AUDIO_CHUNK], np.float32), k / RATE)
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
