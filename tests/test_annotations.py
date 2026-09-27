import pytest

from capture_tool.core.annotations import Document, Shape


def rect(x1, y1, x2, y2, **kw):
    return Shape(kind="rect", points=[(x1, y1), (x2, y2)], **kw)


def test_ANN_01_add():
    d = Document(400, 300)
    assert d.add(rect(10, 10, 50, 50))
    assert len(d.shapes) == 1


def test_ANN_02_undo_redo():
    d = Document(400, 300)
    d.add(rect(10, 10, 50, 50))
    d.add(rect(60, 60, 90, 90))
    assert d.undo() and len(d.shapes) == 1
    assert d.redo() and len(d.shapes) == 2


def test_ANN_03_new_action_clears_redo():
    d = Document(400, 300)
    d.add(rect(10, 10, 50, 50))
    d.undo()
    d.add(rect(60, 60, 90, 90))
    assert not d.redo()
    assert len(d.shapes) == 1


def test_ANN_04_nothing_to_undo_redo():
    d = Document(400, 300)
    assert d.undo() is False
    assert d.redo() is False


def test_ANN_05_step_numbers_increment():
    d = Document(400, 300)
    nums = [d.add_step((10 * i, 10), "#E03131").number for i in range(1, 4)]
    assert nums == [1, 2, 3]


def test_ANN_06_undo_step_reuses_number():
    d = Document(400, 300)
    d.add_step((10, 10), "#E03131")
    d.add_step((20, 10), "#E03131")
    d.undo()
    assert d.add_step((30, 10), "#E03131").number == 2


def test_ANN_07_delete_middle_step_next_is_max_plus_one():
    d = Document(400, 300)
    for i in range(3):
        d.add_step((10 + i * 20, 10), "#E03131")
    d.delete(1)
    assert d.add_step((90, 10), "#E03131").number == 4


def test_ANN_08_zero_size_not_added():
    d = Document(400, 300)
    assert not d.add(rect(10, 10, 10, 10))
    assert not d.add(rect(10, 10, 11, 60))  # width < 2
    assert not d.add(Shape(kind="arrow", points=[(5, 5), (6, 6)]))
    assert d.shapes == []


def test_ANN_09_clamped_to_canvas():
    d = Document(400, 300)
    d.add(rect(-50, -50, 500, 500))
    assert d.shapes[0].points == [(0, 0), (400, 300)]


def test_ANN_10_invalid_color():
    with pytest.raises(ValueError):
        rect(1, 1, 50, 50, color="red")
    with pytest.raises(ValueError):
        rect(1, 1, 50, 50, color="#12")


def test_ANN_11_color_normalized():
    assert rect(1, 1, 50, 50, color="#f00").color == "#FF0000"


def test_ANN_12_opacity_clamped_width_validated():
    assert rect(1, 1, 50, 50, opacity=0).opacity == 0.1
    assert rect(1, 1, 50, 50, opacity=3).opacity == 1.0
    with pytest.raises(ValueError):
        rect(1, 1, 50, 50, width=0)


def test_ANN_13_empty_text_not_added():
    d = Document(400, 300)
    assert not d.add(Shape(kind="text", points=[(10, 10)], text="   "))
    assert d.add(Shape(kind="text", points=[(10, 10)], text="메모"))


def test_ANN_14_move_and_delete_undoable():
    d = Document(400, 300)
    d.add(rect(10, 10, 50, 50))
    d.move(0, 20, 5)
    assert d.shapes[0].points == [(30, 15), (70, 55)]
    d.undo()
    assert d.shapes[0].points == [(10, 10), (50, 50)]
    d.delete(0)
    assert d.shapes == []
    d.undo()
    assert len(d.shapes) == 1


def test_ANN_14b_move_clamped_inside_canvas():
    d = Document(100, 100)
    d.add(rect(10, 10, 50, 50))
    d.move(0, 500, 500)
    assert d.shapes[0].points == [(60, 60), (100, 100)]


def test_ANN_15_history_limit():
    d = Document(400, 300)
    for i in range(120):
        d.add(rect(0, 0, 10 + i % 50, 10 + i % 50))
    undone = 0
    while d.undo():
        undone += 1
    assert undone == 100
    assert len(d.shapes) == 20


def test_pen_needs_two_points_and_is_clamped():
    d = Document(100, 100)
    assert not d.add(Shape(kind="pen", points=[(5, 5)]))
    assert d.add(Shape(kind="pen", points=[(5, 5), (50, 50), (150, 50)]))
    assert d.shapes[0].points[-1] == (100, 50)


def test_unknown_kind():
    with pytest.raises(ValueError):
        Shape(kind="star", points=[(0, 0), (5, 5)])


def test_ANN_16_update_style_is_undoable():
    d = Document(400, 300)
    d.add(rect(10, 10, 50, 50, color="#E03131", width=4))
    assert d.update(0, color="#1971C2", width=12)
    assert (d.shapes[0].color, d.shapes[0].width) == ("#1971C2", 12)
    d.undo()
    assert (d.shapes[0].color, d.shapes[0].width) == ("#E03131", 4)


def test_ANN_17_update_validates():
    d = Document(400, 300)
    d.add(rect(10, 10, 50, 50))
    with pytest.raises(ValueError):
        d.update(0, color="nope")
    with pytest.raises(IndexError):
        d.update(5, width=3)
    assert d.update(0) is False  # nothing to change


def test_ANN_18_text_style_fields():
    s = Shape(kind="text", points=[(0, 0)], text="메모", font_size=300, bold=True, italic=True,
              underline=True, strike=True)
    assert s.font_size == 144 and s.bold and s.italic and s.underline and s.strike
    assert Shape(kind="text", points=[(0, 0)], text="x", font_size=1).font_size == 8


def test_ANN_20_font_family():
    assert Shape(kind="text", points=[(0, 0)], text="x").font_family == "Malgun Gothic"
    assert Shape(kind="text", points=[(0, 0)], text="x", font_family="  나눔고딕 ").font_family == "나눔고딕"
    assert Shape(kind="text", points=[(0, 0)], text="x", font_family="").font_family == "Malgun Gothic"
    assert Shape(kind="text", points=[(0, 0)], text="x", font_family=None).font_family == "Malgun Gothic"
    assert len(Shape(kind="text", points=[(0, 0)], text="x", font_family="A" * 500).font_family) <= 100


def test_ANN_19_width_range():
    assert rect(1, 1, 50, 50, width=0.5).width == 0.5
    assert rect(1, 1, 50, 50, width=200).width == 60  # clamped to the maximum


def test_bad_index():
    d = Document(100, 100)
    with pytest.raises(IndexError):
        d.delete(0)
