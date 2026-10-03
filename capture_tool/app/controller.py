"""Glue: hotkey -> overlays (cursor monitor first) -> finish actions (copy/save/pin/text/shapes)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor

from ..core import settings as settings_io
from ..core.clipboard_payload import (HTML, UNICODE, cf_html, dib_from_bgr, image_payload, png_with_dpi, table_payload,
                                      shapes_payload, text_payload)
from ..core.clip import flatten, mask_outside
from ..core.color import pixel_color, push_recent
from ..core.convert import annotations_to_drawing
from ..core.drawingml import gvml_package, svg
from ..core.geometry import Rect, clamp_rect, nudge, order_cursor_first, virtual_bounds
from ..core.naming import SaveDirError, render, resolve_save_dir, unique_path
from ..core.ocr import OcrUnavailable, full_text, select_text
from ..core.scroll_session import ScrollCapture, looks_blocked
from ..core.session import CaptureSession, State
from ..core.shapes import detect, recognize_layout, screen_tables, split_doubtful, to_drawing
from ..core.table import detect_grid, grid_from_cells, table_is_plausible
from ..core.box_table import find_box_table
from ..core.table_capture import CapturedTable, find_table
from ..core.text_table import find_text_table
from ..platform.powerpoint import (ClipboardShapes, Picture, PowerPointBusy, PowerPointUnavailable, TableItem,
                                   TextItem, clip_text, table_fits)
from .overlay import OverlayWindow
from .pin import PinWindow
from .render import compose
from .text_panel import TextPanel, mask

READ_AHEAD_MAX_PX = 8_000_000     # bigger areas (a whole 4K screen) are read only when asked
READ_AHEAD_WAIT_S = 30.0

log = logging.getLogger("capture_tool")


def _protect(text: str) -> str:
    from ..core.contacts import SecretError
    from ..platform import secret
    try:
        return secret.protect(text)
    except secret.SecretError as e:
        raise SecretError(str(e)) from e


def _unprotect(blob: str) -> str:
    from ..platform import secret
    return secret.unprotect(blob)


def _open_url(url: str) -> bool:
    """The person's default browser (web mail) or mail app (mailto:)."""
    if not url.startswith(("https://", "mailto:")):
        return False
    import os
    try:
        os.startfile(url)
        return True
    except OSError:
        return False


def _confirm(text: str) -> bool:
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, "캡처 도구", text, QMessageBox.Yes | QMessageBox.No)
    box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
    return box.exec() == QMessageBox.Yes


def _open_folder(path) -> None:
    import os
    try:
        os.startfile(str(path))
    except OSError:
        pass


def _reveal_file(path) -> None:
    import subprocess
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
    except OSError:
        pass


class _Job(QRunnable):
    def __init__(self, fn, done):
        super().__init__()
        self.fn, self.done = fn, done

    def run(self):
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 - reported back to the UI thread
            result = e
        self.done.emit(result)


class Controller(QObject):
    _job_done = Signal(object)
    _kakao_done = Signal(object)
    _search_done = Signal(object)
    _ppt_done = Signal(object)
    _text_ready = Signal(object)
    _ai_done = Signal(object)
    _ai_partial = Signal(str)
    _ai_progress = Signal(object)
    _ai_dl = Signal(object)
    _share_done = Signal(object)
    _ai_preloaded = Signal(object)

    def __init__(self, screen, clipboard, ocr, settings, settings_path, fallback_dir, sync=False, notify=None):
        super().__init__()
        self.screen, self.clipboard, self.ocr = screen, clipboard, ocr
        self.settings = settings
        self.settings_path = Path(settings_path)
        self.fallback_dir = Path(fallback_dir)
        self.sync = sync
        self._notify = notify
        self.session = CaptureSession()
        self.overlays: list[OverlayWindow] = []
        self._pool: dict[str, OverlayWindow] = {}
        self.active_overlay: OverlayWindow | None = None
        self.pins: list[PinWindow] = []
        self.pin_manager = None
        self.guide_window = None
        self.confirm = _confirm
        self.text_panel: TextPanel | None = None
        self.messages: list[str] = []
        self.mode = "draw"
        self.now = datetime.now
        self._pending = None
        self._job_done.connect(self._on_job_done)
        self._ppt_done.connect(self._on_ppt_done)
        self._text_ready.connect(self._on_text_ready)
        self._ai_done.connect(self._ai_finished)
        self._ai_partial.connect(lambda t: self.ai_window and self.ai_window.set_partial(t))
        self._ai_progress.connect(lambda p: self.ai_window and self.ai_window.show_progress(*p))
        self._ai_dl.connect(lambda r: self._ai_dl_done(r))
        self._share_done.connect(lambda r: self._share_done_cb(r))
        self._ai_idle_timer = QTimer(self)
        self._ai_idle_timer.setSingleShot(True)
        self._ai_idle_timer.setInterval(90_000)      # models leave memory after 90 s unused
        self._ai_idle_timer.timeout.connect(self.ai_idle)
        self._text_ctx = None
        self.last_document = None
        self._text_lines: list = []
        self._text_grid = None
        self._last_text = ""        # what the text mode last put on the clipboard
        self._last_raw = ""         # the same text before masking (for translate / summary)
        self._ai = None             # AiService, created on first use
        self.ai_window = None
        self.ai_offline_once_used = False
        self._ai_ctx = None
        self.ask_yes_no = None      # tests replace these dialogs
        self.ask_consent = None
        self.download_packs = self._download_packs
        self.bring_to_front = self._bring_ppt_to_front
        self.scrolling = False
        self._scroll_stop = False
        self.scroll_indicator = None
        self.scroll_result = None
        self.result_window = None          # whole-window capture result
        self.editor = None                  # edit window for captures bigger than a screen
        self._editor_path = None            # file it was auto-saved to when it opened
        self.tip_active = False
        self._acted = False                 # the user did something with this capture (for auto-save on Esc)
        self._taken_path = None             # file the current capture was saved to (auto-save / link)
        self.ask_share_consent = None       # tests replace the dialog
        self.uploader = None                # tests replace the upload
        self.scroll_limits: dict = {}   # tests: max_height / max_pixels / max_steps
        self.ask_save_path = self._ask_save_path_dialog
        # 메일: address book (per Windows user, encrypted), compose page, paste helper
        self.contacts_path = self.settings_path.parent / "contacts.dat"
        self.protect, self.unprotect = _protect, _unprotect
        self.open_url = _open_url
        self.reveal_file = _reveal_file
        self.open_folder = _open_folder
        self.ask_mail = None                # tests replace the picker
        self.ask_table_preview = None       # tests replace the preview dialog
        self.ask_table_options = None       # tests replace the 표 options dialog
        self.mail_helper = None
        self._book = None
        from ..platform.powerpoint import PowerPointSender
        from ..platform.security_software import detect_drm
        self.powerpoint = PowerPointSender()
        from ..platform.kakao import KakaoSender
        self.kakao = KakaoSender()
        self._kakao_done.connect(self.notify)
        self._search_done.connect(self._open_search)
        self.drm = detect_drm()

    # --- helpers -----------------------------------------------------------------
    def _screen(self, name: str, *args, default=None):
        """Optional screen services (scrolling, window checks); absent in simple fakes."""
        fn = getattr(self.screen, name, None)
        if fn is None:
            return default
        try:
            return fn(*args)
        except OSError:
            return default

    def notify(self, msg: str) -> None:
        self.messages.append(msg)
        log.info(msg)
        if self._notify:
            self._notify(msg)

    def _set_clipboard(self, payload: dict) -> bool:
        try:
            self.clipboard.set(payload)
            return True
        except OSError as e:
            self.notify(f"클립보드에 복사하지 못했습니다: {e}")
            return False

    # --- start -------------------------------------------------------------------
    def start_capture(self, mode: str = "draw") -> bool:
        t0 = time.perf_counter()
        if self.session.state is not State.IDLE:
            if self.editor is not None:
                self.editor.raise_()
                self.editor.activateWindow()
                self.notify("캡처 편집 창이 열려 있습니다. 편집 창에서 복사·저장하거나 닫은 뒤 다시 캡처하세요.")
            return False
        mons = self.screen.monitors()
        if not mons:
            self.notify("모니터를 찾지 못했습니다.")
            return False
        ordered = order_cursor_first(mons, self.screen.cursor_pos())
        if mode == "fullscreen":
            img = np.ascontiguousarray(self.screen.grab(ordered[0].rect)[:, :, :3])
            self._copy_image(img, 96 * ordered[0].scale)
            if self.settings.auto_save:
                self._save(img)
            return True
        self._acted, self._taken_path = False, None
        self.tip_active = self.settings.tip_count < 3
        if self.tip_active:
            self.settings.tip_count += 1
            self._persist()
        wins = self.screen.windows()
        self.session.hotkey(virtual_bounds(mons))
        self.mode = mode
        self._open_overlay(ordered[0], wins, focus=True)
        log.info("overlay shown in %.0f ms", (time.perf_counter() - t0) * 1000)
        rest = ordered[1:]
        if rest:
            if self.sync:
                for m in rest:
                    self._open_overlay(m, wins)
            else:
                QTimer.singleShot(0, lambda: [self._open_overlay(m, wins) for m in rest
                                              if self.session.state is not State.IDLE])
        return True

    def _overlay_for(self, monitor, img, wins) -> OverlayWindow:
        ov = self._pool.get(monitor.name)
        if ov is None:
            ov = OverlayWindow(self, monitor, img, wins)
            self._pool[monitor.name] = ov
        else:
            ov.reset(monitor, img, wins)
        return ov

    def prewarm(self) -> None:
        """Create (hidden) overlay windows for every monitor ahead of the first hotkey."""
        import numpy as np
        for m in self.screen.monitors():
            ov = self._overlay_for(m, np.zeros((8, 8, 3), np.uint8), [])
            ov.place()
            ov.winId()  # force native window creation now

    def _open_overlay(self, monitor, wins, focus=False) -> None:
        img = self.screen.grab(monitor.rect)
        if focus and looks_blocked(img):
            self.notify("화면 캡처가 막혔습니다: 화면 전체가 한 가지 색으로만 찍힙니다. 보안 프로그램이나 "
                        "보호된 영상(DRM)이 캡처를 막는 중일 수 있습니다. 그 창을 닫거나 잠시 뒤 다시 해 보세요.")
        ov = self._overlay_for(monitor, img, wins)
        ov.place()
        ov.show()
        ov.raise_()
        if focus:
            if self.sync:
                self._focus(ov)
            else:  # frozen frame is on screen first; keyboard focus a moment later
                QTimer.singleShot(0, lambda: self._focus(ov))
        self.overlays.append(ov)

    @staticmethod
    def _focus(ov) -> None:
        if ov.isVisible():
            ov.activateWindow()
            ov.setFocus()

    def close_overlays(self) -> None:
        for ov in self.overlays:
            ov.hide()
            ov.release()
        self.overlays = []
        self.active_overlay = None
        if self.editor is not None:
            ed, self.editor = self.editor, None
            ed.close_from_controller()
            ed.deleteLater()

    def close_all(self) -> None:
        if self.ai_window is not None:
            self.ai_window.close()
        if self.editor is not None:
            self.close_overlays()
        self.close_overlays()
        for ov in self._pool.values():
            ov.deleteLater()
        self._pool.clear()
        self.close_pins()
        if self.text_panel:
            self.text_panel.close()
        for w in (self.pin_manager, self.mail_helper, self.guide_window):
            if w is not None:
                w.close()

    # --- selection ---------------------------------------------------------------
    def _clamp_point(self, p, mon):
        r = mon.rect
        return (min(max(p[0], r.x), r.right), min(max(p[1], r.y), r.bottom))

    def on_drag(self, p1, p2, ov) -> None:
        self.session.drag(self._clamp_point(p1, ov.monitor), self._clamp_point(p2, ov.monitor))
        self._after_select(ov)

    def on_select_rect(self, rect: Rect, ov, window=None) -> None:
        if window is not None and clamp_rect(rect, ov.monitor.rect) != rect:
            self._capture_whole_window(window, ov)       # spans monitors / goes off-screen
            return
        r = clamp_rect(rect, ov.monitor.rect)
        if r is not None:
            self.session.select(r)
            self._after_select(ov)

    def _after_select(self, ov) -> None:
        if self.session.state is not State.EDITING:
            return
        self._auto_copied, self._auto_sig = False, None      # a new area: copy it afresh
        self.active_overlay = ov
        for o in self.overlays:
            o.update()
        self._warn_protected(ov, self.session.selection)
        if self.mode == "scroll":
            self.on_toolbar_action("scroll")
            return
        if self.mode in ("text", "shapes"):
            self.on_toolbar_action(self.mode)
            return
        ov.show_toolbar()
        ov.setFocus()
        self.auto_copy_soon(now=True)
        self._start_read_ahead(ov)

    # --- read ahead: the text is ready by the time a button is pressed ------------------------
    read_ahead_mode = None              # "thread" | "inline" | "off"; None: thread unless a sync (test) controller

    @staticmethod
    def _read_key(raw):
        import hashlib
        return raw.shape, hashlib.blake2b(np.ascontiguousarray(raw).tobytes(), digest_size=16).digest()

    def _start_read_ahead(self, ov) -> None:
        mode = self.read_ahead_mode or ("off" if self.sync else "thread")
        self._ahead = None
        if mode == "off" or not getattr(self.settings, "read_ahead", True):
            return
        sel, doc = self.session.selection, self.session.document
        if sel is None or sel.w * sel.h * ov.scale * ov.scale > READ_AHEAD_MAX_PX:
            return
        raw = mask_outside(ov.crop(sel), doc.clip if doc else None)
        slot = {"key": self._read_key(raw), "done": threading.Event(), "result": None}
        self._ahead = slot

        def job():
            try:
                slot["result"] = self.ocr.recognize(raw)
            except Exception as e:  # noqa: BLE001 - kept and raised where the text is used
                slot["result"] = e
            slot["done"].set()

        if mode == "inline":
            job()
        else:
            threading.Thread(target=job, name="read-ahead", daemon=True).start()

    def _read(self, raw):
        """OCR of `raw`, reusing the read-ahead of the same pixels (waiting for it if running)."""
        slot = getattr(self, "_ahead", None)
        if slot is not None and slot["key"] == self._read_key(raw) and slot["done"].wait(READ_AHEAD_WAIT_S):
            res = slot["result"]
            if isinstance(res, Exception):
                raise res
            return list(res)
        return self.ocr.recognize(raw)

    # --- live copy: Ctrl+V works without Ctrl+C -----------------------------------------
    def auto_copy_soon(self, now: bool = False) -> None:
        """Keep the clipboard equal to what the capture shows while editing (debounced:
        encoding a 4K picture takes ~50 ms, so a burst of edits copies once)."""
        if not self.settings.auto_copy or self.session.state is not State.EDITING or self.mode != "draw":
            return
        if now or self.sync:
            self._auto_copy()
            return
        if not hasattr(self, "_auto_timer"):
            self._auto_timer = QTimer()
            self._auto_timer.setSingleShot(True)
            self._auto_timer.setInterval(300)
            self._auto_timer.timeout.connect(self._auto_copy)
        self._auto_timer.start()

    def flush_auto_copy(self) -> None:
        timer = getattr(self, "_auto_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
            self._auto_copy()

    def _auto_copy(self) -> None:
        ov = self.active_overlay
        sel = self.session.selection
        if ov is None or sel is None or self.session.state is not State.EDITING:
            return
        doc = self.session.document
        sig = ((sel.x, sel.y, sel.w, sel.h), repr(doc.shapes) if doc else "")
        if sig == getattr(self, "_auto_sig", None) and getattr(self, "_auto_copied", False):
            return                                        # repaint without a change
        self._auto_sig = sig
        img = compose(ov.crop(sel), doc)
        payload = self._image_payload(img, 96 * ov.scale)
        if payload and self._set_clipboard(payload) and not getattr(self, "_auto_copied", False):
            self._auto_copied = True
            self.notify("클립보드에 복사했습니다 — 바로 Ctrl+V 하면 됩니다. 그림을 그리면 복사본도 바뀝니다.")

    def _warn_protected(self, ov, sel) -> None:
        """Windows that asked to be hidden from screenshots (banking, DRM video, secure apps)
        come out black. That is their owner's security choice; it is explained, not bypassed."""
        for w in getattr(ov, "windows", []):
            if clamp_rect(w.rect, sel) is None:
                continue
            if self._screen("display_affinity", w.hwnd, default=0):
                self.notify(f"'{w.title or '이름 없는 창'}' 창은 캡처 보호가 켜져 있어 검게 찍힙니다. "
                            "그 프로그램이 보안을 위해 막아 둔 것이라 캡처 도구로는 풀 수 없습니다.")

    def nudge(self, dx: int, dy: int) -> None:
        ov = self.active_overlay
        if ov is None or self.session.selection is None:
            return
        self.session.resize(nudge(self.session.selection, dx, dy, ov.monitor.rect))
        ov.show_toolbar()
        ov.update()
        self.auto_copy_soon()

    def cancel(self) -> None:
        ov, sel, doc = self.active_overlay, self.session.selection, self.session.document
        if (self.settings.auto_save and self._acted and ov is not None and sel is not None
                and self.session.state is State.EDITING):
            self._autosave(ov.crop(sel), doc)            # used (e.g. text copied), then closed
        self.session.key("Escape")
        self.close_overlays()

    def copy_color(self, ov, local_pt) -> None:
        x, y = ov.to_phys(local_pt)
        c = pixel_color(ov.image, x - ov.monitor.rect.x, y - ov.monitor.rect.y)
        if c and self._set_clipboard({UNICODE: c}):
            self.notify(f"색상 {c} 를 복사했습니다.")

    # --- finishing ---------------------------------------------------------------
    def on_toolbar_action(self, name: str) -> None:
        if name == "help":
            self.show_guide()
            return
        if name in ("autosave", "more", "open_folder") or name.startswith("tableopt:"):
            if name.startswith("tableopt:"):
                self._table_option(name)
                return
            self._bar_action(name)
            return
        if name not in ("undo", "redo"):
            self._acted = True
        if name in ("link_file", "link_web"):
            self._link_from_capture(name)
        elif name.startswith("kakao"):
            self._send_to_kakao(name)
        elif name == "mail":
            self._send_mail()
        elif name in ("pin_stack", "pin_other"):
            self._pin_from_capture(name)
        elif name == "pin_manager":
            self.show_pin_manager()
        elif name.startswith(("search_img:", "search_text:")):
            self._web_search(name)
        elif name in ("copy", "save", "save_as", "pin"):
            self.finish(name)
        elif name == "cancel":
            self.cancel()
        elif name in ("undo", "redo") and self.session.document is not None:
            getattr(self.session.document, name)()
            if self.active_overlay:
                self.active_overlay.update()
        elif name == "text" and self.mode != "text":
            self._start_text_mode()
        elif name == "ppt":
            self._send_capture_to_ppt()
        elif name == "scroll":
            self._start_scroll()
        elif name == "ppt_shapes":
            self._run_recognition("ppt")
        elif name in ("text", "shapes", "table", "table_preview"):
            self._run_recognition(name)
        elif name.startswith("tableopt:"):
            self._table_option(name)

    # --- scroll capture ----------------------------------------------------------------------
    def _scroll_target(self, ov, sel):
        """(area, scroll to top first?, description). A whole browser window picked while
        selecting means "the whole page": only the page area, from the top."""
        for w in getattr(ov, "windows", []):
            r = w.rect
            if max(abs(r.x - sel.x), abs(r.y - sel.y), abs(r.right - sel.right), abs(r.bottom - sel.bottom)) > 12:
                continue
            if self._screen("is_browser", w.hwnd, default=False):
                vp = self._screen("browser_viewport", w.hwnd)
                vp = clamp_rect(vp, ov.monitor.rect) if vp else None
                # without a known page view (e.g. Firefox) the whole window works too: tabs and
                # the address bar don't move, so they are kept once at the top like a sticky header
                return (vp or sel), True, "브라우저 페이지 전체"
            break
        return sel, False, "선택한 영역"

    def _start_scroll(self) -> None:
        if self.session.state is not State.EDITING:
            return
        if self.scrolling:
            self.notify("스크롤 캡처가 이미 진행 중입니다.")
            return
        ov, sel = self.active_overlay, self.session.selection
        rect, to_top, what = self._scroll_target(ov, sel)
        drew = bool(self.session.document and self.session.document.shapes)
        dpi = 96 * ov.scale
        local = ov.local_rect(rect)
        anchor = (ov.mapToGlobal(local.bottomLeft().toPoint()), ov.mapToGlobal(local.topLeft().toPoint()),
                  ov.geometry())
        self._take(autosave=False)
        if drew:
            self.notify("스크롤 캡처에는 그린 내용이 들어가지 않습니다. 결과를 고정하거나 저장한 뒤 다시 캡처해서 그려 주세요.")
        self._run_scroll(rect, to_top, what, dpi, anchor)

    def _run_scroll(self, rect, to_top, what, dpi, anchor) -> None:
        from .scroll_ui import ScrollIndicator
        self.scrolling, self._scroll_stop = True, False
        self._screen("esc_pressed")                       # forget an Esc pressed before this
        cursor = self.screen.cursor_pos()
        cx, cy = rect.x + rect.w // 2, rect.y + rect.h // 2
        ind = ScrollIndicator()
        below, above, screen_geo = anchor
        ind.adjustSize()
        pos = below + QPoint(0, 8)
        if pos.y() + ind.height() > screen_geo.bottom():
            pos = above - QPoint(0, ind.height() + 8)
        if pos.y() < screen_geo.top():
            pos = above + QPoint(8, 8)
        ind.move(pos)
        ind.show()
        self._screen("exclude_from_capture", int(ind.winId()))
        ind.stopRequested.connect(lambda: setattr(self, "_scroll_stop", True))
        self.scroll_indicator = ind

        def stop() -> bool:
            return self._scroll_stop or bool(self._screen("esc_pressed", default=False))

        owner = {}

        def visible() -> bool:
            """The window under the area is the one we started with (nothing popped up over it)."""
            root = self._screen("root_window_at", cx, cy)
            if root is None:
                return True
            return owner.setdefault("hwnd", root) == root

        sc = ScrollCapture(grab=lambda: self.screen.grab(rect), wheel=lambda n: self.screen.wheel(cx, cy, n),
                           to_top=to_top, stop_requested=stop, progress=ind.show_progress, still_visible=visible,
                           **self.scroll_limits)
        gen = sc.run()

        def finish(error=None) -> None:
            self.scrolling = False
            ind.close()
            self.scroll_indicator = None
            self._screen("set_cursor", *cursor)
            self._finish_scroll(sc, what, dpi, error, below)

        if self.sync:
            for _ in gen:
                pass
            finish()
            return

        def tick() -> None:
            try:
                ms = next(gen)
            except StopIteration:
                finish()
                return
            except Exception as e:  # noqa: BLE001 - keep what was captured, report
                log.exception("scroll capture failed")
                finish(e)
                return
            QTimer.singleShot(ms, tick)

        QTimer.singleShot(150, tick)   # let the overlays disappear from the screen first

    def _finish_scroll(self, sc, what, dpi, error, pos) -> None:
        img = sc.result()
        h, w = img.shape[:2]
        payload = self._image_payload(img, dpi)
        if payload:
            self._set_clipboard(payload)
        if error is not None:
            self.notify(f"스크롤 캡처 중 오류가 났습니다({error}). 그때까지 찍은 {w}×{h}px를 복사했습니다.")
        elif sc.reason == "noscroll":
            self.notify("스크롤되지 않아 보이는 부분만 복사했습니다. 스크롤할 내용이 없거나, 관리자 권한으로 "
                        "실행된 창이거나, 스크롤을 막아 둔 창일 수 있습니다.")
        else:
            note = {"stopped": "중지한 곳까지 ", "limit": f"너무 길어 {h}px까지만 ", "full": f"너무 길어 {h}px까지만 ",
                    "nomatch": "화면이 크게 바뀌어 이어 붙일 곳을 찾지 못해 여기까지만 ",
                    "covered": "다른 창이 캡처 영역을 가려서 여기까지만 ",
                    "blocked": "화면 캡처가 막혔습니다(보안 프로그램이나 보호된 영상이 캡처를 막고 있을 수 "
                               "있습니다). 막히기 전까지 "}.get(sc.reason, "")
            self.notify(f"스크롤 캡처({what}) {w}×{h}px를 {note}복사했습니다. 원하는 곳에 Ctrl+V")
        self.open_editor(img, dpi, f"스크롤 캡처 · {what}")

    # --- edit window ---------------------------------------------------------------------------------
    def open_editor(self, img, dpi: float, title: str) -> None:
        """Show a big capture (scroll, whole window) with every normal capture tool. It is already
        on the clipboard; with auto-save on it is saved now (and updated if drawn on)."""
        from .editor import EditorWindow
        h, w = img.shape[:2]
        self._editor_path = self._save(img) if self.settings.auto_save else None
        self.session.hotkey(Rect(0, 0, w, h))
        self.session.select(Rect(0, 0, w, h))
        self.mode = "draw"
        self._acted = True
        ed = EditorWindow(self, np.ascontiguousarray(img), title)
        self.editor = ed
        self.overlays = [ed.canvas]
        self.active_overlay = ed.canvas
        ed.show()
        ed.initial_zoom()
        ed.canvas.show_toolbar()
        ed.raise_()
        ed.activateWindow()
        ed.canvas.setFocus()

    def _result_action(self, name: str, img, dpi: float, win, holder: dict) -> None:
        """Buttons of a result window (scroll capture, whole-window capture)."""
        if name == "copy":
            self._copy_image(img, dpi)
        elif name == "save_as":
            self._save_as(img, win)
        elif name == "ppt":
            self._send_item_to_ppt(Picture(img, dpi), "캡처를")
        elif name == "pin":
            self.pin(img, win.pos(), dpi / 96)
        elif name == "link_file":
            if holder.get("path") is None:
                holder["path"] = self._save(img)
            if holder["path"] is not None:
                self._copy_file_link(holder["path"])
        elif name == "link_web":
            self._share_web(img, on_declined=lambda: None)

    # --- whole window (one click, also across monitors) -----------------------------------------
    def _capture_whole_window(self, win, ov) -> None:
        img = self._screen("capture_window", win.hwnd, win.rect)
        if img is None or img.shape[:2] != (win.rect.h, win.rect.w) or looks_blocked(img):
            img = self._compose_from_screens(win.rect)
        img = np.ascontiguousarray(img[:, :, :3])
        dpi = 96 * ov.scale
        self._acted = True
        self.session.key("Escape")
        pos = ov.mapToGlobal(QPoint(40, 40))
        self.close_overlays()
        payload = self._image_payload(img, dpi)
        if payload:
            self._set_clipboard(payload)
        self.notify(f"'{win.title or '창'}' 창 전체({win.rect.w}×{win.rect.h}px)를 복사했습니다. 원하는 곳에 Ctrl+V")
        self.open_editor(img, dpi, f"창 전체 · {win.title or '창'}")

    def _compose_from_screens(self, rect: Rect):
        """The window pieced together from each monitor's frozen picture (white where no monitor is)."""
        out = np.full((rect.h, rect.w, 3), 255, np.uint8)
        done = set()
        for o in self.overlays:
            m = o.monitor.rect
            part = clamp_rect(rect, m)
            if part is None:
                continue
            done.add(o.monitor.name)
            src = o.image[part.y - m.y:part.y - m.y + part.h, part.x - m.x:part.x - m.x + part.w, :3]
            out[part.y - rect.y:part.y - rect.y + part.h, part.x - rect.x:part.x - rect.x + part.w] = src
        for mon in self.screen.monitors():
            part = clamp_rect(rect, mon.rect)
            if part is not None and mon.name not in done:
                src = self.screen.grab(part)[:, :, :3]
                out[part.y - rect.y:part.y - rect.y + part.h, part.x - rect.x:part.x - rect.x + part.w] = src
        return out

    # --- links -------------------------------------------------------------------------------------------
    # --- action bar switches ---------------------------------------------------------------------
    def _bar_action(self, name: str) -> None:
        s = self.settings
        if name == "autosave":
            s.auto_save = not s.auto_save
            self._persist()
            for ov in self.overlays:
                ov.side_bar.set_autosave(s.auto_save)
            if s.auto_save:
                folder, _ = resolve_save_dir(s.save_dir, self.fallback_dir)
                self.notify(f"자동 저장을 켰습니다. 캡처를 끝낼 때마다 {folder}에 저장합니다.")
            else:
                self.notify("자동 저장을 껐습니다.")
        elif name == "more":
            s.bar_expanded = not s.bar_expanded
            self._persist()
            for ov in self.overlays:
                ov.side_bar.set_expanded(s.bar_expanded)
                if ov is self.active_overlay:
                    ov.show_toolbar()
        elif name == "open_folder":
            folder, _ = resolve_save_dir(s.save_dir, self.fallback_dir)
            self.open_folder(folder)

    # --- web search -------------------------------------------------------------------------------
    def _web_search(self, name: str) -> None:
        from ..core import websearch
        kind, engine = name.split(":", 1)
        if (kind == "search_img" and engine != "google") or \
                (kind == "search_text" and engine not in websearch.LABELS):
            return
        if self.session.state is not State.EDITING:
            return
        ov, sel, doc, raw = self._take()
        final = compose(raw, doc)
        payload = self._image_payload(final, 96 * ov.scale)
        if payload:
            self._set_clipboard(payload)
        if kind == "search_img":
            self._open_search(("img", engine, websearch.image_page(engine)))
            return

        def work():
            try:
                lines = self._read(raw)
            except OcrUnavailable:
                lines = []
            return "text", engine, websearch.text_url(engine, full_text(lines)) if lines else None

        if self.sync:
            self._open_search(work())
        else:
            self.notify("캡처 속 글자를 읽는 중…")
            QThreadPool.globalInstance().start(_Job(work, self._search_done))

    def _open_search(self, result) -> None:
        from ..core.websearch import LABELS
        if isinstance(result, Exception):
            self.notify(f"검색하지 못했습니다: {result}")
            return
        kind, engine, url = result
        if url is None:
            self.notify("캡처에서 글자를 찾지 못해 검색할 수 없습니다.")
            return
        if not self.open_url(url):
            self.notify("브라우저를 열지 못했습니다. 캡처는 복사되어 있습니다.")
        elif kind == "img":
            if self._screen("paste_into_new_browser_page", "Google", default=False):
                self.notify("구글 '이미지로 검색' 창을 열었습니다. 창이 앞에 뜨면 캡처를 자동으로 붙여 넣어 찾습니다. "
                            "붙지 않으면 그 창에서 Ctrl+V 하세요(안 보이면 카메라 아이콘을 누른 뒤 Ctrl+V).")
            else:
                self.notify("구글 '이미지로 검색' 창을 열었습니다. 그 창에서 Ctrl+V 하면 캡처로 찾습니다 "
                            "(창이 안 보이면 검색창의 카메라 아이콘을 누른 뒤 Ctrl+V). 붙여 넣기 전에는 아무것도 올라가지 않습니다.")
        else:
            self.notify(f"캡처 속 글자로 찾기를 열었습니다 ({LABELS[engine]}).")

    # --- mail -----------------------------------------------------------------------------------
    def address_book(self):
        if self._book is None:
            from ..core import contacts
            self._book, warn = contacts.load(self.contacts_path, unprotect=self.unprotect)
            if warn:
                self.notify(warn)
        return self._book

    def _save_book(self) -> None:
        from ..core import contacts
        try:
            contacts.save(self.address_book(), self.contacts_path, protect=self.protect)
        except Exception as e:  # noqa: BLE001 - the mail still goes ahead; say why it wasn't kept
            log.warning("address book not saved: %s", type(e).__name__)
            self.notify("주소록을 저장하지 못했습니다. 이번 메일은 그대로 진행합니다.")

    def _send_mail(self) -> None:
        """Copy the capture, choose recipients, open the mail service's compose page in the
        person's own browser (their own sign-in), and show the paste helper. Never sends."""
        if self.session.state is not State.EDITING:
            return
        from ..core.contacts import BookFull, InvalidEmail
        from ..core.mailcompose import compose as compose_mail
        from ..core.mailcompose import default_subject
        ov, sel, doc, raw = self._take()
        final = compose(raw, doc)
        payload = self._image_payload(final, 96 * ov.scale)
        if payload:
            self._set_clipboard(payload)
        book = self.address_book()
        from .mail_ui import ask_mail
        choice = (self.ask_mail or ask_mail)(book, self.settings, None)
        if choice is None:
            self.notify("메일 보내기를 취소했습니다. 캡처는 복사되어 있습니다.")
            return
        for email, name in choice.new.items():
            try:
                book.add(name, email)
            except (InvalidEmail, BookFull):
                pass
        to, cc = book.resolve(choice.to, choice.cc)
        if self.settings.mail_provider != choice.provider:
            self.settings.mail_provider = choice.provider
            self._persist()
        subject = default_subject(self.now())
        try:
            page = compose_mail(choice.provider, to, cc, subject, account=self.settings.mail_account,
                                custom=self.settings.mail_custom_url)
        except ValueError:
            self.notify("회사 메일 쓰기 주소가 올바르지 않습니다. 설정 → 메일에서 https:// 로 시작하는 주소를 넣어 주세요. "
                        "캡처는 복사되어 있습니다.")
            return
        book.mark_used(to + cc)
        self._save_book()
        if not self.open_url(page.url):
            self.notify("브라우저를 열지 못했습니다. 메일 사이트를 직접 열고 도우미 창으로 붙여 넣으세요.")
        else:
            self.notify("메일 쓰기 화면을 열었습니다. 도우미 창의 버튼으로 붙여 넣고 [보내기]는 직접 누르세요.")
        from .mail_ui import MailHelper
        if self.mail_helper is not None:
            self.mail_helper.close()

        def save_for_attachment() -> None:
            path = self._save(final)
            if path is not None:
                self.reveal_file(path)
                self.notify(f"첨부용으로 저장했습니다: {path.name}")
        self.mail_helper = MailHelper(self._set_clipboard)
        self.mail_helper.set_data(to, cc, subject, page.prefilled, payload, save_for_attachment)
        if to and not page.prefilled:              # first step done: Ctrl+V in 받는 사람 right away
            self.mail_helper.press("to")
        self.mail_helper.place()
        self.mail_helper.show()

    def _send_to_kakao(self, name: str) -> None:
        """Copy the capture (drawings included), then bring the chosen chat to the front and
        paste it there - KakaoTalk shows its own send confirmation - or open KakaoTalk."""
        hwnd = 0
        if name.startswith("kakao_chat:"):
            try:
                hwnd = int(name.split(":", 1)[1])
            except ValueError:
                return
        if self.session.state is not State.EDITING:
            return
        self.finish("copy")
        kakao = self.kakao
        if not kakao.installed():
            self.notify("카카오톡이 설치되어 있지 않습니다. 캡처는 복사되어 있으니 보낼 곳에 Ctrl+V 하세요.")
            return

        def work() -> str:
            if hwnd:
                title = dict(kakao.chats()).get(hwnd)
                if title is None:
                    kakao.open_main()
                    return "그 채팅방이 닫혀 있어 카카오톡을 열었습니다. 보낼 채팅방을 열고 Ctrl+V → [전송]."
                if kakao.paste_into(hwnd):
                    return f"'{title}' 채팅방에 캡처를 붙여 넣었습니다. 카카오톡 창의 [전송]을 누르면 보내집니다."
                return f"'{title}' 채팅방을 앞으로 띄우지 못했습니다. 그 채팅방에서 Ctrl+V → [전송] 하세요."
            if kakao.open_main():
                return "카카오톡을 열었습니다. 보낼 채팅방을 열고 Ctrl+V → [전송] 하세요 (캡처는 복사되어 있습니다)."
            return "카카오톡을 열지 못했습니다. 캡처는 복사되어 있으니 카카오톡 채팅방에서 Ctrl+V 하세요."

        if self.sync:
            self.notify(work())
        else:
            QThreadPool.globalInstance().start(_Job(work, self._kakao_done))

    def _link_from_capture(self, kind: str) -> None:
        if self.session.state is not State.EDITING:
            return
        if kind == "link_web" and not self._share_ok():
            return                                         # declined: the capture stays open
        ov, sel, doc, raw = self._take(autosave=False)
        final = compose(raw, doc)
        path = self._save(final) if (kind == "link_file" or self.settings.auto_save) else None
        if kind == "link_file":
            if path is not None:
                self._copy_file_link(path)
        else:
            self._share_web(final, consent_done=True)

    def _copy_file_link(self, path) -> None:
        from ..core.share import file_link, link_html
        text, url = file_link(path)
        payload = {UNICODE: text, HTML: cf_html(link_html(url, Path(path).name))}
        if self._set_clipboard(payload):
            self.notify(f"파일 링크를 복사했습니다: {text}  (같은 PC나 이 폴더에 들어갈 수 있는 사람만 열 수 있습니다. "
                        "여러 사람과 나누려면 '인터넷 공유 링크'를 쓰세요.)")

    def _share_ok(self) -> bool:
        if self.settings.share_consent:
            return True
        ask = self.ask_share_consent or self._ask_share_consent_dialog
        if not ask():
            return False
        self.settings.share_consent = True
        self._persist()
        return True

    def _ask_share_consent_dialog(self) -> bool:
        from PySide6.QtWidgets import QMessageBox
        from ..core.share import EXPIRY_NAMES
        keep = EXPIRY_NAMES.get(self.settings.share_expiry, self.settings.share_expiry)
        box = QMessageBox(QMessageBox.Question, "인터넷 공유 링크",
                          "인터넷 공유 링크를 만들면 이 캡처가 인터넷(Litterbox 무료 임시 보관 서비스)에 올라갑니다.\n\n"
                          "• 링크를 아는 사람은 누구나 볼 수 있습니다.\n"
                          f"• {keep} 뒤 자동으로 삭제되고, 그 전에는 지울 수 없습니다.\n"
                          "• 회사 기밀·개인정보가 보이는 캡처는 올리지 마세요 (모자이크로 가린 뒤 올리세요).\n\n"
                          "계속할까요? (다음부터는 묻지 않습니다)", QMessageBox.Yes | QMessageBox.No)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        return box.exec() == QMessageBox.Yes

    def _share_web(self, img, on_declined=None, consent_done: bool = False) -> None:
        from ..core.share import EXPIRY_NAMES, ShareError, link_html, upload_litterbox
        if not consent_done and not self._share_ok():
            return
        ok, png = cv2.imencode(".png", img)
        if not ok:
            return
        expiry = self.settings.share_expiry
        keep = EXPIRY_NAMES.get(expiry, expiry)
        upload = self.uploader or upload_litterbox

        def work():
            try:
                return upload(png.tobytes(), expiry), None
            except ShareError as e:
                return None, str(e)

        def done(result) -> None:
            url, err = result if not isinstance(result, Exception) else (None, str(result))
            if url is None:
                self.notify(f"인터넷 링크를 만들지 못했습니다: {err}")
                return
            if self._set_clipboard({UNICODE: url, HTML: cf_html(link_html(url, url))}):
                self.notify(f"인터넷 링크를 복사했습니다 ({keep} 뒤 자동 삭제): {url}")

        if self.sync:
            done(work())
        else:
            self.notify("인터넷 링크를 만드는 중…")
            self._share_done_cb = done
            QThreadPool.globalInstance().start(_Job(work, self._share_done))

    def _save_as(self, img, parent=None) -> bool:
        ext = ".jpg" if self.settings.image_format == "jpg" else ".png"
        default = unique_path(self._save_dialog_start(), render(self.settings.filename_pattern, self.now()), ext)
        target = self.ask_save_path(default, parent)
        if target is None:
            return False
        if target.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            target = target.with_suffix(ext)
        if self._write_image(img, target):
            self.settings.last_save_dir = str(target.parent)
            self._persist()
            return True
        return False

    # --- "PPT로": exactly what was captured -----------------------------------------------
    def _send_capture_to_ppt(self) -> None:
        """Picture of the capture (with drawings); in text mode the recognized/copied text."""
        if self.session.state is not State.EDITING:
            return
        ov = self.active_overlay
        if ov.ocr_lines is not None:
            text, cut = clip_text(self._last_text or full_text(self._text_lines))
            self._take()   # the clipboard keeps the text, so Ctrl+V still pastes text
            if cut:
                self.notify(f"글자가 너무 많아 앞부분 {len(text) - 1}자만 PowerPoint에 넣습니다. "
                            "전체는 Ctrl+V로 붙여넣으세요.")
            self._send_item_to_ppt(TextItem(text, font_family="Malgun Gothic", font_size=18), "글자를")
            return
        ov, sel, doc, raw = self._take(close=False)
        final = compose(raw, doc)
        dpi = 96 * ov.scale
        payload = self._image_payload(final, dpi)
        if payload:
            self._set_clipboard(payload)   # fallback: Ctrl+V anywhere
        self.close_overlays()
        self._send_item_to_ppt(Picture(final, dpi), "캡처 그림을")

    # --- text mode: copy everything, then drag over the frozen image to copy a part -------
    def _start_text_mode(self) -> None:
        if self.session.state is not State.EDITING:
            return
        self._acted = True
        ov, sel = self.active_overlay, self.session.selection
        ov.close_text_editor()
        doc = self.session.document
        raw = mask_outside(ov.crop(sel), doc.clip if doc else None)

        def work():
            try:
                return self._read(raw), None
            except OcrUnavailable as e:
                return [], str(e)

        self._text_ctx = (ov, raw)
        if self.sync:
            self._on_text_ready(work())
        else:
            ov.setCursor(Qt.BusyCursor)
            QThreadPool.globalInstance().start(_Job(work, self._text_ready))

    def _on_text_ready(self, result) -> None:
        ov, raw = self._text_ctx
        if self.session.state is not State.EDITING or ov is not self.active_overlay:
            return  # the capture was closed while recognizing
        if isinstance(result, Exception):
            self.notify(f"인식 중 오류가 발생했습니다: {result}")
            return
        lines, err = result
        if err:
            self.notify(err)
            return
        if not lines:
            self.notify("텍스트를 찾지 못했습니다.")
            ov.unsetCursor()
            return
        self._text_lines, self._text_grid = lines, self._grid_for(raw, lines)
        self._text_table = self._text_grid or self._table_rows(raw, lines, 96 * ov.scale)
        self._last_text = self._last_raw = ""
        self._copy_text(lines, self._text_grid, drag_hint=True)
        ov.enter_ocr_mode(lines, table=bool(self._text_table))
        self._preload_ai(full_text(lines))

    def _preload_ai(self, text: str) -> None:
        """Text mode is open: translate / summary are likely next, so load their models now
        (in the background; freed again after 90 s unused)."""
        ai = self.ai if not self.sync else self._ai      # tests: only a service they put in
        if ai is None or not hasattr(ai, "preload"):
            return

        def work():
            try:
                ai.preload(text)
            except Exception as e:  # noqa: BLE001 - a preload must never disturb text mode
                log.info("AI preload skipped: %s", e)
            return None
        if self.sync:
            work()
        else:
            QThreadPool.globalInstance().start(_Job(work, self._ai_preloaded))
        self._ai_idle_timer.start()

    @staticmethod
    def _grid_for(raw, lines):
        """Spreadsheet screenshot -> table cells (from its grid lines), else None."""
        found = detect_grid(raw)
        if not found:
            return None
        grid = grid_from_cells([(l.text, *l.box) for l in lines], *found)
        return grid if table_is_plausible(grid) else None

    def _best_table(self, raw, scored, det, dpi: float = 96):
        """The table in the capture: ruled / laid-out tables, or one drawn with line characters
        (terminal output) - whichever gives more filled cells."""
        t = find_table(raw, scored, det, dpi) if scored else None
        read = getattr(self.ocr, "read_words", None)
        if read is None:
            return t
        try:
            b = find_box_table(raw, read, dpi)
        except OcrUnavailable:
            b = None
        filled = lambda tb: sum(1 for r in tb.rows for c in r if c)       # noqa: E731
        if b is not None and (t is None or filled(b) >= filled(t)):
            return b
        return t

    def _table_rows(self, raw, lines, dpi: float = 96):
        """Rows of a table laid out on screen without ruling lines (dark pages, web tables)."""
        found = self._best_table(raw, [(l.text, l.box, l.score) for l in lines], [], dpi)
        if found is None:
            return None
        return found.rows

    def _copy_text(self, lines, grid=None, drag_hint=False) -> None:
        redact = self.settings.redact_pii
        if grid:
            cells = [[mask(c) if redact else c for c in row] for row in grid]
            if self._set_clipboard(text_payload("", table=cells)):
                self._last_text = "\n".join("\t".join(row) for row in cells)
                self.notify(f"표 {len(cells)}행×{len(cells[0])}열로 복사했습니다. Excel에 붙여넣으면 칸이 나뉩니다.")
            return
        raw_text = full_text(lines)
        text = mask(raw_text) if redact else raw_text
        if text.strip() and self._set_clipboard(text_payload(text)):
            self._last_text, self._last_raw = text, raw_text
            note = " (개인정보 가림)" if text != raw_text else ""
            hint = " 글자 위를 드래그하면 그 부분만 복사합니다." if drag_hint else ""
            self.notify(f"텍스트 {len(lines)}줄을 복사했습니다{note}.{hint}")

    def copy_ocr_selection(self, rect) -> None:
        text = select_text(self._text_lines, rect)
        if not text:
            self.notify("드래그한 곳에 인식된 글자가 없습니다.")
            return
        self._last_raw = text
        if self.settings.redact_pii:
            text = mask(text)
        if self._set_clipboard(text_payload(text)):
            self._last_text = text
            n = len(text.replace("\n", "").replace(" ", ""))
            self.notify(f"선택한 글자 {n}자를 복사했습니다.")

    def on_ocr_action(self, name: str) -> None:
        ov = self.active_overlay
        if name == "all":
            self._copy_text(self._text_lines, self._text_grid)
        elif name == "table":
            rows = getattr(self, "_text_table", None)
            if not rows:
                self.notify("표 모양을 찾지 못했습니다. 칸이 나란히 맞춰진 글에서 쓸 수 있습니다.")
            else:
                cells = [[mask(c) if self.settings.redact_pii else c for c in r] for r in rows]
                if self._set_clipboard(table_payload(cells)):
                    self.notify(f"표 {len(cells)}행×{len(cells[0])}열로 복사했습니다. Excel·PowerPoint에서 Ctrl+V 하세요.")
        elif name in ("translate", "summarize"):
            self.ai_request(name, self._last_raw or full_text(self._text_lines))
        elif name == "back" and ov is not None:
            ov.exit_ocr_mode()
        elif name == "window" and ov is not None:
            sel = self.session.selection
            pos = self._below(ov, sel)
            lines, grid = self._text_lines, self._text_grid
            self._take()
            self._show_text_panel(lines, None, pos, grid)

    def _show_text_panel(self, lines, qr, pos, grid=None) -> None:
        if self.text_panel:
            self.text_panel.close()
        self.text_panel = TextPanel(lines, self._set_clipboard, self.settings.redact_pii, qr, self.notify, grid,
                                    ai_action=self.ai_request)
        self.text_panel.move(pos + QPoint(0, 8))
        self.text_panel.show()

    def _take(self, close: bool = True, autosave: bool = True):
        """Grab selection + document + pixels and end the session. close=False lets the caller
        put the result on the clipboard first and hide the (large) overlay windows afterwards.
        With auto-save on, the finished capture (drawings included) is saved as well — after
        the caller's action, so copying is never slowed down."""
        ov = self.active_overlay
        ov.close_text_editor()        # keep what is being typed
        sel, doc = self.session.selection, self.session.document
        self.last_document = doc      # what the finished capture contained (drawings)
        raw = ov.crop(sel)
        self._remember_style(ov)
        self.session.key("Escape")
        if close:
            self.close_overlays()
        if autosave and self.settings.auto_save:
            def save():
                self._taken_path = self._autosave(raw, doc)
            if self.sync:
                save()
            else:
                QTimer.singleShot(0, save)
        return ov, sel, doc, raw

    def _autosave(self, raw, doc):
        """Save the finished capture. An edit window was saved when it opened: then only rewrite
        that same file if something was drawn (no second copy)."""
        path, self._editor_path = self._editor_path, None
        if path is not None:
            if doc is not None and doc.shapes and self._write_image(compose(raw, doc), Path(path)):
                return Path(path)
            return Path(path)
        return self._save(compose(raw, doc))

    def _remember_style(self, ov) -> None:
        tb = ov.toolbar
        s = self.settings
        s.last_tool, s.last_color, s.last_width = tb.tool, tb.color, int(tb.line_width)
        s.last_font_family = tb.font_family
        s.last_highlight_color = tb.highlight_color
        s.last_text_bg = tb.bg
        s.recent_colors = push_recent(s.recent_colors, tb.color)
        self._persist()

    def _save_dialog_start(self) -> Path:
        s = self.settings
        for d in (s.last_save_dir, s.save_dir):
            if d and Path(d).is_dir():
                return Path(d)
        return Path(s.last_save_dir or s.save_dir or self.fallback_dir)

    def _ask_save_path_dialog(self, default: Path, parent=None) -> Path | None:
        from PySide6.QtWidgets import QFileDialog
        chosen, _ = QFileDialog.getSaveFileName(parent, "저장할 위치 선택", str(default),
                                                "PNG 이미지 (*.png);;JPG 이미지 (*.jpg)")
        return Path(chosen) if chosen else None

    def finish(self, action: str) -> None:
        if self.session.state is not State.EDITING:
            return
        target = None
        if action == "save_as":
            ext = ".jpg" if self.settings.image_format == "jpg" else ".png"
            default = unique_path(self._save_dialog_start(), render(self.settings.filename_pattern, self.now()), ext)
            target = self.ask_save_path(default, self.active_overlay)
            if target is None:
                return  # cancelled: keep the capture and the drawing
            if target.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                target = target.with_suffix(ext)
        ov, sel, doc, raw = self._take(close=action != "copy", autosave=action not in ("save", "save_as"))
        final = compose(raw, doc)
        dpi = 96 * ov.scale
        if action == "copy":
            t0 = time.perf_counter()
            self._copy_image(final, dpi)   # clipboard first (what "Enter → copied" means) ...
            t1 = time.perf_counter()
            self.close_overlays()          # ... then hide the full-screen windows
            self.last_copy_ms = ((t1 - t0) * 1000, (time.perf_counter() - t0) * 1000)
        elif action == "save":
            self._save(final)
        elif action == "save_as":
            if self._write_image(final, target):
                self.settings.last_save_dir = str(target.parent)
                self._persist()
        elif action == "pin":
            # mapToGlobal: Qt's own mapping is exact on mixed-DPI multi-monitor setups
            pos = ov.mapToGlobal(ov.local_rect(sel).topLeft().toPoint())
            self.pin(final, pos, ov.devicePixelRatioF() or ov.scale, ov.screen())

    @staticmethod
    def _image_payload(img, dpi: float = 96) -> dict | None:
        """PNG + DIB tagged with the screen's pixels-per-inch, so Office pastes it at on-screen size."""
        ok, png = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])  # fast; size is secondary
        if not ok:
            return None
        return image_payload(png_with_dpi(png.tobytes(), dpi), dib_from_bgr(img, dpi))

    def _copy_image(self, img, dpi: float = 96) -> None:
        payload = self._image_payload(img, dpi)
        if payload and self._set_clipboard(payload):
            self.notify("이미지를 클립보드에 복사했습니다. 원하는 곳에 Ctrl+V")

    def _save(self, img, ask: bool = False) -> Path | None:
        s = self.settings
        ext = ".jpg" if s.image_format == "jpg" else ".png"
        try:
            folder, used_fallback = resolve_save_dir(s.save_dir, self.fallback_dir)
        except SaveDirError as e:
            self.notify(f"{e} 이미지는 클립보드에 남겨 둡니다.")
            self._copy_only(img)
            return None
        if used_fallback and s.save_dir:
            self.notify(f"지정한 폴더에 저장할 수 없어 대체 폴더에 저장합니다: {folder}")
        path = unique_path(folder, render(s.filename_pattern, self.now()), ext)
        return path if self._write_image(img, path) else None

    def _write_image(self, img, path: Path) -> bool:
        suffix = path.suffix.lower()
        params = [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpg_quality] if suffix in (".jpg", ".jpeg") else []
        if suffix in (".jpg", ".jpeg"):
            img = flatten(img)   # JPG has no transparency: a freeform crop gets a white outside
        ok, buf = cv2.imencode(".jpg" if suffix in (".jpg", ".jpeg") else ".png", img, params)
        try:
            if not ok:
                raise OSError("이미지 인코딩 실패")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(buf.tobytes())  # write_bytes: cv2.imwrite fails on non-ASCII paths
        except OSError as e:
            self.notify(f"저장하지 못했습니다 ({e}). 이미지는 클립보드에 남겨 둡니다.")
            self._copy_only(img)
            return False
        self.notify(f"저장했습니다: {path}")
        return True

    def _persist(self) -> None:
        try:
            settings_io.save(self.settings, self.settings_path)
        except OSError:
            pass

    def _copy_only(self, img) -> None:
        ok, png = cv2.imencode(".png", img)
        if ok:
            self._set_clipboard(image_payload(png.tobytes(), dib_from_bgr(img)))

    def _below(self, ov, sel) -> QPoint:
        """Global point under the selection, kept on screen (a tall edit canvas ends far below)."""
        from PySide6.QtGui import QGuiApplication
        pos = ov.mapToGlobal(ov.local_rect(sel).bottomLeft().toPoint())
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            if not g.contains(pos):
                pos = QPoint(g.x() + 60, g.y() + 60)
        return pos

    def pin(self, img, pos: QPoint, dpr: float = 1.0, screen=None) -> PinWindow:
        p = PinWindow(img, pos, dpr)
        from PySide6.QtGui import QGuiApplication
        scr = screen or QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if scr is not None:                       # a tall capture is pinned shrunk to fit the screen
            g = scr.availableGeometry()
            if p.height() > g.height() * 0.8 or p.width() > g.width() * 0.8:
                from .pin import MIN_ZOOM
                p.zoom = max(MIN_ZOOM, min(g.height() * 0.8 / p.height(), g.width() * 0.8 / p.width()))
                p._resize()
                if not g.contains(pos):
                    pos = QPoint(g.x() + 40, g.y() + 40)
                p.move(pos)
        if screen is not None:
            p.setScreen(screen)
            p.move(pos)
        p.closed.connect(self._pin_closed)
        p.managerRequested.connect(lambda w: self.show_pin_manager())
        p.copyRequested.connect(lambda w: self._copy_image(w.image, 96 * w.dpr))
        p.saveRequested.connect(lambda w: self._save(w.image))
        self.pins.append(p)
        p.show()
        self.notify("화면에 고정했습니다. 다른 창 위에 계속 떠 있습니다. "
                    "끌어서 옮기기 · 휠로 확대 · 닫기: Esc, X 버튼, 더블클릭")
        return p

    def _pin_closed(self, w) -> None:
        if w in self.pins:
            self.pins.remove(w)
        if self.pin_manager is not None:
            self.pin_manager.refresh()

    def _pin_from_capture(self, how: str) -> None:
        if self.session.state is not State.EDITING:
            return
        ov, sel, doc, raw = self._take()
        final = compose(raw, doc)
        if how == "pin_stack":
            self.pin_stacked(final, ov.devicePixelRatioF() or ov.scale)
        else:
            pos = ov.mapToGlobal(ov.local_rect(sel).topLeft().toPoint())
            self.pin_other_screen(final, pos, ov.devicePixelRatioF() or ov.scale, ov.screen())

    def _screen_rect(self, screen=None):
        from PySide6.QtGui import QGuiApplication
        scr = screen or QGuiApplication.primaryScreen()
        return scr.availableGeometry() if scr is not None else QRect(0, 0, 1280, 720)

    def _stack_slots(self, sizes, g, gap: int = 12):
        """Top-right of the screen, downwards; a full column continues to its left."""
        out = []
        x_right, y, col_w = g.right() - gap, g.top() + gap, 0
        for w, h in sizes:
            if y + h > g.bottom() - gap and y > g.top() + gap:
                x_right -= col_w + gap
                y, col_w = g.top() + gap, 0
            out.append(QPoint(max(g.left(), x_right - w), y))
            y += h + gap
            col_w = max(col_w, w)
        return out

    def pin_stacked(self, img, dpr: float = 1.0) -> PinWindow:
        p = self.pin(img, QPoint(0, 0), dpr)
        g = self._screen_rect()
        others = [q for q in self.pins if q is not p and q.isVisible()]
        y = g.top() + 12
        for q in others:                              # below the pins already at the right edge
            r = q.frameGeometry()
            if r.right() >= g.right() - 40 and r.left() <= g.right() - p.width() - 12 + p.width():
                y = max(y, r.bottom() + 12)
        if y + p.height() > g.bottom():
            self.arrange_pins()
        else:
            p.move(g.right() - 12 - p.width(), y)
        return p

    def pin_other_screen(self, img, pos: QPoint, dpr: float = 1.0, screen=None) -> PinWindow:
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        here = screen or QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        other = next((s for s in screens if s is not here), None)
        if other is None:
            p = self.pin(img, pos, dpr, screen)
            self.notify("모니터가 하나라서 찍은 자리에 고정했습니다.")
            return p
        g = other.availableGeometry()
        return self.pin(img, QPoint(g.x() + 40, g.y() + 40), dpr, other)

    def arrange_pins(self) -> None:
        g = self._screen_rect()
        pins = [p for p in self.pins]
        for p in pins:                                # very tall pins shrink to fit a column
            if p.height() > g.height() - 24:
                p.zoom *= (g.height() - 24) / p.height()
                p._resize()
        for p, pos in zip(pins, self._stack_slots([(p.width(), p.height()) for p in pins], g)):
            p.move(pos)

    def toggle_pins_hidden(self) -> None:
        hide = any(p.isVisible() for p in self.pins)
        for p in self.pins:
            p.setVisible(not hide)

    def toggle_pins_faded(self) -> None:
        fade = any(p.windowOpacity() > 0.99 for p in self.pins)
        for p in self.pins:
            p.setWindowOpacity(0.5 if fade else 1.0)
            p.bar_buttons["fade"].setText("100%" if fade else "50%")

    def close_all_pins(self) -> None:
        if not self.pins:
            return
        if not self.confirm(f"고정한 캡처 {len(self.pins)}개를 모두 닫을까요? (저장하지 않은 고정은 다시 띄울 수 없습니다)"):
            return
        self.close_pins()

    def show_guide(self, topic: str | None = None):
        """The beginner's guide as a pop-up (stays on top, doesn't block the capture)."""
        from .guide import GuideWindow
        if self.guide_window is None:
            self.guide_window = GuideWindow()
        if topic:
            self.guide_window.show_topic(topic)
        self.guide_window.show()
        self.guide_window.raise_()
        self.guide_window.activateWindow()
        return self.guide_window

    def show_guide_first_time(self) -> bool:
        if self.settings.guide_shown:
            return False
        self.settings.guide_shown = True
        self._persist()
        self.show_guide()
        return True

    def show_pin_manager(self):
        from .pin_manager import PinManager
        if self.pin_manager is None:
            self.pin_manager = PinManager(self)
        self.pin_manager.refresh()
        self.pin_manager.show()
        self.pin_manager.raise_()
        return self.pin_manager

    def close_pins(self) -> None:
        for p in list(self.pins):
            p.close()
        self.pins = []

    # --- text & shapes -----------------------------------------------------------------
    def _run_recognition(self, kind: str) -> None:
        if self.session.state is not State.EDITING:
            return
        ov, sel, doc, raw = self._take()
        user_shapes = list(doc.shapes) if doc else []
        final = compose(raw, doc)
        raw = mask_outside(raw, doc.clip if doc else None)   # recognize only what is kept
        self._run_recognition_on(raw, kind, 96 * ov.scale, final, user_shapes, self._below(ov, sel))

    def _run_recognition_on(self, raw, kind: str, dpi: float, final=None, user_shapes=(), pos=None) -> None:
        final = raw if final is None else final
        pos = pos if pos is not None else QPoint(0, 0)
        user_shapes = list(user_shapes)

        def work():
            lines, err = [], None
            try:
                lines = self._read(raw)
            except OcrUnavailable as e:
                err = str(e)
            if kind == "table_preview":        # ▾ 미리 보고 고치기: always the editable preview
                return kind, lines, err, None, None
            if kind == "table":                # 표 button: the capture's table straight to the clipboard
                scored = [(l.text, l.box, l.score) for l in lines]
                return kind, lines, err, None, self._best_table(raw, scored, [], dpi)
            if kind == "text":
                qr = None
                try:
                    data, _, _ = cv2.QRCodeDetector().detectAndDecode(raw)
                    qr = data or None
                except cv2.error:
                    pass
                return kind, lines, err, qr, self._grid_for(raw, lines) if lines else None
            scored = [(l.text, l.box, l.score) for l in lines]
            det = detect(raw, text_boxes=split_doubtful(scored)[0])
            if not user_shapes:                # a table on screen -> a real table, not loose text boxes
                table = self._best_table(raw, scored, det, dpi)
                if table is not None:
                    return kind, lines, err, None, table
            # shapes and labels in their places; dark text on a saturated fill is read again
            det = recognize_layout(raw, scored, None if err is not None else
                                   (lambda crop: [(l.text, l.box) for l in self.ocr.recognize(crop)]), dpi)
            return kind, lines, err, None, det

        self._pending = (user_shapes, final, pos, dpi)
        if self.sync:
            self._on_job_done(work())
        else:
            QThreadPool.globalInstance().start(_Job(work, self._job_done))

    def _on_job_done(self, result) -> None:
        user_shapes, final, pos, dpi = self._pending
        if isinstance(result, Exception):
            self.notify(f"인식 중 오류가 발생했습니다: {result}")
            return
        kind, lines, err, qr, extra = result
        if kind in ("table", "table_preview"):
            if err:
                self.notify(err)
            elif extra is not None:
                if self._table_choice():
                    self._deliver_table(extra.rows, "\n".join(t for t, _ in extra.outside) or None, extra.style,
                                        extra.col_widths)
            elif not lines:
                self.notify("캡처에서 글자를 찾지 못해 표를 만들 수 없습니다. (그림은 클립보드에 있습니다)")
            else:
                self._table_preview(lines)
        elif kind == "text":
            self._finish_text(lines, err, qr, pos, extra)
        elif isinstance(extra, CapturedTable):
            self._finish_table(extra, send=kind == "ppt")
        else:
            self._finish_shapes(extra or [], user_shapes, final, err, send=kind == "ppt", dpi=dpi)

    def _table_preview(self, lines) -> None:
        """Not laid out as a table: show how it would be split, let the person pick and fix."""
        from ..core.table_split import ocr_row_lines
        from .table_preview import ask_table_preview
        rows_text = ocr_row_lines([(l.text, l.box) for l in lines])
        answer = (self.ask_table_preview or ask_table_preview)(rows_text, None)
        if answer is None:
            self.notify("표로 붙여넣기를 취소했습니다. (그림은 클립보드에 있습니다)")
            return
        action, title, rows = answer
        if not rows:
            self.notify("표가 비어 있어 복사하지 않았습니다.")
            return
        self._deliver_table(rows, title, None, [], target=action)

    def _table_option(self, name: str) -> None:
        _, key, val = (name.split(":") + ["", ""])[:3]
        s = self.settings
        if key == "target" and val in ("excel", "ppt"):
            s.table_target = val
        elif key == "style" and val in ("keep", "plain"):
            s.table_style = val
        elif key == "quick" and val in ("0", "1"):
            s.table_quick = val == "1"
        else:
            return
        self._persist()

    def _table_choice(self) -> bool:
        """The first time (or when the person wants to be asked): where and how."""
        if self.settings.table_quick:
            return True
        from .table_options import ask_table_options
        answer = (self.ask_table_options or ask_table_options)(self.settings, None)
        if answer is None:
            self.notify("표 복사를 취소했습니다. (그림은 클립보드에 있습니다)")
            return False
        self.settings.table_target, self.settings.table_style, self.settings.table_quick = answer
        self._persist()
        return True

    def _deliver_table(self, rows, title, captured, col_widths, target: str | None = None) -> None:
        """Rows -> Excel (clipboard) or PowerPoint, in the capture's look or white/black."""
        from ..core.table_capture import plain_style
        target = target or self.settings.table_target
        keep = self.settings.table_style == "keep"
        size_pt = captured.font_size if captured is not None else 11
        style = captured if keep else plain_style(size_pt)
        if not self._set_clipboard(table_payload(rows, style=style, title=title)):
            return
        size = f"표 {len(rows)}행×{len(rows[0])}열"
        look = "캡처 모양 그대로" if keep else "흰 바탕·검은 글씨"
        if target == "ppt":
            item = TableItem(rows, style=style, title=title, col_widths=col_widths if keep else [],
                             font_size=size_pt if captured is not None else 14)
            self._send_item_to_ppt(item, f"{size}({look})를")
        else:
            self.notify(f"{size}({look})로 복사했습니다. 엑셀에서 Ctrl+V 하세요. (▾ 메뉴에서 PPT·모양 변경)")

    def _finish_table(self, t, send: bool) -> None:
        keep = self.settings.keep_style
        style = t.style if keep else None
        title = "\n".join(text for text, _ in t.outside) or None
        if not self._set_clipboard(table_payload(t.rows, style=style, title=title)):
            return
        size = f"표 {len(t.rows)}행×{len(t.rows[0])}열"
        look = "색·글꼴 그대로" if keep else "기본 모양으로"
        if send:
            item = TableItem(t.rows, style=style, title=title, col_widths=t.col_widths if keep else [],
                             font_size=t.style.font_size if (keep and t.style) else 14)
            self._send_item_to_ppt(item, f"{size}({look})를")
        else:
            self.notify(f"{size}({look})로 복사했습니다. PowerPoint·Excel에서 Ctrl+V 하면 칸마다 고칠 수 있는 표가 됩니다.")

    def _finish_text(self, lines, err, qr, pos, grid=None) -> None:
        """Direct "text" hotkey: copy everything at once and show the text window."""
        if err:
            self.notify(err)
            return
        if not lines and not qr:
            self.notify("텍스트를 찾지 못했습니다.")
            return
        if lines:
            self._copy_text(lines, grid)
        elif qr:
            self._set_clipboard(text_payload(qr))
            self.notify("QR 코드 내용을 복사했습니다.")
        self._show_text_panel(lines, qr, pos, grid)

    def _finish_shapes(self, det, user_shapes, final, err, send: bool = False, dpi: float = 96) -> None:
        keep = self.settings.keep_style
        tables, used = screen_tables(det) if keep else ([], [])
        us, uc = annotations_to_drawing(user_shapes, scale=dpi / 96)
        shapes, conns = to_drawing(det, keep_style=keep)            # complete: tables as cell boxes
        shapes, conns = shapes + us, conns + uc
        if not shapes and not conns:
            if send:  # nothing to convert: still deliver the picture to PowerPoint
                payload = self._image_payload(final, dpi)
                if payload:
                    self._set_clipboard(payload)
                self._send_item_to_ppt(Picture(final, dpi), "도형이 없어 캡처 그림을")
            else:
                self.notify("도형을 찾지 못했습니다. 사각형·원·삼각형·선·화살표를 인식합니다.")
            return
        ok, png = cv2.imencode(".png", final)
        png = png_with_dpi(png.tobytes(), dpi)
        full = shapes_payload(gvml_package(shapes, conns, dpi), svg(shapes, conns, dpi), png)
        note = " (텍스트 인식 없이)" if err else ""
        n = len(tables)
        if not send or not tables:
            if not self._set_clipboard(full):
                return
            boxes = sum(1 for d in det if d.kind == "text")
            what = f"도형 {len(shapes) - boxes}개" + (f", 글상자 {boxes}개" if boxes else "") + f", 연결선 {len(conns)}개"
            if send:
                from ..core.drawingml import _bounds, _resolve
                minx, miny, _, _ = _bounds(shapes, _resolve(shapes, conns))
                self._send_item_to_ppt(ClipboardShapes(origin=(minx, miny), dpi=dpi), f"{what}를{note}")
            elif n:
                self.notify(f"{what}를 복사했습니다{note}. ※ 표 {n}개는 칸 상자로 복사되었습니다(클립보드는 표를 담지 "
                            f"못합니다). 고칠 수 있는 PowerPoint 표로 넣으려면 [도형PPT]로 PowerPoint에 바로 보내세요.")
            else:
                self.notify(f"{what}를 복사했습니다{note}. PowerPoint에서 Ctrl+V 하면 하나씩 고칠 수 있습니다.")
            return
        # straight into PowerPoint: tables as real tables, everything else pasted; afterwards the
        # clipboard holds the complete capture again (tables as cell boxes) for Ctrl+V elsewhere
        rest = [d for d in det if not any(d is u for u in used)]
        s2, c2 = to_drawing(rest, keep_style=keep)
        s2, c2 = s2 + us, c2 + uc
        self._ppt_after = lambda: self._set_clipboard(full)
        self._ppt_note = (f" 표 {n}개는 고칠 수 있는 PowerPoint 표로 넣었습니다. ※ 클립보드(Ctrl+V)로 붙이면 "
                          f"표가 칸 상자로 들어갑니다.",
                          f" (Ctrl+V로 붙이면 표 {n}개는 칸 상자로 들어갑니다.)")
        boxes = sum(1 for d in rest if d.kind == "text")
        what = f"도형 {len(s2) - boxes}개" + (f", 글상자 {boxes}개" if boxes else "") + f", 표 {n}개"
        if not s2 and not c2:
            self._send_item_to_ppt(ClipboardShapes(tables=tables, dpi=dpi, paste=False), f"{what}를{note}")
            return
        if not self._set_clipboard(shapes_payload(gvml_package(s2, c2, dpi), svg(s2, c2, dpi), png)):
            return
        from ..core.drawingml import _bounds, _resolve
        minx, miny, _, _ = _bounds(s2, _resolve(s2, c2))
        self._send_item_to_ppt(ClipboardShapes(tables=tables, origin=(minx, miny), dpi=dpi), f"{what}를{note}")

    # --- translate / summary -----------------------------------------------------------
    @property
    def ai(self):
        if self._ai is None:
            from ..core.ai_local import LocalSummarizer, LocalTranslator
            from ..core.ai_service import AiService
            from ..core.gemini import Gemini
            self._ai = AiService(self.settings, LocalTranslator(), LocalSummarizer(),
                                 cloud_factory=Gemini, get_key=self._ai_key)
        return self._ai

    @ai.setter
    def ai(self, service) -> None:
        self._ai = service

    def _ai_key(self):
        if not self.settings.ai_key:
            return None
        try:
            from ..platform.secret import SecretError, unprotect
            return unprotect(self.settings.ai_key)
        except (SecretError, OSError, ImportError):
            return None

    def ai_request(self, kind: str, text: str, tgt: str | None = None) -> None:
        """Translate or summarize `text`; the result window stays on top of the capture."""
        if not text or not text.strip():
            self.notify("번역·요약할 글자가 없습니다.")
            return
        from .ai_ui import AiWindow
        if self.ai_window is None:
            self.ai_window = AiWindow()
            self.ai_window.action.connect(self._ai_window_action)
            self.ai_window.targetChanged.connect(lambda code: self._ai_run("translate", self._ai_ctx[1], code))
        win = self.ai_window
        win.start(kind, tgt)
        win.show()
        win.raise_()
        win.activateWindow()
        self._ai_run(kind, text, tgt)

    def _ai_run(self, kind: str, text: str, tgt: str | None = None, offline: bool = False) -> None:
        self._ai_ctx = (kind, text, tgt)
        win = self.ai_window
        win.start(kind, tgt)
        self._ai_cancel = False
        s = self.settings
        saved = (s.ai_summary_engine, s.ai_cloud_translate)
        if offline:                       # "이번엔 오프라인으로": only this request
            s.ai_summary_engine, s.ai_cloud_translate = "local", False
            self.ai_offline_once_used = True

        def partial(t):
            self._ai_partial.emit(t) if not self.sync else win.set_partial(t)

        def work():
            try:
                if kind == "translate":
                    return self.ai.translate(text, tgt=tgt, cancel=lambda: self._ai_cancel)
                return self.ai.summarize(text, "ko", on_text=partial, cancel=lambda: self._ai_cancel)
            finally:
                if offline:
                    s.ai_summary_engine, s.ai_cloud_translate = saved

        if self.sync:
            try:
                result = work()
            except Exception as e:  # noqa: BLE001 - explained in the window
                result = e
            self._ai_finished(result)
        else:
            QThreadPool.globalInstance().start(_Job(work, self._ai_done))

    def _ai_finished(self, result) -> None:
        from ..core.ai_local import Busy, Cancelled, ModelMissing
        from ..core.ai_service import ConsentNeeded
        from ..core import model_store as ms
        win = self.ai_window
        if win is None:
            return
        kind, text, tgt = self._ai_ctx
        self._ai_idle_timer.start()
        if isinstance(result, ModelMissing):
            packs = [ms.CATALOG[p] for p in result.packs if p in ms.CATALOG]
            size = sum(ms.pack_size(p) for p in packs) / 2**20
            what = ", ".join(p.title for p in packs)
            ask = self.ask_yes_no or (lambda t, m: __import__("capture_tool.app.ai_ui", fromlist=["x"]).ask_yes_no(t, m, win))
            if ask("AI 모델 받기", f"{what} 모델이 필요합니다(약 {size:,.0f} MB, 한 번만 받으면 됩니다).\n"
                                   "지금 받을까요? 받은 뒤에는 인터넷 없이 동작합니다."):
                self.download_packs(result.packs, lambda ok: self._ai_run(kind, text, tgt) if ok else None)
            else:
                win.set_status("모델을 받지 않아 실행하지 않았습니다. 필요할 때 다시 누르세요.")
            return
        if isinstance(result, ConsentNeeded):
            from . import ai_ui
            choice = (self.ask_consent or (lambda: ai_ui.ask_consent(win)))()
            if choice == "agree":
                self.settings.ai_cloud_consent = True
                self._persist()
                self._ai_run(kind, text, tgt)
            elif choice == "offline":
                self._ai_run(kind, text, tgt, offline=True)
            else:
                win.set_status("취소했습니다.")
            return
        if isinstance(result, Busy):
            win.set_status(str(result))
        elif isinstance(result, Cancelled):
            win.set_status("중지했습니다.")
        elif isinstance(result, Exception):
            log.warning("ai failed: %s", result)
            win.set_status(f"실행하지 못했습니다: {result}")
        else:
            win.set_result(result)

    def _ai_window_action(self, name: str) -> None:
        win = self.ai_window
        text = win.result_text()
        if name == "cancel":
            self._ai_cancel = True
        elif name == "copy" and text.strip():
            if self._set_clipboard(text_payload(text)):
                win.set_status("결과를 복사했습니다. 원하는 곳에 Ctrl+V 하세요.")
                self.notify("결과를 복사했습니다.")
        elif name == "table":
            found = find_text_table(text)
            if found is None:
                win.set_status("표 모양(| 구분, 탭, 칸 맞춤, '항목: 값' 줄)을 찾지 못했습니다. 복사 버튼을 쓰세요.")
            elif self._set_clipboard(text_payload("", table=found.rows)):
                rows = found.rows
                cut = " (너무 커서 일부만)" if found.cut else ""
                win.set_status(f"표 {len(rows)}행×{len(rows[0])}열로 복사했습니다{cut}. "
                               "Excel이나 PowerPoint에서 Ctrl+V 하면 칸이 나뉜 표가 됩니다.")
                self.notify("표로 복사했습니다.")
        elif name == "ppt" and text.strip():
            body, _ = clip_text(text)
            found = find_text_table(text)
            as_table = found is not None and found.kind == "grid" and table_fits(found.rows)
            if as_table:
                self._set_clipboard(text_payload("", table=found.rows))
            else:
                self._set_clipboard(text_payload(text))   # Ctrl+V works whatever PowerPoint does
            win.buttons["ppt"].setEnabled(False)
            win.set_busy("PowerPoint에 넣는 중…")

            def done(ok: bool, msg: str) -> None:
                win.buttons["ppt"].setEnabled(True)
                win.set_status(msg)
                if ok:                                     # get out of the way: show the new slide
                    if self.session.state is not State.IDLE:
                        self.cancel()
                    win.close()
            what = "요약을" if win.mode == "summarize" else "번역을"
            if as_table:
                self._send_item_to_ppt(TableItem(found.rows), f"표({len(found.rows)}행×{len(found.rows[0])}열)를",
                                       on_done=done)
            else:
                self._send_item_to_ppt(TextItem(body, font_family="Malgun Gothic", font_size=18), what, on_done=done)
        elif name in ("copy", "ppt"):
            win.set_status("넣을 결과가 없습니다.")

    def _download_packs(self, packs: list[str], done) -> None:
        """Download model packs in the background with progress in the result window."""
        from ..core import model_store as ms
        win = self.ai_window

        def work():
            for pid in packs:
                ms.download(ms.CATALOG[pid], ms.user_root(),
                            progress=lambda d, t: self._ai_progress.emit((d, t)),
                            cancel=lambda: self._ai_cancel)
            return True

        def finished(result):
            if isinstance(result, Exception):
                win.set_status(str(result))
                done(False)
            else:
                done(True)
        self._ai_cancel = False
        self._ai_dl_done = finished
        QThreadPool.globalInstance().start(_Job(work, self._ai_dl))

    @staticmethod
    def _bring_ppt_to_front(hwnd: int) -> None:
        try:
            from ..platform.powerpoint import bring_to_front
            if not bring_to_front(hwnd):
                log.info("PowerPoint could not be brought to the front")
        except (OSError, AttributeError):
            pass

    def ai_idle(self) -> None:
        """Free the AI models' memory after a while without use."""
        if self._ai is not None:
            self._ai.unload()

    # --- PowerPoint -----------------------------------------------------------------
    def _send_item_to_ppt(self, item, what: str, on_done=None) -> None:
        """Insert into PowerPoint in the background, time-limited; the clipboard already holds
        the same content, so whatever happens the user can still Ctrl+V.
        on_done(ok, message) lets a window show the outcome itself."""
        if getattr(self.powerpoint, "busy", False):
            msg = "PowerPoint로 보내는 중입니다. 끝나면 다시 시도하세요. (클립보드에 있으니 Ctrl+V도 됩니다)"
            self.notify(msg)
            if on_done:
                on_done(False, msg)
            return
        self._ppt_cb = on_done
        if self.drm and not self.settings.drm_notice_shown:
            self.notify(
                f"이 PC에는 {self.drm}(문서 보안 프로그램)가 설치되어 있습니다. PowerPoint가 켜질 때 "
                "'ai.exe - Bad Image' 창이 뜰 수 있는데, Office AI 기능(ai.exe)과 보안 프로그램의 충돌이며 "
                "캡처 도구·PowerPoint 사용에는 지장이 없습니다. OK를 누르고 계속 사용하세요. "
                "완전히 없애려면 IT 담당자에게 보안 프로그램 업데이트를 요청하세요.")
            self.settings.drm_notice_shown = True
            self._persist()

        self.powerpoint.new_slide = self.settings.ppt_new_slide

        def work():
            try:
                return what, self.powerpoint.send(item), None
            except (PowerPointUnavailable, PowerPointBusy) as e:
                return what, 0, str(e)

        if self.sync:
            self._on_ppt_done(work())
        else:
            self.notify("PowerPoint에 넣는 중…")
            QThreadPool.globalInstance().start(_Job(work, self._ppt_done))

    def _on_ppt_done(self, result) -> None:
        ok = False
        if isinstance(result, Exception):
            msg = f"PowerPoint에 넣지 못했습니다: {result} 클립보드에 있으니 Ctrl+V 하세요."
        else:
            what, added, err = result
            if err:
                msg = f"{err} 클립보드에 복사해 두었으니 원하는 곳에 Ctrl+V 하세요."
            elif added:
                where = "새 슬라이드" if self.settings.ppt_new_slide else "보고 있는 슬라이드"
                msg, ok = f"{what} PowerPoint에 넣었습니다 ({where}).", True
                hwnd = int(getattr(self.powerpoint, "last_hwnd", 0) or 0)
                if hwnd:
                    self.bring_to_front(hwnd)       # PowerPoint in front, showing the new slide
            else:
                msg = "PowerPoint에 들어가지 않았습니다. 클립보드에 있으니 슬라이드에서 Ctrl+V 하세요."
        after, self._ppt_after = getattr(self, "_ppt_after", None), None
        extra, self._ppt_note = getattr(self, "_ppt_note", None), None
        if after:
            after()                                   # the complete capture back on the clipboard
        if extra:
            msg += extra[0] if ok else extra[1]
        self.notify(msg)
        cb, self._ppt_cb = getattr(self, "_ppt_cb", None), None
        if cb:
            cb(ok, msg)
