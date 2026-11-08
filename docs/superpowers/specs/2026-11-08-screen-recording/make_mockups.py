"""Mockups for the proposed screen recording feature, drawn with the app's real widgets where they
exist (capture screen, action bar) and the app's colours for the new parts. Writes PNGs to argv[1]."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(sys.argv[2])
sys.path.insert(0, str(ROOT))
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,  # noqa: E402
                               QLabel, QPushButton, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

app = QApplication([])
for f in ("/System/Library/Fonts/AppleSDGothicNeo.ttc",):
    QFontDatabase.addApplicationFont(f)
app.setFont(QFont("Apple SD Gothic Neo", 10))

W, H = 1280, 800


# --- a sample desktop: a report window with a chart and text ----------------------------------------
def desktop() -> QImage:
    img = QImage(W, H, QImage.Format_RGB888)
    img.fill(QColor("#D9DEE7"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    win = QRect(90, 60, 1100, 680)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(win, 10, 10)
    p.setBrush(QColor("#EEF1F6"))
    p.drawRoundedRect(QRect(win.x(), win.y(), win.width(), 44), 10, 10)
    p.setPen(QColor("#333"))
    p.setFont(QFont("Apple SD Gothic Neo", 12, QFont.Bold))
    p.drawText(win.x() + 20, win.y() + 29, "3분기 업무 보고 — 대시보드")
    p.setFont(QFont("Apple SD Gothic Neo", 11))
    for i, t in enumerate(["• 신규 가입자 12% 증가", "• 처리 시간 평균 1.8초 → 1.2초", "• 장애 0건, 점검 2회",
                           "• 다음 분기: 모바일 앱 출시 준비"]):
        p.drawText(win.x() + 30, win.y() + 90 + i * 30, t)
    # bar chart
    base_y, x0 = win.y() + 600, win.x() + 520
    p.setPen(QPen(QColor("#999"), 1))
    p.drawLine(x0 - 10, base_y, x0 + 520, base_y)
    for i, (v, c) in enumerate([(220, "#1F5FD1"), (300, "#1F5FD1"), (260, "#1F5FD1"), (380, "#E8730C")]):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c))
        p.drawRect(x0 + i * 125, base_y - v, 80, v)
        p.setPen(QColor("#555"))
        p.drawText(x0 + i * 125 + 18, base_y + 22, f"{i + 1}분기" if i < 3 else "예상")
    p.setPen(QColor("#444"))
    p.setFont(QFont("Apple SD Gothic Neo", 11, QFont.Bold))
    p.drawText(x0, win.y() + 90, "분기별 처리 건수")
    # a cursor
    p.setBrush(QColor("#111"))
    p.setPen(QPen(QColor("#FFF"), 1.5))
    cur = QPainterPath()
    cx, cy = 760, 380
    cur.moveTo(cx, cy)
    for dx, dy in ((0, 22), (6, 16), (11, 26), (15, 24), (10, 14), (18, 14)):
        cur.lineTo(cx + dx, cy + dy)
    cur.closeSubpath()
    p.drawPath(cur)
    p.end()
    return img


DESK = desktop()


def to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    return a.reshape(img.height(), img.width(), 3)[:, :, ::-1].copy()      # BGR like a screen grab


# --- 1. the capture screen with a new 녹화 button (the real overlay and action bar) ----------------
def mock_capture_bar() -> QPixmap:
    from capture_tool.app import icons, side_bar
    from capture_tool.core import bar_layout as bl
    from capture_tool.core.geometry import Monitor, Rect
    # in memory only, for the picture: a 녹화 button next to 스크롤
    icons._P["record"] = '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>'
    side_bar.ACTIONS.insert(2, ("record", "record", "녹화",
                                "고른 영역을 동영상으로 녹화 (MP4 · GIF) — 다시 누르거나 Esc 로 끝", "basic"))
    side_bar.LABELS["record"] = "녹화"
    for key, label, names in bl.GROUPS:
        if key == "screen":
            names.insert(0, "record")
    bl.NAMES.insert(-1, "record")
    bl._GROUP_OF["record"], bl._LABEL_OF["record"] = "screen", "화면"
    bl.DEFAULT_FAVOURITES.insert(1, "record")

    from capture_tool.app.controller import Controller
    from capture_tool.core.settings import Settings

    class Screen:
        def monitors(self):
            return [Monitor(0, Rect(0, 0, W, H), 1.0, True, "A")]

        def cursor_pos(self):
            return (700, 400)

        def grab(self, r):
            a = to_array(DESK)
            return a[r.y:r.y + r.h, r.x:r.x + r.w].copy()

        def windows(self):
            return []

    class Clip:
        def set(self, payload):
            pass

    class Ocr:
        ready = True

        def recognize(self, img):
            return []

        def warmup(self):
            pass

    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "rec_mockup" / "state"
    tmp.mkdir(parents=True, exist_ok=True)
    c = Controller(screen=Screen(), clipboard=Clip(), ocr=Ocr(), settings=Settings(save_dir=str(tmp / "shots"),
                   show_recent=False), settings_path=tmp / "settings.json", fallback_dir=tmp / "fb", sync=True)
    c.start_capture()
    ov = c.overlays[0]
    ov.resize(W, H)
    from PySide6.QtTest import QTest
    a, b = QPoint(560, 120), QPoint(1150, 690)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, a)
    for t in (0.3, 0.6, 1.0):
        QTest.mouseMove(ov, QPoint(int(a.x() + (b.x() - a.x()) * t), int(a.y() + (b.y() - a.y()) * t)))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, b)
    app.processEvents()
    pm = ov.grab()
    # point at the new button
    btn = ov.side_bar.buttons.get("record")
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if btn is not None:
        r = QRect(btn.mapTo(ov, QPoint(0, 0)), btn.size()).adjusted(-4, -4, 4, 4)
        p.setPen(QPen(QColor("#E03131"), 3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        _callout(p, r, "새 버튼: 녹화\n고른 영역을 동영상으로")
    p.end()
    c.close_all()
    return pm


def _callout(p: QPainter, target: QRect, text: str) -> None:
    lines = text.split("\n")
    f = QFont("Apple SD Gothic Neo", 12, QFont.Bold)
    p.setFont(f)
    w = max(p.fontMetrics().horizontalAdvance(t) for t in lines) + 28
    h = 22 * len(lines) + 16
    box = QRect(target.x() - 40, target.bottom() + 18, w, h)
    if box.bottom() > H - 10:
        box.moveBottom(target.top() - 18)
    if box.right() > W - 10:
        box.moveRight(W - 10)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#E03131"))
    p.drawRoundedRect(box, 8, 8)
    p.setPen(QColor("#FFFFFF"))
    for i, t in enumerate(lines):
        p.drawText(box.x() + 14, box.y() + 26 + i * 22, t)


def _callout_left(p: QPainter, target: QRect, text: str) -> None:
    """A red note to the left of `target`, with a short pointer."""
    lines = text.split("\n")
    p.setFont(QFont("Apple SD Gothic Neo", 12, QFont.Bold))
    w = max(p.fontMetrics().horizontalAdvance(t) for t in lines) + 28
    h = 22 * len(lines) + 16
    box = QRect(target.x() - w - 24, target.center().y() - h // 2 + 40, w, h)
    p.setPen(QPen(QColor("#E03131"), 2))
    p.drawLine(box.right(), box.center().y(), target.x() - 4, target.center().y())
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#E03131"))
    p.drawRoundedRect(box, 8, 8)
    p.setPen(QColor("#FFFFFF"))
    for i, t in enumerate(lines):
        p.drawText(box.x() + 14, box.y() + 26 + i * 22, t)


# --- 2. while recording: the area's red frame and the small control bar -----------------------------
PILL_STYLE = """
QWidget#pill { background: rgba(15,18,24,232); border-radius: 12px; }
QLabel { color: #E9ECF2; font-size: 14px; }
QLabel#rec { color: #FF5A5A; font-size: 15px; font-weight: bold; }
QToolButton { color: #E9ECF2; background: #262C3A; border: 1px solid #353C4E; border-radius: 8px;
              padding: 6px 12px; font-size: 13px; }
QToolButton#stop { background: #C92A2A; border-color: #E03131; font-weight: bold; }
"""


def control_pill(paused: bool = False) -> QWidget:
    w = QWidget()
    w.setObjectName("pill")
    w.setAttribute(Qt.WA_StyledBackground, True)
    w.setAttribute(Qt.WA_TranslucentBackground, True)          # rounded corners, not a dark square
    w.setStyleSheet(PILL_STYLE)
    h = QHBoxLayout(w)
    h.setContentsMargins(14, 8, 10, 8)
    h.setSpacing(8)
    rec = QLabel("● 녹화 중" if not paused else "❚❚ 일시정지")
    rec.setObjectName("rec")
    h.addWidget(rec)
    h.addWidget(QLabel("00:12"))
    h.addWidget(QLabel("·  1.8 MB"))
    for text, name in (("🎙 마이크 끔", "mic"), ("❚❚ 일시정지" if not paused else "▶ 계속", "pause"),
                       ("■ 끝내기 (Esc)", "stop")):
        b = QToolButton()
        b.setText(text)
        b.setObjectName(name)
        h.addWidget(b)
    w.adjustSize()
    return w


def mock_recording() -> QPixmap:
    pm = QPixmap.fromImage(DESK)
    area = QRect(560, 120, 590, 570)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    veil = QPainterPath()
    veil.addRect(QRectF(0, 0, W, H))
    hole = QPainterPath()
    hole.addRect(QRectF(area))
    p.fillPath(veil.subtracted(hole), QColor(0, 0, 0, 70))          # outside the area, lightly dimmed
    p.setPen(QPen(QColor("#E03131"), 3, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(area.adjusted(-2, -2, 2, 2))
    # a click ring (optional: show clicks)
    p.setPen(QPen(QColor(255, 196, 0, 220), 4))
    p.drawEllipse(QPoint(767, 392), 22, 22)
    pill = control_pill()
    pill_pm = pill.grab()
    px, py = area.center().x() - pill_pm.width() // 2, area.top() - pill_pm.height() - 14
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(15, 18, 24, 232))                          # the bar's own dark rounded body
    p.drawRoundedRect(QRect(px, py, pill_pm.width(), pill_pm.height()), 12, 12)
    p.drawPixmap(px, py, pill_pm)
    _callout_left(p, QRect(px, py, pill_pm.width(), pill_pm.height()), "영역 밖에 뜨는 조작 막대\n(녹화 화면에는 안 찍힘)")
    p.end()
    return pm


# --- 3. after recording: preview, trim, format, then the usual 복사 / 저장 -------------------------
RESULT_STYLE = """
QWidget#result { background: #F7F8FA; }
QLabel#title { font-size: 16px; font-weight: bold; color: #222; }
QLabel#info { color: #555; font-size: 13px; }
QToolButton { border: 1px solid #C9CFDB; border-radius: 8px; background: #FFFFFF; padding: 7px 14px; font-size: 13px; }
QToolButton#primary { background: #1F5FD1; color: white; border-color: #1F5FD1; font-weight: bold; }
QToolButton#fmt_on { background: #E8F0FE; border: 2px solid #1F5FD1; color: #1F5FD1; font-weight: bold; }
"""


class Timeline(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(66)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(10, 14, -10, -18)
        thumbs = 12
        tw = r.width() / thumbs
        src = DESK.copy(QRect(560, 120, 590, 570))
        for i in range(thumbs):
            t = QRectF(r.x() + i * tw, r.y(), tw - 2, r.height())
            p.drawImage(t, src)
        a, b = r.x() + r.width() * 0.08, r.x() + r.width() * 0.86
        p.fillRect(QRectF(r.x(), r.y(), a - r.x(), r.height()), QColor(0, 0, 0, 140))
        p.fillRect(QRectF(b, r.y(), r.right() - b, r.height()), QColor(0, 0, 0, 140))
        p.setPen(QPen(QColor("#1F5FD1"), 3))
        p.drawRect(QRectF(a, r.y() - 2, b - a, r.height() + 4))
        for x in (a, b):
            p.setBrush(QColor("#1F5FD1"))
            p.drawRoundedRect(QRectF(x - 6, r.y() - 6, 12, r.height() + 12), 4, 4)
        play = r.x() + r.width() * 0.4
        p.setPen(QPen(QColor("#E03131"), 2))
        p.drawLine(int(play), r.y() - 8, int(play), r.bottom() + 8)
        p.setPen(QColor("#555"))
        p.setFont(QFont("Apple SD Gothic Neo", 10))
        p.drawText(int(a) - 14, self.height() - 2, "0:01")
        p.drawText(int(b) - 14, self.height() - 2, "0:11")
        p.end()


def mock_result() -> QPixmap:
    w = QWidget()
    w.setObjectName("result")
    w.setAttribute(Qt.WA_StyledBackground, True)
    w.setStyleSheet(RESULT_STYLE)
    w.resize(920, 720)
    v = QVBoxLayout(w)
    v.setContentsMargins(20, 16, 20, 16)
    v.setSpacing(10)
    title = QLabel("녹화 결과 — 12초 · 590×570")
    title.setObjectName("title")
    v.addWidget(title)
    prev = QLabel()
    src = QPixmap.fromImage(DESK.copy(QRect(560, 120, 590, 570))).scaled(600, 390, Qt.KeepAspectRatio,
                                                                          Qt.SmoothTransformation)
    prev.setPixmap(src)
    prev.setAlignment(Qt.AlignCenter)
    prev.setStyleSheet("background: #1B1F2A; border-radius: 10px;")
    prev.setMinimumHeight(400)
    v.addWidget(prev, 1)
    ctrl = QHBoxLayout()
    for t in ("▶ 재생", "0:04 / 0:12"):
        lb = QToolButton() if t.startswith("▶") else QLabel(t)
        if isinstance(lb, QToolButton):
            lb.setText(t)
        ctrl.addWidget(lb)
    ctrl.addStretch(1)
    hint = QLabel("파란 손잡이를 끌어 앞뒤를 잘라냅니다")
    hint.setObjectName("info")
    ctrl.addWidget(hint)
    v.addLayout(ctrl)
    v.addWidget(Timeline())
    fmt = QHBoxLayout()
    lab = QLabel("형식")
    lab.setObjectName("info")
    fmt.addWidget(lab)
    for text, on in (("MP4 동영상", True), ("GIF 움짤", False)):
        b = QToolButton()
        b.setText(text)
        b.setObjectName("fmt_on" if on else "fmt")
        fmt.addWidget(b)
    q = QComboBox()
    q.addItems(["화질: 보통 (15fps)", "화질: 부드럽게 (30fps)", "화질: 작게 (10fps)"])
    fmt.addWidget(q)
    fmt.addStretch(1)
    size = QLabel("10초 · 약 1.6 MB")
    size.setObjectName("info")
    fmt.addWidget(size)
    v.addLayout(fmt)
    acts = QHBoxLayout()
    for text, primary in (("복사", True), ("저장", False), ("다른 이름 저장", False), ("메일", False),
                          ("카톡", False), ("저장 폴더", False)):
        b = QToolButton()
        b.setText(text)
        if primary:
            b.setObjectName("primary")
        acts.addWidget(b)
    acts.addStretch(1)
    b = QToolButton()
    b.setText("다시 녹화")
    acts.addWidget(b)
    v.addLayout(acts)
    w.show()
    app.processEvents()
    return w.grab()


# --- 4. settings: a 녹화 section ---------------------------------------------------------------------
def mock_settings() -> QPixmap:
    w = QFrame()
    w.setStyleSheet("QFrame { background: #FFFFFF; } QLabel#h { font-size: 15px; font-weight: bold; } "
                    "QLabel#note { color: #777; font-size: 12px; }")
    w.resize(620, 360)
    g = QGridLayout(w)
    g.setContentsMargins(20, 16, 20, 16)
    h = QLabel("녹화")
    h.setObjectName("h")
    g.addWidget(h, 0, 0, 1, 2)
    rows = [("단축키", "Ctrl + Alt + R"), ("기본 형식", "MP4 동영상"), ("초당 장면 수", "15 (보통)")]
    for i, (k, val) in enumerate(rows, start=1):
        g.addWidget(QLabel(k), i, 0)
        cb = QComboBox()
        cb.addItem(val)
        g.addWidget(cb, i, 1)
    r = len(rows) + 1
    g.addWidget(QLabel("최대 길이"), r, 0)
    sp = QSpinBox()
    sp.setSuffix(" 분")
    sp.setValue(10)
    g.addWidget(sp, r, 1)
    for j, (text, on) in enumerate((("마우스 커서 보이기", True), ("클릭할 때 노란 원 표시", True),
                                    ("마이크 소리 녹음 (2단계)", False), ("녹화 시작 전 3초 세기", True)), start=r + 1):
        c = QCheckBox(text)
        c.setChecked(on)
        g.addWidget(c, j, 0, 1, 2)
    note = QLabel("회사용: 보호된 영상(DRM)·보안 창은 녹화되지 않고 검게 나옵니다.")
    note.setObjectName("note")
    g.addWidget(note, r + 5, 0, 1, 2)
    w.show()
    app.processEvents()
    return w.grab()


for name, make in (("1-capture-bar", mock_capture_bar), ("2-recording", mock_recording),
                   ("3-result", mock_result), ("4-settings", mock_settings)):
    pm = make()
    pm.save(str(OUT / f"{name}.png"))
    print("wrote", OUT / f"{name}.png", pm.width(), pm.height())
