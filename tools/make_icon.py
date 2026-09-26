"""Render the app icon to assets/app.ico (multi-size, PNG-compressed entries)."""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from capture_tool.app.main import app_icon  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    QApplication([])
    icon = app_icon()
    images = []
    for s in SIZES:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        icon.pixmap(s, s).toImage().save(buf, "PNG")
        images.append(bytes(ba))
    out = Path(__file__).resolve().parents[1] / "assets" / "app.ico"
    out.parent.mkdir(exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for s, png in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    out.write_bytes(header + entries + data)
    print("wrote", out)


if __name__ == "__main__":
    main()
