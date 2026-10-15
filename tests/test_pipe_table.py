"""표 on a capture of text laid out with | bars (the person's monospace table): real OCR, then the
preview must already show the columns (BUG-108: it came out as one column)."""
import cv2
import numpy as np
import pytest

from capture_tool.core.ocr import OcrEngine, ocr_params
from capture_tool.core.table_split import ocr_row_lines, split_table
from tests.test_app import make  # noqa: F401 (fixture)

IMG = "tests/data/pipe_table.png"
pytestmark = pytest.mark.skipif(not ocr_params("korean"), reason="OCR models missing")


def _lines():
    return OcrEngine().recognize(cv2.imread(IMG))


def test_PIPE_01_real_ocr_rows_split_into_three_columns():
    rows_text = ocr_row_lines([(l.text, l.box) for l in _lines()])
    title, rows = split_table(rows_text, "auto")
    assert title is None
    assert rows[0] == ["열", "제목", "내용"]
    assert all(len(r) == 3 for r in rows) and len(rows) == 3          # the --- row is gone
    assert rows[1][0] == "1" and "이런 제목을" in rows[1][1]
    assert rows[2][0] == "2" and rows[2][1].startswith("xxxx")


def test_PIPE_02_the_table_button_opens_the_preview_with_the_columns(make):
    c = make(ocr=OcrEngine())
    got = {}
    c.ask_table_preview = lambda lines, parent=None: (got.setdefault("lines", lines), None)[1]
    assert c.open_image_file(IMG)
    c.on_toolbar_action("table")
    assert "lines" in got, c.messages[-3:]
    _, rows = split_table(got["lines"], "auto")
    assert rows[0] == ["열", "제목", "내용"] and len(rows[0]) == 3
