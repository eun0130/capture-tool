# macOS Port (scope 1: core capture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The home edition runs on an Apple Silicon Mac (area/window/full/scroll capture, editing, copy/save/PDF/print, OCR text/table copy, mail/web search, 캡처 찾기/모양으로, translation/summary) from a `.dmg` on capture_dist, while Windows behaviour and its 1,537 tests stay unchanged.

**Architecture:** `capture_tool/platform/__init__.py` becomes an OS backend selector (`backend().screen`, `.clipboard`, `.hotkey`, `.windows`, `.scroll`, `.startup`, `.secret`, `.shell`); the Windows modules stay where they are, a new `capture_tool/platform/mac/` package implements the same function names with pyobjc/Quartz/Carbon; Mac-less features (Office senders, KakaoTalk, Lens, DRM) are hidden through `edition.excluded()` exactly like the work edition hides KakaoTalk. Spec: `docs/superpowers/specs/2026-10-24-macos-port-design.md`.

**Tech Stack:** Python 3.12, PySide6, numpy, mss, pyobjc (Cocoa, Quartz), Carbon `RegisterEventHotKey` via ctypes, PyInstaller `BUNDLE`, `hdiutil`, GitHub Actions `macos-latest`.

**Three milestones.** A (Tasks 1–8) runs on the Windows PC and must leave Windows unchanged (full suite + selftest). B (Tasks 9–14) runs on the Mac (Claude Code on the Mac, same repository): the real Quartz/Carbon bodies, permissions, selftest. C (Tasks 15–17) packaging and release v0.10.0. Pytest on Windows: `.venv/Scripts/python -X utf8 -m pytest … --basetemp=<scratchpad>/pyt`; on the Mac: `.venv/bin/python -m pytest …`.

---

## File structure

| File | Responsibility |
|---|---|
| `capture_tool/platform/__init__.py` | backend selector: `name()`, `is_mac()`, `backend()`, `use(fake)` |
| `capture_tool/platform/shell.py` | Windows: `open_path`, `reveal`, `open_url` (`os.startfile`, `explorer /select,`) |
| `capture_tool/platform/mac/__init__.py` | empty |
| `capture_tool/platform/mac/screen.py` | monitors / cursor / grab; pure `flip_y`, `to_physical` |
| `capture_tool/platform/mac/clipboard.py` | NSPasteboard; pure `pasteboard_items(payload)` |
| `capture_tool/platform/mac/hotkey.py` | Carbon hot keys; pure `carbon_keys(hk)` |
| `capture_tool/platform/mac/windows.py` | window list / window_at / process_name / capture_window / bring_to_front |
| `capture_tool/platform/mac/scroll.py` | wheel / cursor / esc / exclude_from_capture / browser checks |
| `capture_tool/platform/mac/startup.py` | LaunchAgent plist; pure `plist_text(exe)` |
| `capture_tool/platform/mac/secret.py` | Keychain through `security` |
| `capture_tool/platform/mac/shell.py` | `open`, `open -R` |
| `capture_tool/platform/mac/permissions.py` | screen-recording / accessibility checks, settings pane |
| `capture_tool/edition.py` | `EXCLUDED_ON_MAC`, `excluded()` = edition ∪ OS |
| `capture_tool/core/hotkey.py` | OS labels, Mac conflicts |
| `capture_tool/core/settings.py` | `default_hotkeys()` per OS |
| `capture_tool/core/update.py` | `channel()`, Mac asset, `launch_installer` returns whether the app restarts itself |
| `capture_tool/app/{services,hotkeys,toast,overlay,controller,main}.py` | use the backend, never an OS module by name |
| `capture_tool/app/guide.py` | Mac first-run page |
| `packaging/capture_tool.spec`, `build.sh`, `.github/workflows/release.yml`, `tools/make_icon.py` | `.app`/`.dmg` |
| `tests/test_platform_backend.py`, `tests/test_mac.py`, `tests/test_mac_real.py` | selector; pure Mac logic (runs on Windows); real Mac APIs (`mac` marker) |

---

# Milestone A — Windows PC: backend selector, hiding, pure Mac logic

### Task 1: Backend selector and `shell.py`

**Files:**
- Modify: `capture_tool/platform/__init__.py` (currently empty)
- Create: `capture_tool/platform/shell.py`
- Create: `capture_tool/platform/mac/__init__.py` (empty)
- Create: `tests/test_platform_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
"""One platform package, two backends: app code asks `platform.backend()` for screen / clipboard /
hotkey / windows / scroll / startup / secret / shell and never names an OS module. CAPTURE_PLATFORM
(not in a frozen build) forces the choice for tests."""
import sys

import pytest

from capture_tool import platform as pf


def test_PB_01_the_backend_follows_the_os_and_CAPTURE_PLATFORM(monkeypatch):
    monkeypatch.delenv("CAPTURE_PLATFORM", raising=False)
    pf.use(None)
    assert pf.name() == sys.platform
    assert pf.is_mac() == (sys.platform == "darwin")
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert pf.is_mac() and pf.backend() is pf.MAC
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert not pf.is_mac() and pf.backend() is pf.WINDOWS
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert pf.name() == sys.platform                      # an installed build ignores the variable


def test_PB_02_windows_backend_maps_names_to_the_existing_modules(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    b = pf.backend()
    from capture_tool.platform import win_clipboard, win_hotkey, screen, shell
    assert b.clipboard is win_clipboard and b.hotkey is win_hotkey and b.screen is screen and b.shell is shell


def test_PB_03_mac_backend_modules_import_on_any_os(monkeypatch):
    """The Mac modules import pyobjc lazily inside functions, so the package loads on Windows."""
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    b = pf.backend()
    for n in ("screen", "clipboard", "hotkey", "windows", "scroll", "startup", "secret", "shell"):
        assert getattr(b, n).__name__ == f"capture_tool.platform.mac.{n}"


def test_PB_04_use_swaps_the_backend_for_tests():
    class Fake:
        pass
    before = pf.use(Fake)
    try:
        assert pf.backend() is Fake
    finally:
        pf.use(before)
    assert pf.backend() is not Fake


def test_PB_05_shell_opens_paths_and_urls_through_injected_runners(tmp_path):
    from capture_tool.platform import shell
    ran = []
    shell.open_path(tmp_path, runner=lambda p: ran.append(("start", str(p))))
    shell.reveal(tmp_path / "a.png", runner=lambda cmd: ran.append(("popen", cmd)))
    assert shell.open_url("https://x", runner=lambda u: ran.append(("url", u))) is True
    assert shell.open_url("file:///etc", runner=lambda u: ran.append(("url", u))) is False
    assert ran[0] == ("start", str(tmp_path)) and ran[1][1][:2] == ["explorer", "/select,"] and ran[2] == ("url", "https://x")
```

- [ ] **Step 2: Run them**

Run: `.venv/Scripts/python -X utf8 -m pytest tests/test_platform_backend.py -q`
Expected: FAIL (`AttributeError: module 'capture_tool.platform' has no attribute 'use'`)

- [ ] **Step 3: Implement**

`capture_tool/platform/__init__.py`:

```python
"""OS backends. App code asks `backend()` and uses its screen / clipboard / hotkey / windows /
scroll / startup / secret / shell modules; it never imports an OS module by name. Windows modules
keep their old names (win_clipboard, win_hotkey, …); the Mac ones live in platform/mac/.
CAPTURE_PLATFORM=darwin|win32 forces the choice for tests on a developer machine - never in an
installed (frozen) build."""
from __future__ import annotations

import importlib
import os
import sys


class Backend:
    """Lazy module bag: `backend().clipboard` imports the module on first use."""

    def __init__(self, package: str, names: dict[str, str]):
        self._package, self._names = package, names

    def __getattr__(self, item: str):
        if item not in self._names:
            raise AttributeError(item)
        mod = importlib.import_module(f"{self._package}.{self._names[item]}")
        setattr(self, item, mod)
        return mod


_NAMES = ("screen", "clipboard", "hotkey", "windows", "scroll", "startup", "secret", "shell")
WINDOWS = Backend("capture_tool.platform", {"screen": "screen", "clipboard": "win_clipboard", "hotkey": "win_hotkey",
                                            "windows": "windows", "scroll": "scroll", "startup": "startup",
                                            "secret": "secret", "shell": "shell"})
MAC = Backend("capture_tool.platform.mac", {n: n for n in _NAMES})
_override = None


def name() -> str:
    """'win32' or 'darwin'."""
    if not getattr(sys, "frozen", False):
        forced = os.environ.get("CAPTURE_PLATFORM", "").strip().lower()
        if forced in ("win32", "darwin"):
            return forced
    return sys.platform


def is_mac() -> bool:
    return name() == "darwin"


def backend():
    if _override is not None:
        return _override
    return MAC if is_mac() else WINDOWS


def use(b):
    """Swap the backend (tests). Returns the previous override so it can be restored."""
    global _override
    before, _override = _override, b
    return before
```

`capture_tool/platform/shell.py`:

```python
"""Windows: open a folder or file with its program, show a file in Explorer, open a web/mail link."""
from __future__ import annotations

import os
import subprocess


def open_path(path, runner=None) -> None:
    try:
        (runner or os.startfile)(str(path))
    except OSError:
        pass


def reveal(path, runner=None) -> None:
    try:
        (runner or subprocess.Popen)(["explorer", "/select,", str(path)])
    except OSError:
        pass


def open_url(url: str, runner=None) -> bool:
    """The default browser (https) or mail app (mailto:); other schemes are refused."""
    if not url.startswith(("https://", "mailto:")):
        return False
    try:
        (runner or os.startfile)(url)
        return True
    except OSError:
        return False
```

`capture_tool/platform/mac/__init__.py`: empty file. For PB_03 the eight Mac modules must exist; create each as a stub that Task 7 (pure logic) and Milestone B fill in:

```python
"""macOS <name> backend (Milestone B fills in the bodies)."""
from __future__ import annotations
```

- [ ] **Step 4: Run**

Run: `.venv/Scripts/python -X utf8 -m pytest tests/test_platform_backend.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add capture_tool/platform/__init__.py capture_tool/platform/shell.py capture_tool/platform/mac tests/test_platform_backend.py
git commit -m "feat: platform backend selector (Windows modules unchanged, platform/mac/ stubs), shell.open_path/reveal/open_url"
```

### Task 2: App layer uses the backend

**Files:**
- Modify: `capture_tool/app/services.py`
- Modify: `capture_tool/app/hotkeys.py:60-75`
- Modify: `capture_tool/app/toast.py:55-60`
- Modify: `capture_tool/app/overlay.py:560`
- Modify: `capture_tool/app/controller.py:64-110, 447-451`
- Modify: `capture_tool/app/main.py:308-345, 458`
- Test: `tests/test_platform_backend.py`

- [ ] **Step 1: Failing test — no OS module named in the app layer**

```python
def test_PB_06_app_layer_never_names_an_os_module():
    from pathlib import Path
    import re
    app = Path(__file__).resolve().parents[1] / "capture_tool" / "app"
    bad = []
    for f in app.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"from \.\.platform(?:\.(\w+))? import ([\w, ]+)", src):
            names = {m.group(1)} if m.group(1) else {n.strip() for n in m.group(2).split(",")}
            if names & {"screen", "win_clipboard", "win_hotkey", "windows", "scroll", "startup", "secret", "shell"}:
                bad.append(f"{f.name}: {m.group(0)}")
        if "os.startfile" in src or '"explorer"' in src:
            bad.append(f"{f.name}: os.startfile/explorer")
    assert bad == [], bad
```

(The Office / Kakao / Lens / security_software / printing imports stay: they are Windows-only features gated in Task 3, or Qt-only.)

- [ ] **Step 2: Run** — Expected: FAIL listing services.py, hotkeys.py, toast.py, overlay.py, controller.py, main.py.

- [ ] **Step 3: Rewrite the touch points**

`services.py` (whole file):

```python
"""Real implementations of the screen and clipboard services on top of the OS backend."""
from __future__ import annotations

import os

from .. import platform as pf


def _b():
    return pf.backend()


class RealScreen:
    def monitors(self):
        return _b().screen.monitors()

    def cursor_pos(self):
        return _b().screen.cursor_pos()

    def grab(self, rect):
        return _b().screen.grab(rect)

    # scroll capture & capture-protection checks
    def wheel(self, x, y, notches):
        _b().scroll.wheel(x, y, notches)

    def set_cursor(self, x, y):
        _b().scroll.set_cursor(x, y)

    def esc_pressed(self):
        return _b().scroll.esc_pressed()

    def display_affinity(self, hwnd):
        return _b().scroll.display_affinity(hwnd)

    def paste_into_new_browser_page(self, want):
        from ..platform import lens                       # Windows only (edition hides 'lens' on the Mac)
        return lens.paste_into_new_browser_page(want)

    def is_browser(self, hwnd):
        return _b().scroll.is_browser(hwnd)

    def browser_viewport(self, hwnd):
        return _b().scroll.browser_viewport(hwnd)

    def root_window_at(self, x, y):
        return _b().scroll.root_window_at(x, y)

    def exclude_from_capture(self, hwnd):
        return _b().scroll.exclude_from_capture(hwnd)

    def capture_window(self, hwnd, rect):
        return _b().windows.capture_window(hwnd, rect)

    def process_name(self, hwnd):
        return _b().windows.process_name(hwnd)

    def windows(self):
        try:
            return _b().windows.top_level_windows(exclude_pid=os.getpid())
        except OSError:
            return []


class RealClipboard:
    def __init__(self, hwnd=None):
        self.hwnd = hwnd

    def set(self, payload: dict) -> None:
        _b().clipboard.set_formats(payload, retries=10, delay=0.02, hwnd=self.hwnd)
```

(Keep whatever other methods `RealClipboard` has today — read the rest of the file; replace only `win_clipboard.` with `_b().clipboard.`.)

`hotkeys.py` `HotkeyWindow.__init__`:

```python
    def __init__(self):
        super().__init__()
        from .. import platform as pf
        hotkey = pf.backend().hotkey
        self.hwnd = int(self.winId())
        self.manager = HotkeyManager(
            register=lambda i, hk: hotkey.register(self.hwnd, i, hk),
            unregister=lambda i: hotkey.unregister(self.hwnd, i),
        )
        if pf.is_mac():
            hotkey.set_dispatch(self.manager.dispatch)       # Carbon calls back; no WM_HOTKEY on the Mac
```

`toast.py`: replace `from ..platform.scroll import exclude_from_capture` / `exclude_from_capture(int(self.winId()))` with

```python
                from .. import platform as pf
                pf.backend().scroll.exclude_from_capture(int(self.winId()))
```

`overlay.py:560`: `from ..platform.windows import window_at` → `from .. import platform as pf` and `window_at = pf.backend().windows.window_at`.

`controller.py`: delete `_open_url`, `_open_folder`, `_reveal_file`; in `__init__` set

```python
        from .. import platform as pf
        shell = pf.backend().shell
        self.open_url, self.reveal_file, self.open_folder = shell.open_url, shell.reveal, shell.open_path
```

`_protect`/`_unprotect` use `pf.backend().secret`; `_window_under` uses `pf.backend().windows.window_at`.

`main.py`: `_sync_startup` / `open_settings` use `pf.backend().startup`; `open_folder` ends with `pf.backend().shell.open_path(d)`; `selftest` reads the clipboard with `pf.backend().clipboard.get_format(PNG)` (check the existing call and keep its arguments).

- [ ] **Step 4: Run the whole suite** (Windows behaviour must not change)

Run: `.venv/Scripts/python -X utf8 -m pytest tests -q -x --basetemp=<scratchpad>/pyt`
Expected: all pass (1,537 + 6 new). Then `.venv/Scripts/python -X utf8 run_capture.py --selftest` → `SELFTEST OK`.

- [ ] **Step 5: Commit**

```bash
git add capture_tool/app tests/test_platform_backend.py
git commit -m "refactor: the app layer reaches the OS through platform.backend() (screen, clipboard, hotkey, windows, scroll, startup, secret, shell)"
```

### Task 3: Hide Mac-less features through `edition.excluded()`

**Files:**
- Modify: `capture_tool/edition.py`
- Modify: `capture_tool/app/controller.py:237-247`
- Modify: `capture_tool/core/bar_layout.py:56` (the `off` list) if it names `EXCLUDED_AT_WORK` directly
- Test: `tests/test_edition.py`

- [ ] **Step 1: Failing tests**

```python
@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")


def test_ED_10_the_mac_has_no_office_kakao_lens_or_drm(mac, monkeypatch):
    monkeypatch.delenv("CAPTURE_EDITION", raising=False)
    edition.reset()
    assert set(edition.excluded()) == {"ppt", "ppt_shapes", "ppt_merge", "excel", "word", "kakao", "lens", "drm"}
    assert not edition.has("ppt") and not edition.has_kakao() and edition.has("mail") and edition.has("search_web")
    from capture_tool.core import bar_layout as bl
    assert "ppt" not in bl.available() and "pdf" in bl.available() and "print" in bl.available()


def test_ED_11_the_work_edition_on_windows_is_unchanged(work):
    edition.reset()
    assert set(edition.excluded()) == set(edition.EXCLUDED_AT_WORK)


def test_ED_12_the_controller_makes_no_office_senders_on_the_mac(mac, make):
    c = make()
    assert c.powerpoint is None and c.excel is None and c.word is None and c.kakao is None and c.drm is None
    c.start_capture()
    assert "ppt" not in [b.name for b in c.overlays[0].side_bar.buttons()]   # adapt to the side bar's accessor
```

(For the last assertion look at `tests/test_action_bar.py::visible(sb)` and use the same helper.)

- [ ] **Step 2: Run** — Expected: FAIL (`excluded()` lacks the Mac names; controller makes the senders).

- [ ] **Step 3: Implement**

`edition.py` additions:

```python
EXCLUDED_ON_MAC = ("ppt", "ppt_shapes", "ppt_merge", "excel", "word", "kakao", "lens", "drm")
# Office COM, KakaoTalk window control, Google Lens paste and DRM detection are Windows-only; the Mac
# copies the picture to the clipboard instead (Cmd+V into Keynote / PowerPoint).


def excluded() -> tuple[str, ...]:
    """The buttons / code paths this edition on this OS leaves out."""
    from . import platform as pf
    out = EXCLUDED_AT_WORK if is_work() else ()
    if pf.is_mac():
        out = tuple(dict.fromkeys(out + EXCLUDED_ON_MAC))
    return out
```

`controller.__init__` (replace the sender block):

```python
        self.powerpoint = self.word = self.excel = self.kakao = None
        if edition.has("ppt"):
            from ..platform.powerpoint import PowerPointSender
            self.powerpoint = PowerPointSender()
        if edition.has("word"):
            from ..platform.word import WordSender
            self.word = WordSender()
        if edition.has("excel"):
            from ..platform.excel import ExcelSender
            self.excel = ExcelSender()
        if edition.has_kakao():
            from ..platform.kakao import KakaoSender
            self.kakao = KakaoSender()
        self._kakao_done.connect(self.notify)
        self._search_done.connect(self._open_search)
        self.drm = None
        if edition.has("drm"):
            from ..platform.security_software import detect_drm
            self.drm = detect_drm()
```

Then grep `self.powerpoint`, `self.word`, `self.excel` uses in controller: each send path must guard `if self.powerpoint is None: return` the way `self.kakao` already does (search `self.kakao is None` for the pattern). The module-level `from ..platform.powerpoint import (ClipboardShapes, Picture, …)` stays: `powerpoint.py` imports pywin32 only inside functions (line 181), so the import is safe on the Mac. `bar_layout.py:56`: replace `edition.EXCLUDED_AT_WORK` with `edition.excluded()` so the layout test for "buttons off" follows the OS too.

- [ ] **Step 4: Run** `tests/test_edition.py tests/test_bar_layout.py tests/test_action_bar.py tests/test_app.py -q` → pass.

- [ ] **Step 5: Commit** — `git commit -m "feat: edition.excluded() also hides Office, KakaoTalk, Lens and DRM on the Mac; the controller makes no senders for hidden buttons"`

### Task 4: Hotkey labels, Mac conflicts, per-OS defaults

**Files:**
- Modify: `capture_tool/core/hotkey.py`
- Modify: `capture_tool/core/settings.py:13-22`
- Test: `tests/test_hotkey.py`

- [ ] **Step 1: Failing tests**

```python
def test_HK_20_mac_labels_and_conflicts(monkeypatch):
    from capture_tool.core import hotkey as hk
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert str(hk.parse("cmd+shift+2")) == "Cmd + Shift + 2"
    assert str(hk.parse("option+`")) == "Option + ~"
    assert hk.known_conflicts(hk.parse("Cmd+Shift+4")) and "캡처" in hk.known_conflicts(hk.parse("Cmd+Shift+4"))[0]
    assert hk.is_reserved(hk.parse("Cmd+Q")) and hk.is_reserved(hk.parse("Cmd+Tab"))
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert str(hk.parse("cmd+shift+2")) == "Win + Shift + 2"
    assert not hk.is_reserved(hk.parse("Cmd+Q"))


def test_HK_21_default_hotkeys_per_os(monkeypatch):
    from capture_tool.core import settings as s
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert s.default_hotkeys()["capture"] == "Cmd + Shift + 2"
    assert s.Settings().hotkeys["capture"] == "Cmd + Shift + 2"
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert s.default_hotkeys()["capture"] == "Alt + ~" and s.DEFAULT_HOTKEYS["capture"] == "Alt + ~"
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement**

`core/hotkey.py`:

```python
_MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
_MOD_LABEL_MAC = {"ctrl": "Ctrl", "alt": "Option", "shift": "Shift", "win": "Cmd"}


def _labels() -> dict[str, str]:
    from .. import platform as pf
    return _MOD_LABEL_MAC if pf.is_mac() else _MOD_LABEL
```

`Hotkey.__str__` uses `_labels()`. Add the Mac tables and OS-aware lookups:

```python
_RESERVED_MAC = ["Win+Q", "Win+W", "Win+H", "Win+M", "Win+Tab", "Win+Space", "Win+`"]
_CONFLICTS_MAC = {
    "Win+Shift+3": "macOS 전체 화면 캡처 단축키와 겹칩니다.",
    "Win+Shift+4": "macOS 영역 캡처 단축키와 겹칩니다.",
    "Win+Shift+5": "macOS 스크린샷 도구 단축키와 겹칩니다.",
    "Win+Space": "Spotlight 단축키와 겹칩니다.",
    "Win+`": "같은 앱의 창 전환 단축키와 겹칩니다.",
}
_RESERVED_SET_MAC = {parse(s) for s in _RESERVED_MAC}
_CONFLICT_MAP_MAC = {parse(k): v for k, v in _CONFLICTS_MAC.items()}


def is_reserved(hk: Hotkey) -> bool:
    from .. import platform as pf
    return hk in (_RESERVED_SET_MAC if pf.is_mac() else _RESERVED_SET)


def known_conflicts(hk: Hotkey) -> list[str]:
    from .. import platform as pf
    msg = (_CONFLICT_MAP_MAC if pf.is_mac() else _CONFLICT_MAP).get(hk)
    return [msg] if msg else []
```

`core/settings.py`:

```python
DEFAULT_HOTKEYS = {"capture": "Alt + ~", "ocr": "", "shapes": "", "fullscreen": "", "scroll": "", "search": ""}
DEFAULT_HOTKEYS_MAC = {**DEFAULT_HOTKEYS, "capture": "Cmd + Shift + 2"}   # Cmd+Shift+3/4/5 belong to macOS


def default_hotkeys() -> dict:
    from .. import platform as pf
    return dict(DEFAULT_HOTKEYS_MAC if pf.is_mac() else DEFAULT_HOTKEYS)
```

and the dataclass field `hotkeys: dict = field(default_factory=default_hotkeys)`. Check line 259 (`OLD_DEFAULT_CAPTURE` migration) still reads `DEFAULT_HOTKEYS["capture"]` — on the Mac that migration never applies (fresh settings), leave it.

- [ ] **Step 4: Run** `tests/test_hotkey.py tests/test_settings.py -q` → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat: hotkeys show Cmd/Option on the Mac, Mac system shortcuts are reserved, default capture key Cmd+Shift+2"`

### Task 5: User data paths per OS

**Files:**
- Modify: `capture_tool/app/main.py:31-42`
- Modify: `capture_tool/core/model_store.py:113-116`
- Test: `tests/test_installer.py` (INST_03 pattern) — add `tests/test_mac.py::test_MAC_01`

- [ ] **Step 1: Failing test** (`tests/test_mac.py`, new file)

```python
"""Pure Mac logic that runs on any OS: paths, hotkey codes, clipboard mapping, plist, coordinates."""
from pathlib import Path

import pytest


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")


def test_MAC_01_user_data_lives_under_library_application_support(mac, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from capture_tool.app import main
    from capture_tool.core import model_store as ms
    assert main.data_dir() == tmp_path / "Library" / "Application Support" / "CaptureTool"
    assert main.log_dir() == tmp_path / "Library" / "Logs" / "CaptureTool"
    assert ms.user_root() == tmp_path / "Library" / "Application Support" / "CaptureTool" / "models"
    assert main.fallback_dir() == tmp_path / "Pictures" / "Captures"
```

- [ ] **Step 2: Run** — FAIL (Windows paths).
- [ ] **Step 3: Implement**

```python
def data_dir() -> Path:
    from .. import platform as pf
    if pf.is_mac():
        return Path.home() / "Library" / "Application Support" / APP
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP


def log_dir() -> Path:
    from .. import platform as pf
    if pf.is_mac():
        return Path.home() / "Library" / "Logs" / APP
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP
```

`model_store.user_root()`:

```python
def user_root() -> Path:
    from .. import platform as pf
    if pf.is_mac():
        return Path.home() / "Library" / "Application Support" / "CaptureTool" / "models"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "CaptureTool" / "models"
```

(keep the exact Windows expression that is there now.)

- [ ] **Step 4: Run** `tests/test_mac.py tests/test_installer.py tests/test_model_store.py -q` → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat: Mac user data under ~/Library (Application Support, Logs)"`

### Task 6: Updater knows the Mac asset

**Files:**
- Modify: `capture_tool/core/update.py:19-23, 188-193`
- Modify: `capture_tool/app/main.py:376, 437-441`
- Test: `tests/test_update.py`

- [ ] **Step 1: Failing tests**

```python
def test_UP_10_mac_channel_reads_the_dmg_from_capture_dist(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert update.channel("home") == "mac" and update.channel("work") == "mac"
    assert update.REPOS["mac"] == "eun0130/capture_dist"
    assert update.INSTALLER["mac"].format(v="1.2.3") == "CaptureTool-1.2.3-mac.dmg"
    assert update._PATTERN["mac"].match("CaptureTool-1.2.3-mac.dmg").group(1) == "1.2.3"
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert update.channel("work") == "work"


def test_UP_11_on_the_mac_the_dmg_is_opened_and_the_app_stays(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    dmg = tmp_path / "CaptureTool-1.0.0-mac.dmg"
    dmg.write_bytes(b"")
    ran = []
    assert update.launch_installer(dmg, runner=lambda cmd, **kw: ran.append(cmd)) is False
    assert ran == [["open", str(dmg)]]
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    exe = tmp_path / "CaptureTool-Setup-1.0.0.exe"
    exe.write_bytes(b"")
    assert update.launch_installer(exe, runner=lambda cmd, **kw: None) is True
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**

```python
REPOS = {"home": "eun0130/capture_dist", "work": "eun0130/capture_work", "mac": "eun0130/capture_dist"}
INSTALLER = {"home": "CaptureTool-Setup-{v}.exe", "work": "CaptureTool-Work-Setup-{v}.exe", "mac": "CaptureTool-{v}-mac.dmg"}
_PATTERN = {"home": re.compile(r"^CaptureTool-Setup-(\d+\.\d+\.\d+)\.exe$"),
            "work": re.compile(r"^CaptureTool-Work-Setup-(\d+\.\d+\.\d+)\.exe$"),
            "mac": re.compile(r"^CaptureTool-(\d+\.\d+\.\d+)-mac\.dmg$")}


def channel(edition: str) -> str:
    """Which release asset this build updates from: the Mac has one channel (home only)."""
    from .. import platform as pf
    return "mac" if pf.is_mac() else edition


def launch_installer(path: Path, runner: Callable | None = None) -> bool:
    """Start the downloaded installer. Windows: silently, a few seconds from now (the app quits
    meanwhile) and it restarts the app itself - returns True. Mac: opens the .dmg for the person to
    drag the app into Applications - returns False (the app keeps running)."""
    from .. import platform as pf
    if pf.is_mac():
        (runner or subprocess.Popen)(["open", str(path)])
        return False
    cmd = ["cmd.exe", "/c", f'ping -n 4 127.0.0.1 >nul & "{path}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES /UPDATE=1']
    (runner or subprocess.Popen)(cmd, creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)
    return True
```

`main.py:376`: `ed = update.channel(edition.current())`. `main.py` download `done`:

```python
            if update.launch_installer(result):
                self.toast("설치를 시작합니다. 잠시 뒤 새 버전으로 다시 실행됩니다.")
                if wait:
                    self.quit()
                else:
                    QTimer.singleShot(400, self.quit)
            else:
                self.toast("새 버전 디스크 이미지를 열었습니다. CaptureTool을 응용 프로그램 폴더로 끌어 넣고 다시 실행하세요.")
```

- [ ] **Step 4: Run** `tests/test_update.py -q` → pass (UP_06 still passes: Windows path unchanged).
- [ ] **Step 5: Commit** — `git commit -m "feat: updater has a mac channel (CaptureTool-<v>-mac.dmg on capture_dist); on the Mac it opens the dmg and keeps running"`

### Task 7: Pure Mac logic (testable on Windows)

**Files:**
- Modify: `capture_tool/platform/mac/{screen,clipboard,hotkey,startup}.py`
- Test: `tests/test_mac.py`

- [ ] **Step 1: Failing tests**

```python
def test_MAC_02_quartz_coordinates_flip_to_top_left_physical_pixels():
    from capture_tool.platform.mac.screen import flip_rect, to_physical
    from capture_tool.core.geometry import Rect
    # Quartz: origin bottom-left of the main display (height 900 logical); a 100x50 box whose bottom is at y=100
    assert flip_rect((10, 100, 100, 50), main_height=900) == Rect(10, 750, 100, 50)
    assert to_physical(Rect(10, 750, 100, 50), scale=2.0) == Rect(20, 1500, 200, 100)


def test_MAC_03_carbon_keys_from_a_hotkey():
    from capture_tool.core.hotkey import parse
    from capture_tool.platform.mac.hotkey import carbon_keys, UnsupportedKey
    assert carbon_keys(parse("Cmd+Shift+2")) == (0x13, 0x0100 | 0x0200)      # kVK_ANSI_2, cmdKey|shiftKey
    assert carbon_keys(parse("Ctrl+Option+`")) == (0x32, 0x1000 | 0x0800)    # kVK_ANSI_Grave, controlKey|optionKey
    assert carbon_keys(parse("F5")) == (0x60, 0)
    with pytest.raises(UnsupportedKey):
        carbon_keys(parse("Alt+PrintScreen"))


def test_MAC_04_pasteboard_items_keep_png_html_and_text_and_drop_windows_only_formats():
    from capture_tool.platform.mac.clipboard import pasteboard_items
    from capture_tool.core.clipboard_payload import DIB, GVML, HTML, PNG, UNICODE, cf_html
    html = cf_html("<b>x</b>")                                 # the CF_HTML wrapper with StartHTML offsets
    items = pasteboard_items({PNG: b"\x89PNG", DIB: b"dib", GVML: b"g", HTML: html, UNICODE: "hi"})
    assert items["public.png"] == b"\x89PNG" and items["public.utf8-plain-text"] == "hi"
    assert items["public.html"].strip().startswith("<") and "StartHTML" not in items["public.html"]
    assert "dib" not in str(items) and set(items) == {"public.png", "public.html", "public.utf8-plain-text"}


def test_MAC_05_launch_agent_plist():
    from capture_tool.platform.mac.startup import LABEL, plist_text
    text = plist_text("/Applications/CaptureTool.app/Contents/MacOS/CaptureTool")
    assert LABEL == "com.capturetool.app" and f"<string>{LABEL}</string>" in text
    assert "<string>--tray</string>" in text and "<key>RunAtLoad</key>" in text and "<true/>" in text
```

- [ ] **Step 2: Run** — FAIL (`ImportError`).
- [ ] **Step 3: Implement the pure parts** (real API bodies come in Milestone B; keep them as functions that import pyobjc inside)

`mac/screen.py`:

```python
"""macOS screen: monitors and cursor from Qt (logical px × devicePixelRatio = physical px), pictures
from mss. Quartz reports rectangles with a bottom-left origin; the app wants top-left physical px."""
from __future__ import annotations

import numpy as np

from ...core.geometry import Monitor, Rect


def flip_rect(q: tuple[float, float, float, float], main_height: float) -> Rect:
    """Quartz (x, y, w, h) with y up from the main display's bottom -> top-left logical rect."""
    x, y, w, h = q
    return Rect(int(round(x)), int(round(main_height - y - h)), int(round(w)), int(round(h)))


def to_physical(r: Rect, scale: float) -> Rect:
    return Rect(int(round(r.x * scale)), int(round(r.y * scale)), int(round(r.w * scale)), int(round(r.h * scale)))


def set_dpi_awareness() -> None:
    pass


def monitors() -> list[Monitor]:
    from PySide6.QtGui import QGuiApplication
    out = []
    primary = QGuiApplication.primaryScreen()
    for i, s in enumerate(QGuiApplication.screens()):
        g, k = s.geometry(), s.devicePixelRatio()
        out.append(Monitor(i, to_physical(Rect(g.x(), g.y(), g.width(), g.height()), k), k, s is primary, s.name()))
    return out


def cursor_pos() -> tuple[int, int]:
    from PySide6.QtGui import QCursor, QGuiApplication
    p = QCursor.pos()
    s = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
    k = s.devicePixelRatio()
    return int(round(p.x() * k)), int(round(p.y() * k))


def grab(r: Rect) -> np.ndarray:
    """BGR pixels of a physical rect (mss takes logical coordinates on the Mac and returns physical)."""
    import mss
    scale = _scale_at(r)
    with mss.mss() as sct:
        shot = sct.grab({"left": int(r.x / scale), "top": int(r.y / scale), "width": max(1, int(r.w / scale)),
                         "height": max(1, int(r.h / scale))})
    img = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3]
    if img.shape[1] != r.w or img.shape[0] != r.h:
        import cv2
        img = cv2.resize(img, (r.w, r.h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def _scale_at(r: Rect) -> float:
    for m in monitors():
        if m.rect.x <= r.x < m.rect.x + m.rect.w and m.rect.y <= r.y < m.rect.y + m.rect.h:
            return m.scale or 1.0
    return 1.0
```

`mac/hotkey.py`:

```python
"""macOS global hot keys through Carbon RegisterEventHotKey (no permission needed). The event
handler calls back `dispatch(id)` on the Qt thread through a timer poll of a queue."""
from __future__ import annotations

from ...core.hotkey import Hotkey

cmdKey, shiftKey, optionKey, controlKey = 0x0100, 0x0200, 0x0800, 0x1000
_MODS = {"win": cmdKey, "shift": shiftKey, "alt": optionKey, "ctrl": controlKey}
_VK = {"A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06, "X": 0x07, "C": 0x08, "V": 0x09,
       "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E, "R": 0x0F, "Y": 0x10, "T": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
       "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
       "O": 0x1F, "U": 0x20, "[": 0x21, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "'": 0x27, "K": 0x28, ";": 0x29,
       "\\": 0x2A, ",": 0x2B, "/": 0x2C, "N": 0x2D, "M": 0x2E, ".": 0x2F, "Tab": 0x30, "Space": 0x31, "`": 0x32,
       "Escape": 0x35, "F5": 0x60, "F6": 0x61, "F7": 0x62, "F3": 0x63, "F8": 0x64, "F9": 0x65, "F11": 0x67,
       "F13": 0x69, "F14": 0x6B, "F10": 0x6D, "F12": 0x6F, "F15": 0x71, "F4": 0x76, "F2": 0x78, "F1": 0x7A,
       "Home": 0x73, "PageUp": 0x74, "Delete": 0x75, "End": 0x77, "PageDown": 0x79, "Left": 0x7B, "Right": 0x7C,
       "Down": 0x7D, "Up": 0x7E, "Insert": 0x72}


class UnsupportedKey(ValueError):
    pass


def carbon_keys(hk: Hotkey) -> tuple[int, int]:
    """(virtual key code, modifier mask) for RegisterEventHotKey."""
    if hk.key not in _VK:
        raise UnsupportedKey(f"{hk.key} 키는 맥에서 쓸 수 없습니다.")
    mods = 0
    for m in hk.mods:
        mods |= _MODS[m]
    return _VK[hk.key], mods
```

`mac/clipboard.py`:

```python
"""macOS pasteboard. The app's payload uses Windows format names; PNG, HTML and text map to UTIs,
CF_DIB / GVML / SVG have no Mac reader and are dropped."""
from __future__ import annotations

import re

from ...core.clipboard_payload import HTML, PNG, UNICODE

_UTI = {PNG: "public.png", HTML: "public.html", UNICODE: "public.utf8-plain-text"}
_FRAGMENT = re.compile(r"<!--StartFragment-->(.*)<!--EndFragment-->", re.S)


class ClipboardBusy(OSError):
    pass


def _strip_cf_html(value) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)
    m = _FRAGMENT.search(text)
    if m:
        return m.group(1)
    i = text.find("<")
    return text[i:] if i >= 0 else text


def pasteboard_items(payload: dict) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for name, value in payload.items():
        uti = _UTI.get(name)
        if uti is None:
            continue
        if name == HTML:
            out[uti] = _strip_cf_html(value)
        elif name == UNICODE:
            out[uti] = value.decode("utf-16-le", "replace").rstrip("\x00") if isinstance(value, (bytes, bytearray)) else str(value)
        else:
            out[uti] = bytes(value)
    return out
```

(Check `cf_html` in `core/clipboard_payload.py` — if it writes `<!--StartFragment-->` markers the regex path is used; otherwise the "first `<`" path. UNICODE: see `win_clipboard._to_bytes` for whether text arrives as `str` or UTF-16 bytes and match it.)

`mac/startup.py`:

```python
"""Launch at login through a LaunchAgent (~/Library/LaunchAgents/com.capturetool.app.plist)."""
from __future__ import annotations

from pathlib import Path

LABEL = "com.capturetool.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_text(exe_path: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
        <string>--tray</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def set_enabled(enabled: bool, exe_path: str, backend=None) -> None:
    p = plist_path()
    if enabled:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(plist_text(exe_path), encoding="utf-8")
    elif p.exists():
        p.unlink()


def is_enabled(backend=None) -> bool:
    return plist_path().exists()
```

- [ ] **Step 4: Run** `tests/test_mac.py -q` → 5 passed.
- [ ] **Step 5: Commit** — `git commit -m "feat: Mac backend pure parts - coordinate flip, Carbon key table, pasteboard mapping, LaunchAgent plist"`

### Task 8: Dependencies, markers, docs, memory (end of Milestone A)

**Files:**
- Modify: `pyproject.toml:14-27, 36-40`
- Modify: `docs/test-cases.md` (new section "## v0.10.0 추가 — 맥 지원 (1단계)"), `docs/USER_GUIDE.md`, `docs/release-notes/v0.10.0.md` (new)
- Modify: `tests/conftest.py` (skip `mac` marker off the Mac, `windows` marker on the Mac)

- [ ] **Step 1: pyproject**

```toml
dependencies = [
    "PySide6>=6.8",
    "numpy>=2.0",
    "opencv-python-headless>=4.10",
    "onnxruntime>=1.20",
    "rapidocr>=3.0",
    "mss>=9.0",
    "pywin32>=306; sys_platform == 'win32'",
    "pyobjc-framework-Cocoa>=10; sys_platform == 'darwin'",
    "pyobjc-framework-Quartz>=10; sys_platform == 'darwin'",
    …
]
markers = [
    "slow: …", "timing: …",
    "windows: needs real Windows APIs",
    "mac: needs real macOS APIs (Quartz, Carbon, NSPasteboard)",
]
```

`tests/conftest.py` — add:

```python
def pytest_collection_modifyitems(config, items):
    import sys
    skip_mac = pytest.mark.skip(reason="needs macOS")
    skip_win = pytest.mark.skip(reason="needs Windows")
    for item in items:
        if "mac" in item.keywords and sys.platform != "darwin":
            item.add_marker(skip_mac)
        if "windows" in item.keywords and sys.platform == "darwin":
            item.add_marker(skip_win)
```

(If conftest already has a `pytest_collection_modifyitems`, merge into it.)

- [ ] **Step 2: docs** — test-cases rows PB-01…06, ED-10…12, HK-20/21, MAC-01…05, UP-10/11; release notes v0.10.0 draft (맥 1단계: 핵심 캡처, 우클릭 > 열기, 권한 2개, Cmd+Shift+2, 없는 기능); USER_GUIDE "맥에서" bullet. `capture_tool/__init__.py` stays 0.9.1 until Milestone C.

- [ ] **Step 3: Full suite + selftest on Windows**

Run: full pytest; `run_capture.py --selftest` → OK; `CAPTURE_EDITION=work` selftest → OK.

- [ ] **Step 4: Commit and push**

```bash
git add -A pyproject.toml tests/conftest.py docs
git commit -m "chore: OS-conditional dependencies (pywin32 / pyobjc), mac test marker, docs for the Mac port milestone A"
git push origin main
```

- [ ] **Step 5: Memory** — update `project-capture-tool.md` / add `project-mac-port.md`: backend selector, CAPTURE_PLATFORM, what runs where, Mac session next.

---

# Milestone B — on the Mac (Claude Code in the same repository)

Setup on the Mac first: `tools/mac_bootstrap.sh` does it all (Homebrew, python 3.12, `.venv`, `pip install -e .[dev]`, `tools/fetch_models.py`, Claude Code, the first `pytest -m "not windows and not mac and not slow and not timing"` run); the human steps and the agent prompt are in `docs/MAC_HANDOFF.md` (Paseo Desktop + Claude Code). The tests must pass before touching code; Windows-marked tests are skipped by Task 8's conftest.

**Already written from Windows, untested on a Mac (2026-10-25):** the bodies of Tasks 9-12, the guide page of Task 13, the packaging and CI of Tasks 15-16. On the Mac the work is: run, watch what breaks, fix with a test, commit. Two desk-check fixes landed before the handoff: `pyobjc-framework-ApplicationServices` dependency (MAC-08) and Carbon ctypes argtypes (MAC-09, `hotkey._declare`).

### Task 9: Permissions module and first-run flow

**Files:**
- Create: `capture_tool/platform/mac/permissions.py`
- Modify: `capture_tool/app/main.py` (start-up, `on_hotkey`)
- Test: `tests/test_mac_real.py` (`@pytest.mark.mac`), `tests/test_mac.py::test_MAC_06`

```python
"""Screen Recording (capture, window names) and Accessibility (scroll events) must be granted in
System Settings; this module only asks and reports."""
from __future__ import annotations

import subprocess

PANES = {"screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
         "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"}
MESSAGES = {"screen": "시스템 설정 > 개인정보 보호 및 보안 > 화면 기록에서 캡처 도구를 켜고 다시 실행하세요.",
            "accessibility": "스크롤 캡처는 시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용에서 캡처 도구를 켜야 합니다."}


def screen_recording() -> bool:
    from Quartz import CGPreflightScreenCaptureAccess
    return bool(CGPreflightScreenCaptureAccess())


def request_screen_recording() -> bool:
    from Quartz import CGRequestScreenCaptureAccess
    return bool(CGRequestScreenCaptureAccess())


def accessibility() -> bool:
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def open_settings(pane: str, runner=None) -> None:
    (runner or subprocess.Popen)(["open", PANES[pane]])
```

`main.py` after the tray is built, Mac only: if `not screen_recording()`: `request_screen_recording()`; still false → `QMessageBox` with the message and a "설정 열기" button (`open_settings("screen")`). `on_hotkey("scroll")` on the Mac without `accessibility()` → toast `MESSAGES["accessibility"]` + open the pane once. Test MAC_06 (pure): `PANES`/`MESSAGES` keys, `open_settings` runner gets `["open", url]`.

### Task 10: `mac/windows.py`

```python
"""Windows on screen through Quartz (CGWindowList). Ids are CGWindowNumbers; frames are top-left
physical px like the Windows backend."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from ...core.geometry import Rect
from .screen import flip_rect, to_physical, monitors


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: Rect
    pid: int = 0
    # keep the same field names as platform/windows.WindowInfo (check and copy them)


def _main_height_and_scale() -> tuple[float, float]:
    from PySide6.QtGui import QGuiApplication
    s = QGuiApplication.primaryScreen()
    return s.geometry().height(), s.devicePixelRatio()


def top_level_windows(exclude_pid: int | None = None) -> list[WindowInfo]:
    from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
                        kCGWindowListExcludeDesktopElements, kCGNullWindowID)
    h, k = _main_height_and_scale()
    out = []
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID) or []:
        if w.get("kCGWindowLayer", 0) != 0 or w.get("kCGWindowOwnerPID") == exclude_pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        r = to_physical(flip_rect((b["X"], h - b["Y"] - b["Height"], b["Width"], b["Height"]), h), k)
        # kCGWindowBounds is already top-left in screen points; the flip above is the identity — keep to_physical only:
        r = to_physical(Rect(int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])), k)
        if r.w < 8 or r.h < 8:
            continue
        out.append(WindowInfo(int(w["kCGWindowNumber"]), str(w.get("kCGWindowName") or w.get("kCGWindowOwnerName") or ""), r,
                              int(w.get("kCGWindowOwnerPID", 0))))
    return out            # front-most first, as CGWindowList orders them


def window_at(p, wins: list[WindowInfo]) -> WindowInfo | None:
    x, y = p
    for w in wins:
        if w.rect.x <= x < w.rect.x + w.rect.w and w.rect.y <= y < w.rect.y + w.rect.h:
            return w
    return None


def process_name(hwnd: int) -> str:
    from Quartz import CGWindowListCreateDescriptionFromArray
    for w in CGWindowListCreateDescriptionFromArray([hwnd]) or []:
        return str(w.get("kCGWindowOwnerName") or "")
    return ""


def capture_window(hwnd: int, frame: Rect):
    from Quartz import (CGWindowListCreateImage, CGRectNull, kCGWindowListOptionIncludingWindow,
                        kCGWindowImageBoundsIgnoreFraming, CGImageGetWidth, CGImageGetHeight,
                        CGImageGetDataProvider, CGDataProviderCopyData, CGImageGetBytesPerRow)
    img = CGWindowListCreateImage(CGRectNull, kCGWindowListOptionIncludingWindow, hwnd, kCGWindowImageBoundsIgnoreFraming)
    if img is None:
        return None
    w, h, stride = CGImageGetWidth(img), CGImageGetHeight(img), CGImageGetBytesPerRow(img)
    data = bytes(CGDataProviderCopyData(CGImageGetDataProvider(img)))
    arr = np.frombuffer(data, np.uint8).reshape(h, stride // 4, 4)[:, :w, :3]       # BGRA -> BGR
    return np.ascontiguousarray(arr)


def bring_to_front(hwnd: int) -> bool:
    from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
    from Quartz import CGWindowListCreateDescriptionFromArray
    for w in CGWindowListCreateDescriptionFromArray([hwnd]) or []:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(w["kCGWindowOwnerPID"]))
        return bool(app and app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
    return False
```

(Note: `kCGWindowBounds` is top-left in points already; delete the flip line when implementing — kept here so the reader sees why `flip_rect` is only for `NSEvent.mouseLocation`/NSScreen frames.) Real test (`mac` marker): `top_level_windows()` contains the test's own Qt window when not excluded, `window_at` finds it, `capture_window` returns its size.

### Task 11: `mac/clipboard.py` real bodies, `mac/scroll.py`, `mac/secret.py`, `mac/shell.py`

`clipboard.set_formats(payload, retries=5, delay=0.02, hwnd=None)`:

```python
def set_formats(payload: dict, retries: int = 5, delay: float = 0.02, hwnd=None) -> None:
    from AppKit import NSPasteboard
    from Foundation import NSData
    pb = NSPasteboard.generalPasteboard()
    items = pasteboard_items(payload)
    pb.clearContents()
    for uti, value in items.items():
        if isinstance(value, str):
            pb.setString_forType_(value, uti)
        else:
            pb.setData_forType_(NSData.dataWithBytes_length_(value, len(value)), uti)


def get_format(name: str, retries: int = 5, delay: float = 0.02) -> bytes | None:
    from AppKit import NSPasteboard
    uti = _UTI.get(name)
    if uti is None:
        return None
    d = NSPasteboard.generalPasteboard().dataForType_(uti)
    return bytes(d) if d is not None else None


def get_text() -> str | None:
    from AppKit import NSPasteboard
    s = NSPasteboard.generalPasteboard().stringForType_("public.utf8-plain-text")
    return str(s) if s is not None else None
```

`scroll.py`:

```python
from ...core.geometry import Rect
BROWSERS = ("com.apple.Safari", "com.google.Chrome", "com.microsoft.edgemac", "org.mozilla.firefox", "company.thebrowser.Browser", "com.brave.Browser")


def wheel(x: int, y: int, notches: int) -> None:
    from Quartz import CGEventCreateScrollWheelEvent, CGEventPost, kCGScrollEventUnitLine, kCGHIDEventTap
    set_cursor(x, y)
    CGEventPost(kCGHIDEventTap, CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, int(notches)))


def set_cursor(x: int, y: int) -> None:
    from Quartz import CGWarpMouseCursorPosition
    from .screen import _scale_at
    k = _scale_at(Rect(x, y, 1, 1))
    CGWarpMouseCursorPosition((x / k, y / k))


def esc_pressed() -> bool:
    from Quartz import CGEventSourceKeyState, kCGEventSourceStateHIDSystemState
    return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, 0x35))


def display_affinity(hwnd: int) -> int:
    return 0                                           # no DRM-style window protection on macOS


def exclude_from_capture(hwnd: int) -> bool:
    """`hwnd` is a Qt winId = NSView pointer: set its window's sharingType to none."""
    import objc
    from AppKit import NSView, NSWindowSharingNone
    view = objc.objc_object(c_void_p=hwnd)
    win = view.window()
    if win is None:
        return False
    win.setSharingType_(NSWindowSharingNone)
    return True


def _bundle_of(hwnd: int) -> str:
    from AppKit import NSRunningApplication
    from Quartz import CGWindowListCreateDescriptionFromArray
    for w in CGWindowListCreateDescriptionFromArray([hwnd]) or []:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(w["kCGWindowOwnerPID"]))
        return str(app.bundleIdentifier() or "") if app else ""
    return ""


def is_browser(hwnd: int) -> bool:
    return _bundle_of(hwnd) in BROWSERS


def browser_viewport(hwnd: int) -> Rect | None:
    return None                                        # the whole window; no child-window viewport on the Mac


def root_window_at(x: int, y: int) -> int:
    from .windows import top_level_windows, window_at
    w = window_at((x, y), top_level_windows())
    return w.hwnd if w else 0
```

`secret.py` (Keychain through the `security` tool; the stored "blob" is the account name):

```python
import subprocess, uuid
SERVICE = "CaptureTool"


class SecretError(Exception):
    pass


def protect(text: str) -> str:
    account = f"key-{uuid.uuid4().hex}"
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", text], capture_output=True)
    if r.returncode:
        raise SecretError(r.stderr.decode(errors="replace").strip() or "키체인에 저장하지 못했습니다.")
    return account


def unprotect(blob: str) -> str:
    r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", blob, "-w"], capture_output=True)
    if r.returncode:
        raise SecretError("키체인에서 읽지 못했습니다.")
    return r.stdout.decode().rstrip("\n")
```

`shell.py`: `open_path` → `["open", path]`, `reveal` → `["open", "-R", path]`, `open_url` → `["open", url]` with the same scheme check as Windows.

Real tests (`mac` marker): pasteboard round trip PNG+text; `wheel` does not raise when accessibility is granted (skip otherwise); `protect`/`unprotect` round trip then `security delete-generic-password` cleanup.

### Task 12: `mac/hotkey.py` real registration

```python
import ctypes, ctypes.util, queue, threading
_carbon = None
_refs: dict[int, ctypes.c_void_p] = {}
_dispatch = None
_queue: "queue.Queue[int]" = queue.Queue()


def set_dispatch(fn) -> None:
    """Called by HotkeyWindow: start a Qt timer that drains the queue on the GUI thread."""
    global _dispatch
    _dispatch = fn
    from PySide6.QtCore import QTimer
    t = QTimer()
    t.setInterval(30)
    t.timeout.connect(_drain)
    t.start()
    _refs[-1] = t                       # keep alive


def _drain():
    while True:
        try:
            hk_id = _queue.get_nowait()
        except queue.Empty:
            return
        if _dispatch:
            _dispatch(hk_id)
```

Register with Carbon via ctypes: `EventTypeSpec{kEventClassKeyboard=0x6B657962, kEventHotKeyPressed=5}`, `InstallEventHandler(GetApplicationEventTarget(), handler, 1, &spec, NULL, NULL)` once; handler reads `GetEventParameter(event, kEventParamDirectObject='hkid', typeEventHotKeyID='hkid', …)` into `EventHotKeyID{signature, id}` and puts `id` on `_queue`; `register(hwnd, id, hk)` → `carbon_keys(hk)` → `RegisterEventHotKey(vk, mods, EventHotKeyID('CPTR', id), target, 0, &ref)` returns `True` when status == 0; `unregister` → `UnregisterEventHotKey(ref)`. `UnsupportedKey` → return False (the manager then shows the conflict message). Real test: register `Cmd+Shift+9`, post the key with `CGEventCreateKeyboardEvent`, assert the queue receives the id within 1 s.

### Task 13: Guide page, selftest, side-bar check on the Mac

- `guide.py`: page "맥에서 처음 쓰기" (권한 2개, 우클릭 > 열기, Cmd+Shift+2, 없는 기능) appended only when `platform.is_mac()`; `tools/make_quick_start.py` regenerates `docs/QUICK_START.md` (page count assertion in `test_guide` — raise the cap if needed).
- `run_capture.py --selftest` on the Mac must print `SELFTEST OK`; fix whatever it finds (likely: overlay window level above the menu bar → `Qt.Tool | WindowStaysOnTopHint`, `NSWindow.level`).
- Manual checklist (spec §9) run and ticked in `docs/test-cases.md`.

### Task 14: Commit Milestone B

Push from the Mac; on Windows pull and run the full suite again (Windows unchanged).

---

# Milestone C — packaging and release v0.10.0

### Task 15: `.app` bundle, icon, `build.sh`

- `tools/make_icon.py`: also write `assets/app.icns` (`iconutil -c icns` from a generated `app.iconset` on the Mac; skip on Windows).
- `packaging/capture_tool.spec`: after `coll`:

```python
if sys.platform == "darwin":
    app = BUNDLE(coll, name="CaptureTool.app", icon=os.path.join(ROOT, "assets", "app.icns"),
                 bundle_identifier="com.capturetool.app",
                 info_plist={"LSUIElement": True, "CFBundleShortVersionString": VERSION,
                             "NSScreenCaptureUsageDescription": "화면을 캡처하기 위해 필요합니다.",
                             "NSAppleEventsUsageDescription": "스크롤 캡처에 필요합니다.",
                             "NSHighResolutionCapable": True})
```

with `VERSION` read from `capture_tool/__init__.py`; `excludes += ["win32com", "pythoncom", "pywintypes", "capture_tool.platform.kakao", "capture_tool.platform.lens", "capture_tool.platform.excel", "capture_tool.platform.word"]` on darwin and the win32 hidden imports removed on darwin.

- `build.sh`:

```bash
#!/bin/sh
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python
[ "$1" = "--skip-tests" ] || $PY -m pytest -q -m "not windows and not slow and not timing"
$PY tools/fetch_models.py
$PY tools/make_icon.py
$PY -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/capture_tool.spec
V=$($PY -c "import capture_tool; print(capture_tool.__version__)")
codesign --force --deep -s - dist/CaptureTool.app
rm -rf dist/dmg && mkdir -p dist/dmg installer/Output
cp -R dist/CaptureTool.app dist/dmg/ && ln -s /Applications dist/dmg/Applications
hdiutil create -volname "CaptureTool $V" -srcfolder dist/dmg -ov -format UDZO "installer/Output/CaptureTool-$V-mac.dmg"
shasum -a 256 "installer/Output/CaptureTool-$V-mac.dmg" | awk '{print $1" *CaptureTool-'$V'-mac.dmg"}' > "installer/Output/CaptureTool-$V-mac.dmg.sha256"
ls -l installer/Output/*.dmg
```

- `tests/test_installer.py::test_INST_10_mac_bundle_declares_permissions_and_menu_bar_only` — read the spec text and assert the plist keys.

### Task 16: CI job

`release.yml` gains a second job `mac` (`runs-on: macos-latest`): checkout, setup-python 3.12, `pip install -e .[dev]`, fetch models (cache), tests `-m "not windows and not mac and not slow and not timing"` with `QT_QPA_PLATFORM=offscreen`, version-tag check, `./build.sh --skip-tests`, upload artifact, and on a tag: `gh release upload $tag installer/Output/*-mac.dmg* --clobber` to this repo and (with `DIST_TOKEN`) to `eun0130/capture_dist` (the Windows job creates the releases; the Mac job must `needs: build` and upload into them). `tools/publish_work.ps1` untouched.

### Task 17: Release v0.10.0

- `capture_tool/__init__.py` → `0.10.0`; `docs/release-notes/v0.10.0.md` final; `docs/bugs.md` untouched unless a bug was found; `docs/test-cases.md` manual checklist ticked.
- Windows full suite + both selftests; Mac suite + selftest.
- Commit, tag `v0.10.0`, push; watch run; verify both repos' releases hold `CaptureTool-Setup-0.10.0.exe`, `CaptureTool-Work-Setup-0.10.0.exe` (capture_work) and `CaptureTool-0.10.0-mac.dmg` (capture_dist). Install on the Mac by hand (우클릭 > 열기); on Windows only after the user's explicit approval for this version.
