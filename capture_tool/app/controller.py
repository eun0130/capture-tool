"""Glue: hotkey -> overlays (cursor monitor first) -> finish actions (copy/save/pin/text/shapes)."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal

from ..core import settings as settings_io
from ..core.clipboard_payload import (UNICODE, dib_from_bgr, image_payload, png_with_dpi, shapes_payload,
                                      text_payload)
from ..core.color import pixel_color, push_recent
from ..core.convert import annotations_to_drawing
from ..core.drawingml import gvml_package, svg
from ..core.geometry import Rect, clamp_rect, nudge, order_cursor_first, virtual_bounds
from ..core.naming import SaveDirError, render, resolve_save_dir, unique_path
from ..core.ocr import OcrUnavailable, full_text, select_text
from ..core.session import CaptureSession, State
from ..core.shapes import attach_text, detect, to_drawing
from ..core.table import detect_grid, grid_from_cells
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
        self._text_ctx = None
        self.last_document = None
        self._text_lines: list = []
        self._text_grid = None
        self.ask_save_path = self._ask_save_path_dialog
        from ..platform.powerpoint import PowerPointSender
        from ..platform.security_software import detect_drm
        self.powerpoint = PowerPointSender()
        self.drm = detect_drm()

    # --- helpers -----------------------------------------------------------------
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
            return False
        mons = self.screen.monitors()
        if not mons:
            self.notify("모니터를 찾지 못했습니다.")
            return False
        ordered = order_cursor_first(mons, self.screen.cursor_pos())
        if mode == "fullscreen":
            img = np.ascontiguousarray(self.screen.grab(ordered[0].rect)[:, :, :3])
            self._copy_image(img, 96 * ordered[0].scale)
            return True
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

    def close_all(self) -> None:
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

    def on_select_rect(self, rect: Rect, ov) -> None:
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
        if self.mode in ("text", "shapes"):
            self.on_toolbar_action(self.mode)
            return
        ov.show_toolbar()
        ov.setFocus()

    def nudge(self, dx: int, dy: int) -> None:
        ov = self.active_overlay
        if ov is None or self.session.selection is None:
            return
        self.session.resize(nudge(self.session.selection, dx, dy, ov.monitor.rect))
        ov.show_toolbar()
        ov.update()

    def cancel(self) -> None:
        self.session.key("Escape")
        self.close_overlays()

    def copy_color(self, ov, local_pt) -> None:
        x, y = ov.to_phys(local_pt)
        c = pixel_color(ov.image, x - ov.monitor.rect.x, y - ov.monitor.rect.y)
        if c and self._set_clipboard({UNICODE: c}):
            self.notify(f"색상 {c} 를 복사했습니다.")

    # --- finishing ---------------------------------------------------------------
    def on_toolbar_action(self, name: str) -> None:
        if name in ("copy", "save", "save_as", "pin"):
            self.finish(name)
        elif name == "cancel":
            self.cancel()
        elif name in ("undo", "redo") and self.session.document is not None:
            getattr(self.session.document, name)()
            if self.active_overlay:
                self.active_overlay.update()
        elif name == "text" and self.mode != "text":
            self._start_text_mode()
        elif name in ("text", "shapes", "ppt"):
            self._run_recognition(name)

    # --- text mode: copy everything, then drag over the frozen image to copy a part -------
    def _start_text_mode(self) -> None:
        if self.session.state is not State.EDITING:
            return
        ov, sel = self.active_overlay, self.session.selection
        ov.close_text_editor()
        raw = ov.crop(sel)

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
        self._copy_text(lines, self._text_grid, drag_hint=True)
        ov.enter_ocr_mode(lines)

    @staticmethod
    def _grid_for(raw, lines):
        """Spreadsheet screenshot -> table cells (from its grid lines), else None."""
        found = detect_grid(raw)
        if not found:
            return None
        grid = grid_from_cells([(l.text, *l.box) for l in lines], *found)
        filled = sum(1 for row in grid for c in row if c)
        return grid if filled >= 3 else None

    def _copy_text(self, lines, grid=None, drag_hint=False) -> None:
        redact = self.settings.redact_pii
        if grid:
            cells = [[mask(c) if redact else c for c in row] for row in grid]
            if self._set_clipboard(text_payload("", table=cells)):
                self.notify(f"표 {len(cells)}행×{len(cells[0])}열로 복사했습니다. Excel에 붙여넣으면 칸이 나뉩니다.")
            return
        raw_text = full_text(lines)
        text = mask(raw_text) if redact else raw_text
        if text.strip() and self._set_clipboard(text_payload(text)):
            note = " (개인정보 가림)" if text != raw_text else ""
            hint = " 글자 위를 드래그하면 그 부분만 복사합니다." if drag_hint else ""
            self.notify(f"텍스트 {len(lines)}줄을 복사했습니다{note}.{hint}")

    def copy_ocr_selection(self, rect) -> None:
        text = select_text(self._text_lines, rect)
        if not text:
            self.notify("드래그한 곳에 인식된 글자가 없습니다.")
            return
        if self.settings.redact_pii:
            text = mask(text)
        if self._set_clipboard(text_payload(text)):
            n = len(text.replace("\n", "").replace(" ", ""))
            self.notify(f"선택한 글자 {n}자를 복사했습니다.")

    def on_ocr_action(self, name: str) -> None:
        ov = self.active_overlay
        if name == "all":
            self._copy_text(self._text_lines, self._text_grid)
        elif name == "back" and ov is not None:
            ov.exit_ocr_mode()
        elif name == "window" and ov is not None:
            sel = self.session.selection
            pos = ov.local_rect(sel).bottomLeft().toPoint() + ov.geometry().topLeft()
            lines, grid = self._text_lines, self._text_grid
            self._take()
            self._show_text_panel(lines, None, pos, grid)

    def _show_text_panel(self, lines, qr, pos, grid=None) -> None:
        if self.text_panel:
            self.text_panel.close()
        self.text_panel = TextPanel(lines, self._set_clipboard, self.settings.redact_pii, qr, self.notify, grid)
        self.text_panel.move(pos + QPoint(0, 8))
        self.text_panel.show()

    def _take(self, close: bool = True):
        """Grab selection + document + pixels and end the session. close=False lets the caller
        put the result on the clipboard first and hide the (large) overlay windows afterwards."""
        ov = self.active_overlay
        ov.close_text_editor()        # keep what is being typed
        sel, doc = self.session.selection, self.session.document
        self.last_document = doc      # what the finished capture contained (drawings)
        raw = ov.crop(sel)
        self._remember_style(ov)
        self.session.key("Escape")
        if close:
            self.close_overlays()
        return ov, sel, doc, raw

    def _remember_style(self, ov) -> None:
        tb = ov.toolbar
        s = self.settings
        s.last_tool, s.last_color, s.last_width = tb.tool, tb.color, int(tb.line_width)
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
        ov, sel, doc, raw = self._take(close=action != "copy")
        final = compose(raw, doc)
        dpi = 96 * ov.scale
        if action == "copy":
            self._copy_image(final, dpi)   # clipboard first (what "Enter → copied" means) ...
            self.close_overlays()          # ... then hide the full-screen windows
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
        if self.settings.auto_save:
            self._save(img)

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

    def pin(self, img, pos: QPoint, dpr: float = 1.0, screen=None) -> PinWindow:
        p = PinWindow(img, pos, dpr)
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
        pos = ov.local_rect(sel).bottomLeft().toPoint() + ov.geometry().topLeft()

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
                if payload and self._set_clipboard(payload):
                    self._send_to_powerpoint("도형이 없어 이미지로")
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
            self._send_to_powerpoint(f"도형 {len(shapes)}개, 연결선 {len(conns)}개를{note}")
        else:
            self.notify(f"도형 {len(shapes)}개, 연결선 {len(conns)}개를 복사했습니다{note}. PowerPoint에서 Ctrl+V")

    # --- PowerPoint -----------------------------------------------------------------
    def _send_to_powerpoint(self, what: str) -> None:
        if self.drm and not self.settings.drm_notice_shown:
            self.notify(
                f"이 PC에는 {self.drm}(문서 보안 프로그램)가 설치되어 있습니다. PowerPoint가 켜질 때 "
                "'ai.exe - Bad Image' 창이 뜰 수 있는데, Office AI 기능(ai.exe)과 보안 프로그램의 충돌이며 "
                "캡처 도구·PowerPoint 사용에는 지장이 없습니다. OK를 누르고 계속 사용하세요. "
                "완전히 없애려면 IT 담당자에게 보안 프로그램 업데이트를 요청하세요.")
            self.settings.drm_notice_shown = True
            self._persist()

        def work():
            from ..platform.powerpoint import PowerPointUnavailable
            try:
                return what, self.powerpoint.paste(), None
            except PowerPointUnavailable as e:
                return what, 0, str(e)

        if self.sync:
            self._on_ppt_done(work())
        else:
            self.notify("PowerPoint를 여는 중…")
            QThreadPool.globalInstance().start(_Job(work, self._ppt_done))

    def _on_ppt_done(self, result) -> None:
        if isinstance(result, Exception):
            self.notify(f"PowerPoint에 붙여넣지 못했습니다: {result} 클립보드에 있으니 Ctrl+V 하세요.")
            return
        what, added, err = result
        if err:
            self.notify(f"{err} 클립보드에 복사해 두었으니 원하는 곳에 Ctrl+V 하세요.")
        elif added:
            self.notify(f"{what} PowerPoint에 붙여넣었습니다.")
        else:
            self.notify("PowerPoint가 붙여넣기를 받지 않았습니다. 클립보드에 있으니 슬라이드에서 Ctrl+V 하세요.")
