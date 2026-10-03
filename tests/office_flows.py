"""Real Excel / PowerPoint round trips used by test_office_real.py (run in a child process on
the real desktop). Every workbook / presentation here is created by the flow itself and closed
without saving; Excel runs as its own instance so the person's open workbooks are untouched."""
import ctypes
import os
import sys
import tempfile
import time

DATA = [["품목", "수량", "단가", "금액", "비고"],
        ["노트북", "12", "1,250,000", "15,000,000", "영업팀"],
        ["모니터", "30", "320,000", "9,600,000", ""],
        ["키보드", "45", "35,000", "1,575,000", "무선"],
        ["마우스", "50", "18,000", "900,000", "2026-10-03 입고"],
        ["합계", "", "", "27,075,000", "부가세 별도"]]


def excel_table(opts: str) -> None:
    """Excel shows DATA (variants: nogrid, bare, header-fill, headers) -> screenshot of the range
    -> our OCR + table logic -> cells compared. Prints RESULT cells_ok n/30."""
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    import mss
    import numpy as np
    import pythoncom
    import win32com.client
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.core.table import detect_grid, grid_from_cells, to_grid
    opts = set(opts.split())
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = True
    xl.ErrorCheckingOptions.NumberAsText = False
    wb = xl.Workbooks.Add()
    ws = wb.Worksheets(1)
    try:
        for r, row in enumerate(DATA, 1):
            for c, v in enumerate(row, 1):
                ws.Cells(r, c).NumberFormat = "@"
                ws.Cells(r, c).Value = v
        ws.Range("A1:E6").Columns.AutoFit()
        if "nogrid" in opts:
            xl.ActiveWindow.DisplayGridlines = False
            ws.Range("A1:E6").Borders.LineStyle = 1
        if "bare" in opts:
            xl.ActiveWindow.DisplayGridlines = False
        if "header-fill" in opts:
            ws.Range("A1:E1").Interior.Color = 0x7F3F1F
            ws.Range("A1:E1").Font.Color = 0xFFFFFF
            ws.Range("A1:E1").Font.Bold = True
        xl.ActiveWindow.Zoom = 100
        xl.WindowState = -4137
        hwnd = xl.Hwnd
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(1.5)
        win = xl.ActiveWindow
        rng = ws.Range("A1:E6")
        k = ctypes.windll.user32.GetDpiForWindow(hwnd) / 72 * win.Zoom / 100
        x1, y1 = win.PointsToScreenPixelsX(rng.Left), win.PointsToScreenPixelsY(rng.Top)
        x2, y2 = x1 + int(rng.Width * k), y1 + int(rng.Height * k)
        if "headers" in opts:                         # Excel's own A B C / 1 2 3 in the capture
            x1 -= int(30 * k)
            y1 -= int(14 * k)
        pad = 6
        with mss.mss() as sct:
            shot = np.array(sct.grab({"left": x1 - pad, "top": y1 - pad,
                                      "width": x2 - x1 + 2 * pad, "height": y2 - y1 + 2 * pad}))[:, :, :3]
    finally:
        wb.Saved = True
        wb.Close(False)
        xl.Quit()
    items = [(l.text, *l.box) for l in OcrEngine().recognize(np.ascontiguousarray(shot))]
    found = detect_grid(shot)
    grid = grid_from_cells(items, *found) if found else to_grid(items)
    ok = sum(1 for r in range(min(len(grid), 6)) for c in range(min(len(grid[r]), 5)) if grid[r][c] == DATA[r][c])
    print("GRID", grid)
    print(f"RESULT cells_ok {ok}/30")


def excel_paste() -> None:
    """Our table clipboard -> pasted into Excel: numbers stay numbers, codes keep zeros, a
    formula-looking cell stays text."""
    import pythoncom
    import win32com.client
    from capture_tool.core.clipboard_payload import text_payload
    from capture_tool.platform import win_clipboard
    grid = [["코드", "금액", "식"], ["007", "1,250,000", "=SUM(A1)"]]
    win_clipboard.set_formats(text_payload("", table=grid), retries=10, delay=0.05)
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    wb = xl.Workbooks.Add()
    ws = wb.Worksheets(1)
    try:
        ws.Range("A1").Select()
        ws.Paste()
        cells = [(ws.Cells(2, c).Formula, type(ws.Cells(2, c).Value).__name__) for c in (1, 2, 3)]
    finally:
        wb.Saved = True
        wb.Close(False)
        xl.Quit()
        win_clipboard.set_formats({"CF_UNICODETEXT": ""}, retries=10, delay=0.05)
    print("RESULT", cells)


def _rgb(h):
    return int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16)


def _hex(v):
    v = int(v)
    return "#%02X%02X%02X" % (v & 255, (v >> 8) & 255, (v >> 16) & 255)


SPEC = [(1, 60, 60, 200, 90, "#1F5FD1", "#0B3A8C", 2, "요청 접수", "#FFFFFF", 20, True),
        (5, 340, 60, 220, 90, None, "#E8730C", 3, "검토", "#E8730C", 18, False),
        (9, 640, 50, 200, 110, "#2E9E5B", None, 0, "승인", "#1A1A1A", 22, True),
        (4, 340, 260, 220, 130, "#F5C518", "#333333", 1.5, "예산 확인", "#000000", 16, False),
        (7, 640, 260, 200, 140, "#D93025", None, 0, "", "#000000", 14, False),
        (1, 60, 270, 200, 100, "#F2F2F2", "#7F7F7F", 1, "보류\n사유 기록", "#C00000", 14, False)]


def ppt_shapes() -> None:
    """PowerPoint draws styled shapes -> slide exported as a 150 % 'screenshot' -> our shape
    recognition -> pasted into a new deck -> each pasted shape's look printed as SHAPE lines."""
    import cv2
    import pythoncom
    import win32com.client
    from capture_tool.core.clipboard_payload import shapes_payload
    from capture_tool.core.drawingml import gvml_package, svg
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.core.shapes import (attach_found_text, detect, drop_doubtful_inside, split_doubtful,
                                         text_boxes_for, to_drawing)
    from capture_tool.platform import win_clipboard
    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("PowerPoint.Application")
    src = app.Presentations.Add(False)
    slide = src.Slides.Add(1, 12)
    for kind, l, t, w, h, fill, line, lw, text, tc, size, bold in SPEC:
        s = slide.Shapes.AddShape(kind, l, t, w, h)
        s.Fill.Visible = bool(fill)
        if fill:
            s.Fill.Solid()
            s.Fill.ForeColor.RGB = _rgb(fill)
        s.Line.Visible = bool(line)
        if line:
            s.Line.ForeColor.RGB = _rgb(line)
            s.Line.Weight = lw
        r = s.TextFrame.TextRange
        r.Text = text.replace("\n", "\r")
        r.Font.Color.RGB, r.Font.Size, r.Font.Bold, r.Font.Name = _rgb(tc), size, bold, "Malgun Gothic"
        s.Shadow.Visible = False
    tb = slide.Shapes.AddTextbox(1, 60, 440, 500, 50)
    r = tb.TextFrame.TextRange
    r.Text = "업무 처리 흐름"
    r.Font.Color.RGB, r.Font.Size, r.Font.Bold, r.Font.Name = _rgb("#404040"), 28, True, "Malgun Gothic"
    fd, png = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        slide.Export(png, "PNG", 1920, 1080)
        src.Saved = True
        src.Close()
        img = cv2.imread(png)
    finally:
        os.remove(png)                                   # our own temporary file
    dpi = 144
    eng = OcrEngine()
    lines = eng.recognize(img)
    scored = [(l.text, l.box, l.score) for l in lines]
    det = detect(img, text_boxes=split_doubtful(scored)[0])
    rest = attach_found_text(img, det, drop_doubtful_inside(det, scored),
                             lambda c: [(l.text, l.box) for l in eng.recognize(c)], dpi)
    det += text_boxes_for(rest, img, dpi)
    shapes, conns = to_drawing(det)
    ok, pngb = cv2.imencode(".png", img)
    win_clipboard.set_formats(shapes_payload(gvml_package(shapes, conns, dpi), svg(shapes, conns, dpi),
                                             pngb.tobytes()), retries=10, delay=0.05)
    dst = app.Presentations.Add(False)
    rng = dst.Slides.Add(1, 12).Shapes.Paste()
    try:
        for i in range(1, rng.Count + 1):
            shp = rng.Item(i)
            fill = _hex(shp.Fill.ForeColor.RGB) if shp.Fill.Visible else None
            line = _hex(shp.Line.ForeColor.RGB) if shp.Line.Visible else None
            text = ()
            if shp.HasTextFrame and shp.TextFrame.HasText:
                tr = shp.TextFrame.TextRange
                text = (tr.Text.replace("\r", "/"), _hex(tr.Font.Color.RGB), float(tr.Font.Size), bool(tr.Font.Bold))
            print("SHAPE", int(shp.AutoShapeType), fill, line, text)
    finally:
        dst.Saved = True
        dst.Close()
        win_clipboard.set_formats({"CF_UNICODETEXT": ""}, retries=10, delay=0.05)
    print("RESULT done")


def ppt_table() -> None:
    from capture_tool.core.text_table import find_text_table
    from capture_tool.platform.powerpoint import TableItem, send
    t = find_text_table("| 분기 | 매출 |\n|---|---|\n| 3분기 | 1,250억 |\n| 4분기 | 1,320억 |")
    out = {}

    def hook(pres, slide, added):
        tb = slide.Shapes(slide.Shapes.Count).Table
        out["cells"] = [[tb.Cell(r, c).Shape.TextFrame.TextRange.Text for c in range(1, tb.Columns.Count + 1)]
                        for r in range(1, tb.Rows.Count + 1)]
        pres.Saved = True
        pres.Close()
    send(TableItem(t.rows), new_presentation=True, hook=hook, timeout=60)
    print("RESULT", out.get("cells"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    globals()[sys.argv[1]](*sys.argv[2:])
