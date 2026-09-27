from capture_tool.core.fonts import FAVORITES, SEPARATOR, build_font_list


def test_FONT_01_popular_korean_fonts_first_in_order():
    installed = ["Arial", "Batang", "Gulim", "Malgun Gothic", "NanumGothic", "Consolas", "Dotum", "Gungsuh"]
    items = build_font_list(installed)
    head = items[:items.index(SEPARATOR)]
    assert [label for label, _ in head] == ["맑은 고딕", "나눔고딕", "굴림", "돋움", "바탕", "궁서"]
    assert dict(head)["맑은 고딕"] == "Malgun Gothic"


def test_FONT_02_rest_sorted_without_duplicates():
    installed = ["Consolas", "arial", "Malgun Gothic", "Batang", "Times New Roman"]
    items = build_font_list(installed)
    rest = items[items.index(SEPARATOR) + 1:]
    assert [fam for _, fam in rest] == ["arial", "Consolas", "Times New Roman"]
    assert all(fam not in ("Malgun Gothic", "Batang") for _, fam in rest)


def test_FONT_03_only_installed_favorites_are_shown():
    items = build_font_list(["Arial"])
    assert SEPARATOR not in items and items == [("Arial", "Arial")]


def test_FONT_04_localized_family_names_match():
    items = build_font_list(["맑은 고딕", "나눔명조"])
    assert items[:2] == [("맑은 고딕", "맑은 고딕"), ("나눔명조", "나눔명조")]


def test_FONT_05_empty_and_hidden_system_fonts():
    assert build_font_list([]) == []
    items = build_font_list(["@Malgun Gothic", "Malgun Gothic", "", "Arial"])
    assert all(not fam.startswith("@") and fam for _, fam in items if (_, fam) != SEPARATOR)


def test_FONT_06_favorites_table_is_sane():
    labels = [label for label, _ in FAVORITES]
    assert labels[0] == "맑은 고딕" and len(labels) == len(set(labels)) >= 10
