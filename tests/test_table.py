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


# --- false positives: ordinary screens must not become huge "tables" (PPT hang, v0.3.4) ----

def test_TBL_10_dark_screen_is_not_a_table():
    import numpy as np
    img = np.full((600, 900, 3), 40, np.uint8)          # dark-mode app: everything "non-white"
    img[100:110, 50:850] = 200
    assert detect_grid(img) is None


def test_TBL_11_filled_panels_are_not_grid_lines():
    import numpy as np
    img = np.full((600, 900, 3), 255, np.uint8)
    img[0:60, :] = 230                                   # title bar
    img[60:600, 0:220] = 243                             # side panel
    img[200:400, 300:800] = 180                          # picture / button block
    for y in range(80, 600, 3):                          # text-like stripes
        img[y, 240:880:2] = 90
    assert detect_grid(img) is None


def test_TBL_12_lines_packed_tighter_than_text_are_rejected():
    import numpy as np
    img = np.full((400, 400, 3), 255, np.uint8)
    for k in range(0, 400, 4):                           # hatch pattern: lines every 4 px
        img[k, :] = 200
        img[:, k] = 200
    assert detect_grid(img) is None


def test_TBL_13_grid_size_is_capped():
    img, _ = excel_like(rows=4, cols=3)
    assert detect_grid(img) is not None
    from capture_tool.core.table import MAX_ROWS, MAX_COLS
    assert MAX_ROWS <= 500 and MAX_COLS <= 60


def test_TBL_14_real_table_with_thick_header_border_still_found():
    img, (x0, y0, cw, rh) = excel_like(rows=5, cols=4)
    img[y0 + rh - 1:y0 + rh + 2, x0:x0 + 4 * cw + 1] = (120, 120, 120)   # 3 px header rule
    xs, ys = detect_grid(img)
    assert len(xs) == 5 and len(ys) == 6


def test_TBL_15_sparse_table_rejected():
    from capture_tool.core.table import table_is_plausible
    grid = [["a"] + [""] * 30] + [[""] * 31 for _ in range(40)]
    assert not table_is_plausible(grid)
    assert table_is_plausible([["품목", "수량"], ["사과", "3"], ["배", ""]])


# --- v0.6.4: real Excel screenshots (filled header, no gridlines, sheet headers, OCR noise) ----

def test_TBL_15_filled_header_row_keeps_its_borders():
    """A dark header fill swallowed the lines above and below it: header and first row vanished."""
    img, (x0, y0, cw, rh) = excel_like(rows=6, cols=5)
    img[y0:y0 + rh + 1, x0:x0 + 5 * cw + 1] = (127, 63, 31)              # filled header row
    xs, ys = detect_grid(img)
    assert len(xs) == 6 and len(ys) == 7
    assert abs(ys[0] - y0) <= 1 and abs(ys[1] - (y0 + rh)) <= 1


def test_TBL_16_filled_band_alone_is_not_a_table():
    import numpy as np
    img = np.full((300, 600, 3), 255, np.uint8)
    img[20:60, :] = (127, 63, 31)                                         # a coloured title bar only
    assert detect_grid(img) is None


# word boxes measured from a real Excel 365 screenshot with gridlines off (100%, 150% DPI)
BARE = [("품목", 7, 8, 48, 22), ("수량", 93, 8, 38, 22), ("단가", 148, 8, 39, 22), ("금액", 252, 8, 50, 22),
        ("비고", 379, 8, 38, 22),
        ("노트북", 8, 42, 66, 22), ("12", 89, 42, 22, 22), ("1,250,000", 147, 43, 90, 22),
        ("15,000,000", 254, 43, 107, 22), ("영업팀", 375, 42, 64, 22),
        ("모니터", 8, 76, 69, 22), ("30", 90, 76, 22, 22), ("320,000", 145, 77, 79, 22), ("9,600,000", 254, 77, 94, 22),
        ("키보드", 7, 110, 67, 22), ("45", 89, 110, 22, 22), ("35,000", 145, 111, 64, 22),
        ("1,575,000", 255, 111, 92, 22), ("무선", 380, 110, 37, 22),
        ("마우스", 14, 144, 58, 22), ("50", 90, 144, 22, 22), ("18,000", 146, 145, 65, 22), ("900,000", 258, 145, 72, 22),
        ("2026-10-03", 374, 145, 113, 22), ("입고", 496, 144, 46, 22),
        ("합계", 7, 178, 48, 22), ("27,075,000", 257, 179, 102, 22), ("부가세", 377, 178, 61, 22), ("별도", 453, 178, 36, 22)]
EXPECTED = [["품목", "수량", "단가", "금액", "비고"],
            ["노트북", "12", "1,250,000", "15,000,000", "영업팀"],
            ["모니터", "30", "320,000", "9,600,000", ""],
            ["키보드", "45", "35,000", "1,575,000", "무선"],
            ["마우스", "50", "18,000", "900,000", "2026-10-03 입고"],
            ["합계", "", "", "27,075,000", "부가세 별도"]]


def test_TBL_17_borderless_sheet_columns_from_gaps_across_rows():
    assert to_grid(list(reversed(BARE))) == EXPECTED


def test_TBL_18_wide_title_row_does_not_merge_columns():
    title = [("2026년 4분기 구매 내역 (단위: 원)", 7, -30, 420, 22)]
    assert to_grid(title + BARE) == [["2026년 4분기 구매 내역 (단위: 원)", "", "", "", ""]] + EXPECTED


def test_TBL_19_grid_cells_drop_border_bars_and_keep_word_order():
    xs, ys = [0, 100, 300], [0, 30, 60]
    items = [("부가세 |별도", 110, 5, 120, 20), ("|", 95, 35, 6, 20), ("입고", 230, 34, 40, 20),
             ("2026-10-03", 110, 36, 110, 20), ("a|b", 10, 5, 30, 20)]
    assert grid_from_cells(items, xs, ys) == [["a|b", "부가세 별도"], ["", "2026-10-03 입고"]]


def test_TBL_20_excel_row_and_column_headers_are_dropped():
    from capture_tool.core.table import drop_sheet_headers
    g = [["", "A", "B", "C"], ["1", "품목", "수량", "금액"], ["2", "사과", "3", "9,000"]]
    assert drop_sheet_headers(g) == [["품목", "수량", "금액"], ["사과", "3", "9,000"]]
    g = [["", "C", "D"], ["7", "x", "y"], ["8", "z", "w"]]                 # captured from column C, row 7
    assert drop_sheet_headers(g) == [["x", "y"], ["z", "w"]]
    keep = [["No", "이름"], ["1", "김"], ["2", "이"]]                       # a real numbered column stays
    assert drop_sheet_headers(keep) == keep
    keep2 = [["A", "B"], ["사과", "배"]]                                     # letters alone: not sheet headers
    assert drop_sheet_headers(keep2) == keep2
    assert drop_sheet_headers([]) == []


def test_TBL_21_single_row_neighbours_glue_only_when_close():
    items = [("New", 100, 50, 40, 20), ("York", 145, 50, 40, 20)]
    assert to_grid(items) == [["New York"]]
    far = [("이름", 100, 50, 40, 20), ("나이", 300, 50, 40, 20)]
    assert to_grid(far) == [["이름", "나이"]]


def test_TBL_22_thin_empty_row_from_a_split_fill_is_dropped_but_real_blank_rows_stay():
    xs = [0, 100, 200]
    ys = [0, 22, 34, 68, 102, 136]                     # 22..34: a sliver inside the header fill
    items = [("품목", 10, 5, 40, 15), ("수량", 110, 5, 40, 15), ("사과", 10, 40, 40, 20), ("3", 110, 40, 10, 20),
             ("배", 10, 108, 20, 20), ("5", 110, 108, 10, 20)]           # 68..102 is a real blank row
    assert grid_from_cells(items, xs, ys) == [["품목", "수량"], ["사과", "3"], ["", ""], ["배", "5"]]


def test_TBL_23_row_number_strip_and_empty_edge_are_dropped():
    from capture_tool.core.table import drop_sheet_headers
    g = [["", "1", "품목", "수량"], ["", "2", "사과", "3"], ["", "3", "배", "5"]]
    assert drop_sheet_headers(g) == [["품목", "수량"], ["사과", "3"], ["배", "5"]]


def test_TBL_24_sheet_headers_tolerate_one_unread_number():
    from capture_tool.core.table import drop_sheet_headers
    g = [["", "A", "B"], ["", "품목", "수량"], ["2", "사과", "3"], ["3", "배", "5"]]   # "1" not read (selected)
    assert drop_sheet_headers(g) == [["품목", "수량"], ["사과", "3"], ["배", "5"]]
