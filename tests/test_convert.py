from capture_tool.core.annotations import Shape
from capture_tool.core.convert import annotations_to_drawing


def test_CONV_01_user_drawn_shapes_become_native():
    anns = [
        Shape("rect", [(10, 10), (110, 60)], color="#E03131", width=4),
        Shape("ellipse", [(200, 10), (300, 80)], color="#1971C2", fill=True),
        Shape("arrow", [(110, 35), (200, 45)], color="#E03131"),
        Shape("line", [(0, 100), (50, 100)]),
        Shape("text", [(20, 120)], text="메모", color="#000000"),
        Shape("step", [(5, 5)], number=1),
        Shape("pen", [(0, 0), (5, 5), (9, 2)]),       # freehand: not converted
        Shape("mosaic", [(0, 0), (30, 30)]),           # raster effect: not converted
    ]
    shapes, conns = annotations_to_drawing(anns)
    kinds = [s.kind for s in shapes]
    assert kinds == ["rect", "ellipse", "rect", "ellipse"]  # text box + step circle
    assert shapes[0].fill is None and shapes[0].stroke == "#E03131" and shapes[0].stroke_width == 4
    assert shapes[1].fill == "#1971C2"
    assert shapes[2].text == "메모" and shapes[2].stroke is None and shapes[2].fill is None
    assert shapes[3].text == "1" and shapes[3].fill == "#E03131"
    assert [(c.arrow, c.x1, c.x2) for c in conns] == [(True, 110, 200), (False, 0, 50)]


def test_CONV_02_offset_applied():
    shapes, _ = annotations_to_drawing([Shape("rect", [(10, 10), (20, 30)])], offset=(100, 200))
    assert (shapes[0].x, shapes[0].y, shapes[0].w, shapes[0].h) == (110, 210, 10, 20)


def test_CONV_03_reversed_points_normalized():
    shapes, _ = annotations_to_drawing([Shape("rect", [(50, 60), (10, 20)])])
    assert (shapes[0].x, shapes[0].y, shapes[0].w, shapes[0].h) == (10, 20, 40, 40)


def test_CONV_04_empty():
    assert annotations_to_drawing([]) == ([], [])
