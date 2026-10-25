"""Entry point: tray app, single instance, global hotkeys, OCR warm-up."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from datetime import datetime, timedelta

from PySide6.QtCore import QByteArray, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import __version__
from ..core import settings as settings_io
from ..core import update
from ..core.ocr import OcrEngine
from . import icons
from .controller import Controller
from .hotkeys import HotkeyWindow
from .services import RealClipboard, RealScreen
from .settings_dialog import SettingsDialog

APP = "CaptureTool"


def data_dir() -> Path:
    from .. import platform as pf
    if pf.is_mac():
        return Path.home() / "Library" / "Application Support" / APP
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP


def log_dir() -> Path:
    from .. import platform as pf
    if pf.is_mac():
        return Path.home() / "Library" / "Logs" / APP
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP


def fallback_dir() -> Path:
    return Path.home() / "Pictures" / "Captures"


def mac_permission_missing(which: str) -> str | None:
    """On the Mac: the message to show when the Screen Recording ('screen') or Accessibility
    ('accessibility') permission is not granted; None when granted or not on a Mac."""
    from .. import platform as pf
    if not pf.is_mac():
        return None
    from ..platform.mac import permissions
    try:
        ok = permissions.screen_recording() if which == "screen" else permissions.accessibility()
    except Exception:  # noqa: BLE001 - pyobjc missing in a developer run: do not block the app
        return None
    return None if ok else permissions.MESSAGES[which]


def check_mac_permissions(ask=None, open_settings=None) -> bool:
    """First start on a Mac: ask the system for Screen Recording once; still missing, explain and
    offer the settings pane. Returns True when capturing is possible. `ask(text) -> bool` and
    `open_settings()` are injected by tests."""
    from .. import platform as pf
    if not pf.is_mac():
        return True
    from ..platform.mac import permissions
    try:
        if permissions.screen_recording() or permissions.request_screen_recording():
            return True
    except Exception:  # noqa: BLE001
        return True
    text = permissions.MESSAGES["screen"]
    if ask is None:
        def ask(t):
            box = QMessageBox(QMessageBox.Warning, "캡처 도구", t)
            go = box.addButton("설정 열기", QMessageBox.AcceptRole)
            box.addButton("나중에", QMessageBox.RejectRole)
            box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            box.exec()
            return box.clickedButton() is go
    if ask(text):
        (open_settings or (lambda: permissions.open_settings("screen")))()
    return False


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
OPEN_PREFIX = b"open:"
MAX_MESSAGE = 2048
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


def open_message(path: str) -> bytes:
    """What a second launch with a picture (dropped on the shortcut, 보내기) sends."""
    return OPEN_PREFIX + str(Path(path).resolve()).encode("utf-8")


def _openable(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()


def handle_instance_message(data: bytes, trigger) -> bool:
    """Second launch asks the running instance to capture, or to open a picture file. Accept
    only the exact command, or an existing image file (nothing else is ever opened or run)."""
    data = bytes(data).strip()
    action = INSTANCE_COMMANDS.get(data)
    if action is None and data.startswith(OPEN_PREFIX) and len(data) <= MAX_MESSAGE:
        try:
            path = data[len(OPEN_PREFIX):].decode("utf-8")
        except UnicodeDecodeError:
            path = ""
        if path and _openable(path):
            action = "open:" + path
    if action is None:
        logging.warning("ignored unexpected single-instance message (%d bytes)", len(data))
        return False
    trigger(action)
    return True


class _Async(QObject):
    """A worker-thread job whose result (or exception) and progress come back on the UI thread."""
    done = Signal(object)
    progress = Signal(int, int)

    class _Run(QRunnable):
        def __init__(self, fn, sig):
            super().__init__()
            self.fn, self.sig = fn, sig

        def run(self):
            try:
                result = self.fn()
            except Exception as e:  # noqa: BLE001 - reported to the UI thread
                result = e
            self.sig.emit(result)

    def start(self, fn, wait: bool = False) -> None:
        if wait:                                       # tests: the whole thing on this thread
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001
                result = e
            self.done.emit(result)
            return
        QThreadPool.globalInstance().start(self._Run(fn, self.done))


class TrayApp:
    def __init__(self, app: QApplication, selftest: bool = False):
        self._toast = None
        self.available: update.Update | None = None  # a newer version found (tray menu offers to install it)
        self._jobs: list[_Async] = []
        self.app = app
        self.settings_path = data_dir() / "settings.json"
        self.settings, warnings = settings_io.load(self.settings_path)
        self.hk_window = HotkeyWindow()
        self.ocr = OcrEngine()
        self.ocr.warmup()
        self.tray = QSystemTrayIcon(app_icon())
        from .. import edition
        self.tray.setToolTip(f"{edition.title()} {__version__}")
        self.controller = Controller(RealScreen(), RealClipboard(self.hk_window.hwnd), self.ocr, self.settings,
                                     self.settings_path, fallback_dir(), notify=self.toast)
        self.hk_window.manager.triggered.connect(self.on_hotkey)
        from ..core.catalog import Catalog
        from .indexer import Indexer
        self.catalog = Catalog(data_dir() / "catalog.db")
        self.indexer = Indexer(self.catalog, self.ocr.recognize, self._save_folder, busy=self.controller.catalog_busy,
                               text_enabled=lambda: self.settings.catalog_text)
        self.controller.catalog, self.controller.indexer = self.catalog, self.indexer
        self.controller.shape_ready()                      # the shape pack, when installed (backlog at the rescan)
        self.controller.prewarm()
        app.screenAdded.connect(lambda *_: self.controller.prewarm())
        self._build_menu()
        self.tray.show()
        self.tray.activated.connect(lambda reason: self.on_hotkey("capture")
                                    if reason == QSystemTrayIcon.Trigger else None)
        if not selftest:
            check_mac_permissions()
        for w in warnings:
            self.toast(w)
        if not selftest:
            self.apply_hotkeys(first_run=not self.settings_path.exists())
            # the beginner's guide pops up once (first start, or the first start after updating)
            QTimer.singleShot(1500, self.controller.show_guide_first_time)
            QTimer.singleShot(20_000, self._auto_check_update)      # once a day, well after start-up
            if self.settings.catalog_enabled:
                QTimer.singleShot(8_000, self.indexer.rescan)         # the save folder's backlog, when idle

    def _save_folder(self) -> str | None:
        from ..core.naming import SaveDirError, resolve_save_dir
        try:
            return str(resolve_save_dir(self.settings.save_dir, fallback_dir())[0])
        except SaveDirError:
            return None

    # --- ui ------------------------------------------------------------------------
    def toast(self, msg: str) -> None:
        from .toast import toast_ms
        # on-screen message (tray balloons are often hidden by Windows); deferred so a copy
        # is never delayed by painting it
        def show():
            if self._toast is None:
                from .toast import Toast
                self._toast = Toast()
            c = getattr(self, "controller", None)
            self._toast.show_message(msg, toast_ms(msg), avoid=c.busy_rects() if c is not None else ())
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
        from .. import edition
        if not edition.is_work():                    # the work edition is always at work
            from PySide6.QtGui import QActionGroup
            from ..core.bar_layout import PLACE_NAMES, WORKPLACES
            place = m.addMenu("지금 장소 (버튼 막대 배치)")
            grp = QActionGroup(place)
            for key in WORKPLACES:
                a = QAction(f"{PLACE_NAMES[key]}에서", place)
                a.setCheckable(True)
                a.setChecked(self.controller.workplace() == key)
                a.triggered.connect(lambda _=False, k=key: (self.controller.set_workplace(k), self._build_menu()))
                grp.addAction(a)
                place.addAction(a)

        def sync_auto_save():                    # the capture's 자동저장 button may have changed it
            auto.blockSignals(True)
            auto.setChecked(self.controller.settings.auto_save)
            auto.blockSignals(False)
        m.aboutToShow.connect(sync_auto_save)
        a = QAction("이미지 열기… (캡처처럼 표·텍스트·PPT 사용)", m)
        a.triggered.connect(self.open_image)
        m.addAction(a)
        key = hk.get("search") or ""
        a = QAction("캡처 찾기… (저장한 캡처를 글자·태그·모양으로)" + (f"\t{key}" if key else ""), m)
        a.triggered.connect(lambda: self.controller.open_search())
        m.addAction(a)
        a = QAction("사용 설명서 (따라하기)", m)
        a.triggered.connect(lambda: self.controller.show_guide())
        m.addAction(a)
        a = QAction("고정한 캡처 관리…", m)
        a.triggered.connect(self.controller.show_pin_manager)
        m.addAction(a)
        a = QAction("고정 이미지 모두 닫기", m)
        a.triggered.connect(self.controller.close_all_pins)
        m.addAction(a)
        if self.available is not None:
            a = QAction(f"새 버전 {self.available.version} 설치…", m)
            a.triggered.connect(lambda: self.install_update())
            m.addAction(a)
        a = QAction("업데이트 확인…", m)
        a.triggered.connect(lambda: self.check_update(manual=True))
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

    def open_image(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        start = self.settings.save_dir or str(Path.home() / "Pictures")
        path, _ = QFileDialog.getOpenFileName(None, "이미지 열기", start,
                                              "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        if path:
            self.controller.open_image_file(path)

    def _set_auto_save(self, on: bool) -> None:
        self.settings.auto_save = on
        try:
            settings_io.save(self.settings, self.settings_path)
        except OSError:
            pass
        self.toast("캡처 자동 저장을 켰습니다. 캡처할 때마다 저장 폴더에 저장합니다." if on
                   else "캡처 자동 저장을 껐습니다.")

    def on_hotkey(self, action: str) -> None:
        if action.startswith("open:"):                  # a picture sent from a second launch
            self.controller.open_image_file(action[len("open:"):])
            return
        if action == "scroll":
            missing = mac_permission_missing("accessibility")
            if missing:
                self.toast(missing)
                return
        if action == "search":
            self.controller.open_search()
            return
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
        from .. import platform as pf
        try:
            pf.backend().startup.set_enabled(self.settings.launch_at_startup, sys.executable)
        except OSError as e:
            logging.warning("startup registration failed: %s", e)

    def open_settings(self) -> None:
        if getattr(sys, "frozen", False):  # show the real state (the installer may have set it)
            from .. import platform as pf
            self.settings.launch_at_startup = pf.backend().startup.is_enabled()
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
            from .. import platform as pf
            pf.backend().shell.open_path(d)                   # the person's own folder in Explorer / Finder
        except (SaveDirError, OSError) as e:
            self.toast(str(e))

    # --- updates ----------------------------------------------------------------------------------
    def update_due(self) -> bool:
        """Time for the daily look? (Never when switched off in the settings.)"""
        if not getattr(self.settings, "update_check", True):
            return False
        try:
            last = datetime.fromisoformat(self.settings.update_last)
        except (TypeError, ValueError):
            return True
        return datetime.now() - last >= timedelta(hours=update.CHECK_EVERY_HOURS)

    def _auto_check_update(self) -> None:
        if self.update_due():
            self.check_update(manual=False)

    def _job(self) -> _Async:
        job = _Async()
        self._jobs.append(job)
        job.done.connect(lambda _=None, j=job: self._jobs.remove(j) if j in self._jobs else None)
        return job

    def _save_settings(self) -> None:
        try:
            settings_io.save(self.settings, self.settings_path)
        except OSError:
            pass

    def check_update(self, manual: bool = False, wait: bool = False) -> None:
        """Look for a newer version (GitHub release of this edition, or the folder in the
        settings) off the UI thread; found: the tray menu gains "새 버전 … 설치"."""
        from .. import edition
        current, ed, source = __version__, update.channel(edition.current()), getattr(self.settings, "update_source", "")
        job = self._job()

        def done(result):
            self.settings.update_last = datetime.now().isoformat(timespec="seconds")
            self._save_settings()
            if isinstance(result, Exception):
                logging.warning("update check failed: %s", result)
                if manual:
                    self.toast(str(result) if isinstance(result, update.UpdateError)
                               else "업데이트 확인 실패 — 인터넷 연결을 확인하세요.")
                return
            self.available = result
            self._build_menu()
            if result is None:
                if manual:
                    self.toast(f"최신 버전입니다 ({__version__}).")
            else:
                self.toast(f"새 버전 {result.version}이 있습니다 — 트레이 메뉴의 '새 버전 {result.version} 설치'로 받아서 설치합니다.")
        job.done.connect(done)
        job.start(lambda: update.check(current, ed, source), wait)

    def _confirm_update(self, u: update.Update) -> bool:
        notes = (u.notes or "").strip()
        if len(notes) > 700:
            notes = notes[:700] + "…"
        box = QMessageBox(QMessageBox.Question, "새 버전 설치",
                          f"캡처 도구 {u.version}을 받아서 설치할까요? (지금 {__version__})\n\n"
                          "받는 동안 계속 쓸 수 있고, 설치할 때 잠깐 종료됐다가 새 버전으로 다시 실행됩니다.",
                          QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("받아서 설치")
        box.button(QMessageBox.No).setText("나중에")
        if notes:
            box.setDetailedText(notes)
        box.setWindowIcon(app_icon())
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        return box.exec() == QMessageBox.Yes

    def install_update(self, wait: bool = False) -> None:
        """Download the offered installer (checked against its .sha256), run it silently, quit;
        the installer restarts the app."""
        u = self.available
        if u is None or not self._confirm_update(u):
            return
        self.toast(f"새 버전 {u.version} 받는 중… (받는 동안 계속 쓸 수 있습니다)")
        into = data_dir() / "updates"
        job = self._job()
        shown = {"q": 0}

        def on_progress(done_bytes: int, total: int) -> None:
            if total and done_bytes * 4 // total > shown["q"]:
                shown["q"] = done_bytes * 4 // total
                if shown["q"] < 4:
                    self.toast(f"새 버전 받는 중… {done_bytes * 100 // total}%")
        job.progress.connect(on_progress)

        def done(result):
            if isinstance(result, Exception):
                logging.warning("update download failed: %s", result)
                self.toast(str(result) if isinstance(result, update.UpdateError) else "업데이트 파일을 받지 못했습니다.")
                return
            if update.launch_installer(result):
                self.toast("설치를 시작합니다. 잠시 뒤 새 버전으로 다시 실행됩니다.")
                if wait:
                    self.quit()
                else:
                    QTimer.singleShot(400, self.quit)
            else:
                self.toast("새 버전 디스크 이미지를 열었습니다. CaptureTool을 응용 프로그램 폴더로 끌어 넣고 다시 실행하세요.")
        job.done.connect(done)
        job.start(lambda: update.download(u, into, progress=job.progress.emit), wait)

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
    from .. import platform as pf

    c = tray.controller
    tray.ocr._load()  # in real use the warm-up has long finished before the first hotkey
    tray.ocr._load_secondary()
    c.prewarm()  # the app does this at start-up too (see TrayApp): first grab and overlay windows are ready
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
    png = pf.backend().clipboard.get_format(PNG)
    ocr_ok, shapes_ok = _selftest_recognition(tray)
    translate_ok = _selftest_translation()
    summary_ok = _selftest_summary()
    clip_ms, close_ms = getattr(c, "last_copy_ms", (t_copy, t_copy))
    line = (f"monitors={len(c.screen.monitors())} overlay_ms={t_overlay:.0f} copy_ms={t_copy:.0f} "
            f"(clipboard={clip_ms:.0f} +close windows={close_ms - clip_ms:.0f}) "
            f"png_bytes={len(png or b'')} ocr_korean={ocr_ok} shapes={shapes_ok} translate={translate_ok} "
            f"summary={'not installed' if summary_ok is None else summary_ok}")
    # 오버레이 예산: Windows 150 ms. 맥은 워밍업 뒤에도 실제 화면에서 165~180 ms(화면 캡처 10~20 ms,
    # 창 목록 1~3 ms, 나머지는 전체 화면 창 띄우기) - 250 ms 로 둔다. 화면이 잠들어 있으면 캡처가 1초씩 걸린다.
    overlay_budget = 250 if pf.is_mac() else 150
    ok = (bool(png) and t_overlay < overlay_budget and t_copy < 150 and ocr_ok and shapes_ok and translate_ok
          and summary_ok is not False)
    print(line)
    if pf.is_mac():
        from Quartz import CGSessionCopyCurrentDictionary
        if (CGSessionCopyCurrentDictionary() or {}).get("CGSSessionScreenIsLocked"):
            print("note: the screen is locked - captures are black and slow; unlock the Mac and run again")
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
    files = [a for a in argv[1:] if not a.startswith("--") and _openable(a)]   # dropped on the shortcut / 보내기

    name = f"{APP}-{os.environ.get('USERNAME', 'user')}"
    if not is_selftest:
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(200):
            sock.write(open_message(files[0]) if files else b"capture")
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
            handle_instance_message(s.read(MAX_MESSAGE + 1).data(), tray.on_hotkey)  # bounded read
            s.disconnectFromServer()
        s.readyRead.connect(read)
    server.newConnection.connect(on_conn)
    if files:
        QTimer.singleShot(800, lambda: tray.controller.open_image_file(files[0]))
    logging.info("started %s", __version__)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
