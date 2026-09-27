from capture_tool.core.table import detect_grid, grid_from_cells, to_grid, to_tsv


def item(text, col, row, w=60, h=20, dx=0, dy=0):
    return (text, 100 + col * 150 + dx, 50 + row * 40 + dy, w, h)


def test_TBL_01_three_by_three():
    items = [item(f"r{r}c{c}", c, r) for r in range(3) for c in range(3)]
    items.reverse()  # OCR order is not guaranteed
    assert to_grid(items) == [["r0c0", "r0c1", "r0c2"], ["r1c0", "r1c1", "r1c2"], ["r2c0", "r2c1", "r2c2"]]


def test_TBL_02_missing_cell_kept_aligned():
    items = [item("품목", 0, 0), item("수량", 1, 0), item("금액", 2, 0),
             item("합계", 0, 1), item("9,000", 2, 1)]
    assert to_grid(items) == [["품목", "수량", "금액"], ["합계", "", "9,000"]]


def test_TBL_03_slightly_skewed_row():
    items = [item("a", 0, 0), item("b", 1, 0, dy=4), item("c", 2, 0, dy=7)]
    assert to_grid(items) == [["a", "b", "c"]]


def test_TBL_04_tsv_escapes():
    assert to_tsv([["a\tb", "c\nd"], ["e", ""]]) == "a b\tc d\ne\t"


def test_TBL_05_empty_and_single_line():
    assert to_grid([]) == []
    assert to_tsv([]) == ""
    assert to_grid([("hello world", 10, 10, 100, 20)]) == [["hello world"]]


# --- spreadsheet screenshots: cells come from the grid lines ------------------------------

def excel_like(rows=4, cols=3, cw=120, rh=28, x0=10, y0=10):
    import numpy as np
    img = np.full((y0 * 2 + rows * rh + 1, x0 * 2 + cols * cw + 1, 3), 255, np.uint8)
    for r in range(rows + 1):
        img[y0 + r * rh, x0:x0 + cols * cw + 1] = (212, 212, 212)
    for c in range(cols + 1):
        img[y0:y0 + rows * rh + 1, x0 + c * cw] = (212, 212, 212)
    return img, (x0, y0, cw, rh)


def test_TBL_06_detect_grid_from_spreadsheet_lines():
    img, (x0, y0, cw, rh) = excel_like()
    xs, ys = detect_grid(img)
    assert xs == [x0 + i * cw for i in range(4)]
    assert ys == [y0 + i * rh for i in range(5)]


def test_TBL_07_cells_from_grid_keep_empty_and_multiword_cells():
    xs, ys = [10, 130, 250, 370], [10, 38, 66]
    items = [("품목", 20, 15, 40, 18), ("수량", 140, 15, 40, 18), ("비고", 260, 15, 40, 18),
             ("사과", 20, 43, 40, 18), ("박스", 60, 43, 30, 18), ("12", 300, 43, 20, 18)]
    assert grid_from_cells(items, xs, ys) == [["품목", "수량", "비고"], ["사과 박스", "", "12"]]


def test_TBL_08_no_grid_in_plain_text():
    import numpy as np
    from tests.render import render_text  # noqa: F401  (plain white image with no lines)
    img = np.full((200, 400, 3), 255, np.uint8)
    img[50:52, 20:120] = 0   # an underline is not a table
    assert detect_grid(img) is None


def test_TBL_09_grid_needs_two_rows_and_two_columns():
    img, _ = excel_like(rows=1, cols=1)
    assert detect_grid(img) is None


def test_two_words_same_cell_joined():
    items = [("New", 100, 50, 40, 20), ("York", 145, 50, 40, 20), ("10", 400, 50, 20, 20),
             ("Seoul", 100, 90, 60, 20), ("20", 400, 90, 20, 20)]
    assert to_grid(items) == [["New York", "10"], ["Seoul", "20"]]
