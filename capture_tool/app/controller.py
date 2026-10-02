"""Glue: hotkey -> overlays (cursor monitor first) -> finish actions (copy/save/pin/text/shapes)."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor

from ..core import settings as settings_io
from ..core.clipboard_payload import (HTML, UNICODE, cf_html, dib_from_bgr, image_payload, png_with_dpi,
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
from ..core.shapes import attach_text, detect, to_drawing
from ..core.table import detect_grid, grid_from_cells, table_is_plausible
from ..platform.powerpoint import (ClipboardShapes, Picture, PowerPointBusy, PowerPointUnavailable, TextItem,
                                   clip_text)
from .overlay import OverlayWindow
from .pin import PinWindow
from .render import compose
from .text_panel import TextPanel, mask

log = logging.getLogger("capture_tool")


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
    _ppt_done = Signal(object)
    _text_ready = Signal(object)
    _ai_done = Signal(object)
    _ai_partial = Signal(str)
    _ai_progress = Signal(object)
    _ai_dl = Signal(object)
    _share_done = Signal(object)

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
        from ..platform.powerpoint import PowerPointSender
        from ..platform.security_software import detect_drm
        self.powerpoint = PowerPointSender()
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
        if name not in ("undo", "redo"):
            self._acted = True
        if name in ("link_file", "link_web"):
            self._link_from_capture(name)
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
        elif name in ("text", "shapes"):
            self._run_recognition(name)

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

        QTimer.singleShot(250, tick)   # let the overlays disappear from the screen first

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
                return self.ocr.recognize(raw), None
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
        self._last_text = self._last_raw = ""
        self._copy_text(lines, self._text_grid, drag_hint=True)
        ov.enter_ocr_mode(lines)

    @staticmethod
    def _grid_for(raw, lines):
        """Spreadsheet screenshot -> table cells (from its grid lines), else None."""
        found = detect_grid(raw)
        if not found:
            return None
        grid = grid_from_cells([(l.text, *l.box) for l in lines], *found)
        return grid if table_is_plausible(grid) else None

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
        p.closed.connect(lambda w: self.pins.remove(w) if w in self.pins else None)
        p.copyRequested.connect(lambda w: self._copy_image(w.image, 96 * w.dpr))
        p.saveRequested.connect(lambda w: self._save(w.image))
        self.pins.append(p)
        p.show()
        self.notify("화면에 고정했습니다. 다른 창 위에 계속 떠 있습니다. "
                    "끌어서 옮기기 · 휠로 확대 · 닫기: Esc, X 버튼, 더블클릭")
        return p

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
        pos = self._below(ov, sel)

        def work():
            lines, err = [], None
            try:
                lines = self.ocr.recognize(raw)
            except OcrUnavailable as e:
                err = str(e)
            if kind == "text":
                qr = None
                try:
                    data, _, _ = cv2.QRCodeDetector().detectAndDecode(raw)
                    qr = data or None
                except cv2.error:
                    pass
                    return kind, lines, err, qr, self._grid_for(raw, lines) if lines else None
            det = detect(raw, text_boxes=[l.box for l in lines])
            attach_text(det, [(l.text, l.box) for l in lines])
            return kind, lines, err, None, det

        self._pending = (user_shapes, final, pos, 96 * ov.scale)
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
        if kind == "text":
            self._finish_text(lines, err, qr, pos, extra)
        else:
            self._finish_shapes(extra or [], user_shapes, final, err, send=kind == "ppt", dpi=dpi)

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
        shapes, conns = to_drawing(det)
        us, uc = annotations_to_drawing(user_shapes, scale=dpi / 96)
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
        payload = shapes_payload(gvml_package(shapes, conns, dpi), svg(shapes, conns, dpi),
                                 png_with_dpi(png.tobytes(), dpi))
        if not self._set_clipboard(payload):
            return
        note = " (텍스트 인식 없이)" if err else ""
        if send:
            self._send_item_to_ppt(ClipboardShapes(), f"도형 {len(shapes)}개, 연결선 {len(conns)}개를{note}")
        else:
            self.notify(f"도형 {len(shapes)}개, 연결선 {len(conns)}개를 복사했습니다{note}. PowerPoint에서 Ctrl+V")

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
        elif name == "ppt" and text.strip():
            body, _ = clip_text(text)
            self._set_clipboard(text_payload(text))       # Ctrl+V works whatever PowerPoint does
            win.buttons["ppt"].setEnabled(False)
            win.set_busy("PowerPoint에 넣는 중…")

            def done(ok: bool, msg: str) -> None:
                win.buttons["ppt"].setEnabled(True)
                win.set_status(msg)
                if ok:                                     # get out of the way: show the new slide
                    if self.session.state is not State.IDLE:
                        self.cancel()
                    win.close()
            self._send_item_to_ppt(TextItem(body, font_family="Malgun Gothic", font_size=18),
                                   "요약을" if win.mode == "summarize" else "번역을", on_done=done)
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
            else:
                msg = "PowerPoint에 들어가지 않았습니다. 클립보드에 있으니 슬라이드에서 Ctrl+V 하세요."
        self.notify(msg)
        cb, self._ppt_cb = getattr(self, "_ppt_cb", None), None
        if cb:
            cb(ok, msg)
