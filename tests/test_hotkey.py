import pytest

from capture_tool.core.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    Hotkey,
    HotkeyError,
    find_duplicates,
    known_conflicts,
    is_reserved,
    parse,
)


def test_HK_01_win_tilde():
    hk = parse("Win+~")
    assert hk.mods == frozenset({"win"})
    assert hk.key == "`"
    assert hk.vk == 0xC0


@pytest.mark.parametrize(
    "text,mods,key",
    [
        ("ctrl + shift + a", {"ctrl", "shift"}, "A"),
        ("Cmd+~", {"win"}, "`"),
        ("Command+`", {"win"}, "`"),
        ("Windows + ~", {"win"}, "`"),
        ("Control+Option+1", {"ctrl", "alt"}, "1"),
        ("SHIFT+f3", {"shift"}, "F3"),
    ],
)
def test_HK_02_aliases_and_case(text, mods, key):
    hk = parse(text)
    assert hk.mods == frozenset(mods)
    assert hk.key == key


def test_HK_03_display_string():
    assert str(parse("win+`")) == "Win + ~"
    assert str(parse("shift+ctrl+a")) == "Ctrl + Shift + A"
    assert str(parse("alt+win+ctrl+shift+F12")) == "Ctrl + Alt + Shift + Win + F12"


def test_HK_04_windows_flags():
    hk = parse("Ctrl+Alt+Shift+Win+A")
    assert hk.flags == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN | MOD_NOREPEAT
    assert parse("F3").vk == 0x72
    assert parse("Ctrl+1").vk == 0x31
    assert parse("PrintScreen").vk == 0x2C


@pytest.mark.parametrize("text", ["", "   ", "Ctrl+Shift", "Win", "+"])
def test_HK_05_empty_or_only_modifiers(text):
    with pytest.raises(HotkeyError):
        parse(text)


@pytest.mark.parametrize("text", ["Ctrl+Foo", "Ctrl+A+B", "Ctrl++"])
def test_HK_06_unknown_or_two_keys(text):
    with pytest.raises(HotkeyError):
        parse(text)


def test_HK_07_plain_key_needs_modifier_except_function_keys():
    with pytest.raises(HotkeyError):
        parse("A")
    with pytest.raises(HotkeyError):
        parse("`")
    assert parse("F3").mods == frozenset()
    assert parse("PrintScreen").key == "PrintScreen"


@pytest.mark.parametrize("text", ["Win+L", "Alt+F4", "Ctrl+C", "Ctrl+V", "Alt+Tab", "Win+D", "Ctrl+Alt+Delete"])
def test_HK_08_reserved(text):
    assert is_reserved(parse(text))


def test_HK_08_not_reserved():
    assert not is_reserved(parse("Win+`"))
    assert not is_reserved(parse("Ctrl+Shift+3"))


def test_HK_09_known_conflicts():
    msgs = known_conflicts(parse("Ctrl+`"))
    assert any("VS Code" in m for m in msgs)
    assert known_conflicts(parse("Win+`")) == []


def test_HK_10_duplicates():
    b = {"capture": parse("Win+`"), "ocr": parse("Ctrl+Shift+2"), "shapes": parse("cmd+~")}
    assert find_duplicates(b) == [("capture", "shapes")]
    assert find_duplicates({"a": parse("F3")}) == []


@pytest.mark.parametrize("text", ["Win+~", "Ctrl+Shift+A", "F12", "Alt+PrintScreen", "Ctrl+Alt+Delete"])
def test_HK_11_round_trip(text):
    hk = parse(text)
    assert parse(str(hk)) == hk
    assert isinstance(hk, Hotkey)
