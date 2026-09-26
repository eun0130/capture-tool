from capture_tool.core.table import to_grid, to_tsv


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


def test_two_words_same_cell_joined():
    items = [("New", 100, 50, 40, 20), ("York", 145, 50, 40, 20), ("10", 400, 50, 20, 20),
             ("Seoul", 100, 90, 60, 20), ("20", 400, 90, 20, 20)]
    assert to_grid(items) == [["New York", "10"], ["Seoul", "20"]]
