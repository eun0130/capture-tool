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


def setup_logging() -> None:
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=d / "capture.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")


class TrayApp:
    def __init__(self, app: QApplication, selftest: bool = False):
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
            self._sync_startup()

    # --- ui ------------------------------------------------------------------------
    def toast(self, msg: str) -> None:
        # deferred: showing a Windows notification takes ~80 ms, never block a copy on it
        QTimer.singleShot(0, lambda: self.tray.showMessage("캡처 도구", msg, QSystemTrayIcon.Information, 2500))

    def _build_menu(self) -> None:
        m = QMenu()
        hk = self.settings.hotkeys
        for label, action in [("캡처 + 그리기", "capture"), ("텍스트 바로 복사", "ocr"),
                              ("도형 바로 복사 (PPT)", "shapes"), ("전체 화면 캡처", "fullscreen")]:
            key = hk.get(action) or ""
            a = QAction(f"{label}\t{key}" if key else label, m)
            a.triggered.connect(lambda _=False, x=action: QTimer.singleShot(250, lambda: self.on_hotkey(x)))
            m.addAction(a)
        m.addSeparator()
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

    def on_hotkey(self, action: str) -> None:
        mode = {"capture": "draw", "ocr": "text", "shapes": "shapes", "fullscreen": "fullscreen"}[action]
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
    tray.ocr._load()
    print(f"monitors={len(c.screen.monitors())} overlay_ms={t_overlay:.0f} copy_ms={t_copy:.0f} "
          f"png_bytes={len(png or b'')} ocr_ready={tray.ocr.ready}")
    ok = bool(png) and t_overlay < 150 and t_copy < 150
    print("SELFTEST", "OK" if ok else "FAIL")
    return 0 if ok else 1


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
        server.listen(name)

    tray = TrayApp(app, selftest=is_selftest)
    if is_selftest:
        return selftest(tray)

    def on_conn():
        s = server.nextPendingConnection()
        s.readyRead.connect(lambda: tray.on_hotkey("capture"))
    server.newConnection.connect(on_conn)
    logging.info("started %s", __version__)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
