"""Real Excel / PowerPoint (skipped when Office is missing): Excel screenshots -> table cells,
our table pasted into Excel, an AI-style table into PowerPoint, styled shapes round trip."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]


def _installed(exe: str) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"):
            return True
    except OSError:
        return False


def flow(*args, ok=lambda o: "RESULT" in o) -> str:
    from tests.conftest import run_on_desktop
    p = str(ROOT / "tests" / "office_flows.py")
    code = f"import sys; sys.argv = {['x', *args]!r}; sys.path.insert(0, {str(ROOT)!r}); " \
           f"exec(compile(open({p!r}, encoding='utf-8').read(), {p!r}, 'exec'), " \
           f"{{'__name__': '__main__', '__file__': {p!r}}})"
    return run_on_desktop(code, ok, timeout=240)


excel = pytest.mark.skipif(not _installed("excel.exe"), reason="Excel not installed")
ppt = pytest.mark.skipif(not _installed("POWERPNT.EXE"), reason="PowerPoint not installed")


@excel
@pytest.mark.parametrize("opts", ["plain", "nogrid", "header-fill", "bare", "headers", "bare headers",
                                  "header-fill headers"])
def test_OFFICE_01_excel_screenshot_becomes_the_same_cells(opts):
    good = lambda o: "RESULT cells_ok 30/30" in o            # noqa: E731
    out = flow("excel_table", opts, ok=good)
    assert good(out), out


@excel
def test_OFFICE_02_pasted_table_keeps_codes_and_never_runs_formulas():
    out = flow("excel_paste")
    assert "('007', 'str')" in out and "('=SUM(A1)', 'str')" in out and "'float'" in out, out


@ppt
def test_OFFICE_03_ai_table_becomes_a_powerpoint_table():
    out = flow("ppt_table")
    assert "[['분기', '매출'], ['3분기', '1,250억'], ['4분기', '1,320억']]" in out, out


@ppt
def test_OFFICE_04_captured_shapes_keep_their_look_in_powerpoint():
    out = flow("ppt_shapes", ok=lambda o: "RESULT done" in o)
    shapes = [l for l in out.splitlines() if l.startswith("SHAPE")]
    want = ["SHAPE 1 #1F5FD1 #0B3A8C ('요청 접수', '#FFFFFF', 20.0, True)",
            "SHAPE 5 None #E8730C ('검토', '#E8730C', 18.0, False)",
            "SHAPE 9 #2E9E5B None ('승인', '#1A1A1A', 22.0, True)",
            "SHAPE 4 #F5C518 #333333 ('예산 확인', '#000000', 16.0, False)",
            "SHAPE 7 #D93025 None ()",
            "SHAPE 1 #F2F2F2 #7F7F7F ('보류/사유 기록', '#C00000', 14.0, False)",
            "SHAPE 1 None None ('업무 처리 흐름', '#404040', 28.0, True)"]
    for w in want:
        assert w in shapes, (w, out)


@ppt
def test_OFFICE_05_dark_table_into_powerpoint_styled_and_plain():
    styled = flow("ppt_dark_table", "1", ok=lambda o: "RESULT width" in o)
    assert "CELL (1, 1, '축', '#2F2D2B'" in styled and "CELL (2, 1, '전체 평균', '#1F1F1E'" in styled, styled
    assert "TITLE ['측정값(haiku 1회):']" in styled
    plain = flow("ppt_dark_table", "0", ok=lambda o: "RESULT width" in o)
    assert "'#2F2D2B'" not in plain and "CELL (2, 1, '전체 평균'" in plain, plain
