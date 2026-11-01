"""Repository scripts that run on the Korean Windows PC."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_PS1_01_powershell_scripts_with_korean_start_with_a_utf8_bom():
    """BUG-133: Windows PowerShell 5.1 reads a .ps1 without a BOM in the PC's legacy code page (CP949
    on Korean Windows), so the UTF-8 title "캡처 도구 (회사용)" in tools/publish_work.ps1 reached GitHub
    as "罹≪쿂 ?꾧뎄 (?뚯궗??". With a UTF-8 BOM every PowerShell version reads the file as UTF-8."""
    files = subprocess.run(["git", "ls-files", "*.ps1", "*.psm1", "*.psd1"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    assert "tools/publish_work.ps1" in files
    bad = []
    for name in files:
        data = (ROOT / name).read_bytes()
        if any(b > 0x7F for b in data) and not data.startswith(b"\xef\xbb\xbf"):
            bad.append(name)
    assert not bad, f"save these as UTF-8 with BOM: {bad}"


def test_PS1_02_browser_tests_never_give_chrome_a_profile_under_tmp_path():
    """pytest makes tmp_path with mode 0o700 = an owner-only ACL on Windows (Python 3.12.4+); Chrome
    could use nothing inside - its profile ("데이터 디렉터리를 읽고 쓸 수 없습니다") nor the test page
    (ERR_FILE_NOT_FOUND) - so the real browser tests failed (WSCR_04) or skipped (WSCR_02/05). BUG-136."""
    import re
    text = (ROOT / "tests" / "test_scroll_real.py").read_text(encoding="utf-8")
    assert not re.search(r"tmp_path\s*/\s*f?[\"'](profile|page\.html|c\.html|report)", text)
    assert text.count("_scratch(") >= 4 and "os.makedirs(p)" in text and "_drop(work)" in text
