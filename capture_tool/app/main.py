"""Entry point: tray app, single instance, global hotkeys, OCR warm-up."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import __version__
from ..core import settings as settings_io
from ..core.ocr import OcrEngine
from . import icons
from .controller import Controller
from .hotkeys import HotkeyWindow
from .services import RealClipboard, RealScreen
from .settings_dialog import SettingsDialog

APP = "CaptureTool"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP


def fallback_dir() -> Path:
    return Path.home() / "Pictures" / "Captures"


def app_icon() -> QIcon:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
           '<rect x="2" y="2" width="60" height="60" rx="14" fill="#1F5FD1"/>'
           '<path d="M16 26V16h10M38 16h10v10M48 38v10H38M26 48H16V38" fill="none" stroke="#FFFFFF" '
           'stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
           '<circle cx="32" cy="32" r="5" fill="#FFFFFF"/></svg>')
    icon = QIcon()
    r = QSvgRenderer(QByteArray(svg.encode()))
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        icon.addPixmap(pm)
    return icon


def setup_logging(directory: Path | None = None, max_bytes: int = 1_000_000, backups: int = 2) -> logging.Logger:
    """Rotating log (≤ ~3 MB in total). Never logs recognized screen text."""
    from logging.handlers import RotatingFileHandler
    d = directory or log_dir()
    d.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(d / "capture.log", maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger() if directory is None else logging.getLogger(f"capture_tool.{id(handler)}")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


INSTANCE_COMMANDS = {b"capture": "capture"}


def handle_instance_message(data: bytes, trigger) -> bool:
    """Second launch asks the running instance to capture. Accept only the exact command."""
    action = INSTANCE_COMMANDS.get(bytes(data).strip())
    if action is None:
        logging.warning("ignored unexpected single-instance message (%d bytes)", len(data))
        return False
    trigger(action)
    return True


class TrayApp:
    def __init__(self, app: QApplication, selftest: bool = False):
        self._toast = None
        self.app = app
        self.settings_path = data_dir() / "settings.json"
        self.settings, warnings = settings_io.load(self.settings_path)
        self.hk_window = HotkeyWindow()
        self.ocr = OcrEngine()
        self.ocr.warmup()
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip(f"캡처 도구 {__version__}")
        self.controller = Controller(RealScreen(), RealClipboard(self.hk_window.hwnd), self.ocr, self.settings,
                                     self.settings_path, fallback_dir(), notify=self.toast)
        self.hk_window.manager.triggered.connect(self.on_hotkey)
        self.controller.prewarm()
        app.screenAdded.connect(lambda *_: self.controller.prewarm())
        self._build_menu()
        self.tray.show()
        self.tray.activated.connect(lambda reason: self.on_hotkey("capture")
                                    if reason == QSystemTrayIcon.Trigger else None)
        for w in warnings:
            self.toast(w)
        if not selftest:
            self.apply_hotkeys(first_run=not self.settings_path.exists())

    # --- ui ------------------------------------------------------------------------
    def toast(self, msg: str) -> None:
        # on-screen message (tray balloons are often hidden by Windows); deferred so a copy
        # is never delayed by painting it
        def show():
            if self._toast is None:
                from .toast import Toast
                self._toast = Toast()
            self._toast.show_message(msg)
        QTimer.singleShot(0, show)

    def _build_menu(self) -> None:
        m = QMenu()
        hk = self.settings.hotkeys
        for label, action in [("캡처 + 그리기", "capture"), ("텍스트 바로 복사", "ocr"),
                              ("도형 바로 복사 (PPT)", "shapes"), ("전체 화면 캡처", "fullscreen"),
                              ("스크롤 캡처", "scroll")]:
            key = hk.get(action) or ""
            a = QAction(f"{label}\t{key}" if key else label, m)
            a.triggered.connect(lambda _=False, x=action: QTimer.singleShot(250, lambda: self.on_hotkey(x)))
            m.addAction(a)
        m.addSeparator()
        auto = QAction("캡처 자동 저장 (캡처할 때마다 저장 폴더에)", m)
        auto.setCheckable(True)
        auto.setChecked(self.settings.auto_save)
        auto.toggled.connect(self._set_auto_save)
        m.addAction(auto)
        self.auto_save_action = auto
        a = QAction("고정 이미지 모두 닫기", m)
        a.triggered.connect(self.controller.close_pins)
        m.addAction(a)
        a = QAction("설정…", m)
        a.triggered.connect(self.open_settings)
        m.addAction(a)
        a = QAction("저장 폴더 열기", m)
        a.triggered.connect(self.open_folder)
        m.addAction(a)
        m.addSeparator()
        a = QAction("종료", m)
        a.triggered.connect(self.quit)
        m.addAction(a)
        self.menu = m
        self.tray.setContextMenu(m)

    def _set_auto_save(self, on: bool) -> None:
        self.settings.auto_save = on
        try:
            settings_io.save(self.settings, self.settings_path)
        except OSError:
            pass
        self.toast("캡처 자동 저장을 켰습니다. 캡처할 때마다 저장 폴더에 저장합니다." if on
                   else "캡처 자동 저장을 껐습니다.")

    def on_hotkey(self, action: str) -> None:
        mode = {"capture": "draw", "ocr": "text", "shapes": "shapes", "fullscreen": "fullscreen",
                "scroll": "scroll"}[action]
        self.controller.start_capture(mode)

    def apply_hotkeys(self, first_run: bool = False) -> None:
        failures = self.hk_window.manager.apply(self.settings.hotkeys)
        for msg in failures.values():
            self.toast(msg)
        if failures:
            QTimer.singleShot(800, self.open_settings)
        elif first_run:
            self.toast(f"실행 중입니다. {self.settings.hotkeys['capture']} 로 캡처하세요.")

    def _sync_startup(self) -> None:
        if not getattr(sys, "frozen", False):
            return  # only the installed exe registers itself
        from ..platform import startup
        try:
            startup.set_enabled(self.settings.launch_at_startup, sys.executable)
        except OSError as e:
            logging.warning("startup registration failed: %s", e)

    def open_settings(self) -> None:
        if getattr(sys, "frozen", False):  # show the real state (the installer may have set it)
            from ..platform import startup
            self.settings.launch_at_startup = startup.is_enabled()
        dlg = SettingsDialog(self.settings)
        dlg.setWindowIcon(app_icon())
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if dlg.exec():
            new = dlg.result_settings()
            self.settings.__dict__.update(new.__dict__)
            try:
                settings_io.save(self.settings, self.settings_path)
            except OSError as e:
                QMessageBox.warning(None, "캡처 도구", f"설정을 저장하지 못했습니다: {e}")
            self.apply_hotkeys()
            self._sync_startup()
            self._build_menu()

    def open_folder(self) -> None:
        from ..core.naming import SaveDirError, resolve_save_dir
        try:
            d, _ = resolve_save_dir(self.settings.save_dir, fallback_dir())
            if not Path(d).is_dir():  # never "open" a file path taken from settings
                raise OSError(f"폴더가 아닙니다: {d}")
            os.startfile(d)  # noqa: S606 - opening the user's own folder in Explorer
        except (SaveDirError, OSError) as e:
            self.toast(str(e))

    def quit(self) -> None:
        self.hk_window.manager.apply({})
        self.controller.close_all()
        self.tray.hide()
        self.app.quit()


def selftest(tray: TrayApp) -> int:
    """End-to-end check on the real desktop: grab, select, draw, copy, OCR warm-up, timings."""
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    from ..core.clipboard_payload import PNG
    from ..platform import win_clipboard

    c = tray.controller
    tray.ocr._load()  # in real use the warm-up has long finished before the first hotkey
    tray.ocr._load_secondary()
    c.sync = False  # like real use: cursor monitor now, other monitors right after
    t0 = time.perf_counter()
    assert c.start_capture(), "capture did not start"
    t_overlay = (time.perf_counter() - t0) * 1000
    QApplication.processEvents()
    c.sync = True
    ov = c.overlays[0]
    w, h = ov.width(), ov.height()
    a, b = QPoint(w // 4, h // 4), QPoint(w // 2, h // 2)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(ov, b)
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, b)
    ov.set_tool("rect")
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, a + QPoint(10, 10))
    QTest.mouseMove(ov, b - QPoint(10, 10))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, b - QPoint(10, 10))
    t1 = time.perf_counter()
    c.finish("copy")
    t_copy = (time.perf_counter() - t1) * 1000
    png = win_clipboard.get_format(PNG)
    ocr_ok, shapes_ok = _selftest_recognition(tray)
    translate_ok = _selftest_translation()
    summary_ok = _selftest_summary()
    clip_ms, close_ms = getattr(c, "last_copy_ms", (t_copy, t_copy))
    line = (f"monitors={len(c.screen.monitors())} overlay_ms={t_overlay:.0f} copy_ms={t_copy:.0f} "
            f"(clipboard={clip_ms:.0f} +close windows={close_ms - clip_ms:.0f}) "
            f"png_bytes={len(png or b'')} ocr_korean={ocr_ok} shapes={shapes_ok} translate={translate_ok} "
            f"summary={'not installed' if summary_ok is None else summary_ok}")
    ok = (bool(png) and t_overlay < 150 and t_copy < 150 and ocr_ok and shapes_ok and translate_ok
          and summary_ok is not False)
    print(line)
    print("SELFTEST", "OK" if ok else "FAIL")
    logging.info("selftest %s %s", "OK" if ok else "FAIL", line)
    return 0 if ok else 1


def _selftest_translation() -> bool:
    """The bundled offline Korean->English pack loads and translates."""
    try:
        from ..core.ai_local import LocalTranslator
        out = LocalTranslator().translate("회의는 내일 오후 3시에 시작합니다.", "ko", "en")
        logging.info("selftest translate=%r", out)
        return "meeting" in out.lower() or "3" in out
    except Exception as e:  # noqa: BLE001 - reported as a failed check
        logging.error("selftest translate failed: %s", e)
        return False


def _selftest_summary():
    """Offline summary, when its model has been downloaded (None if not installed)."""
    from ..core.ai_local import LocalSummarizer
    s = LocalSummarizer()
    if not s.available():
        return None
    try:
        out = s.summarize("3분기 매출은 1,250억 원으로 12% 늘었다. 영업이익은 4% 줄었다.", "ko")
        s.unload()
        logging.info("selftest summary=%r", out)
        return "1,250" in out or "12" in out
    except Exception as e:  # noqa: BLE001
        logging.error("selftest summary failed: %s", e)
        return False


def _selftest_recognition(tray: TrayApp) -> tuple[bool, bool]:
    """Korean OCR and shape detection on images drawn here (proves models are bundled)."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPen
    from ..core.shapes import detect
    from .render import qimage_to_bgr

    img = QImage(900, 340, QImage.Format_RGB888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont("Malgun Gothic")
    f.setPixelSize(26)
    p.setFont(f)
    p.setPen(QColor("black"))
    p.drawText(20, 40, "요청 접수 검토 승인 010-1234-5678")
    p.drawText(20, 320, "Crème brûlée à côté, niño, Straße")
    p.setPen(QPen(QColor("#343A40"), 2))
    p.setBrush(QColor("#F1F3F5"))
    p.drawRect(QRect(40, 120, 180, 80))
    p.drawRect(QRect(420, 120, 180, 80))
    p.drawLine(222, 160, 400, 160)
    p.setBrush(QColor("#343A40"))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF([QPointF(418, 160), QPointF(400, 150), QPointF(400, 170)]))
    p.end()
    bgr = qimage_to_bgr(img)
    try:
        text = "".join(l.text for l in tray.ocr.recognize(bgr[:80])).replace(" ", "")
    except Exception as e:  # noqa: BLE001
        logging.error("selftest ocr failed: %s", e)
        text = ""
    try:
        latin = "".join(l.text for l in tray.ocr.recognize(bgr[280:])).replace(" ", "")
    except Exception as e:  # noqa: BLE001
        logging.error("selftest latin ocr failed: %s", e)
        latin = ""
    kinds = sorted(d.kind for d in detect(bgr[90:270]))
    logging.info("selftest ocr=%r latin=%r shapes=%s", text, latin, kinds)
    ok_text = "요청접수" in text and "010-1234-5678" in text and all(w in latin for w in ("Crème", "brûlée", "niño", "Straße"))
    return ok_text, kinds == ["arrow", "rect", "rect"]


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP)
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Malgun Gothic", 9))
    is_selftest = "--selftest" in argv

    name = f"{APP}-{os.environ.get('USERNAME', 'user')}"
    if not is_selftest:
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(200):
            sock.write(b"capture")
            sock.flush()
            sock.waitForBytesWritten(200)
            return 0  # already running: ask it to capture instead
        QLocalServer.removeServer(name)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.UserAccessOption)  # only this Windows user may connect
        server.setMaxPendingConnections(2)
        server.listen(name)

    tray = TrayApp(app, selftest=is_selftest)
    if is_selftest:
        return selftest(tray)

    def on_conn():
        s = server.nextPendingConnection()
        if s is None:
            return

        def read():
            handle_instance_message(s.read(64).data(), tray.on_hotkey)  # read at most 64 bytes
            s.disconnectFromServer()
        s.readyRead.connect(read)
    server.newConnection.connect(on_conn)
    logging.info("started %s", __version__)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
