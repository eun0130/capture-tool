"""Pure Mac logic that runs on any OS: user data paths, Quartz coordinate flips, the Carbon key
table, pasteboard format mapping, the LaunchAgent plist. The real Quartz / Carbon / NSPasteboard
calls are covered by tests/test_mac_real.py (mac marker) on a Mac."""
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
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert main.data_dir() == tmp_path / "Roaming" / "CaptureTool"                 # Windows unchanged


def test_MAC_02_quartz_coordinates_flip_to_top_left_physical_pixels():
    from capture_tool.core.geometry import Rect
    from capture_tool.platform.mac.screen import flip_rect, to_physical
    # Quartz / AppKit: origin at the bottom-left of the main display (900 logical px tall); a 100x50 box
    # whose bottom edge is 100 px above the bottom lies 750 px from the top
    assert flip_rect((10, 100, 100, 50), main_height=900) == Rect(10, 750, 100, 50)
    assert flip_rect((0, 0, 1440, 900), main_height=900) == Rect(0, 0, 1440, 900)
    assert to_physical(Rect(10, 750, 100, 50), scale=2.0) == Rect(20, 1500, 200, 100)
    assert to_physical(Rect(3, 3, 3, 3), scale=1.0) == Rect(3, 3, 3, 3)


def test_MAC_03_carbon_keys_from_a_hotkey():
    from capture_tool.core.hotkey import parse
    from capture_tool.platform.mac.hotkey import UnsupportedKey, carbon_keys
    assert carbon_keys(parse("Cmd+Shift+2")) == (0x13, 0x0100 | 0x0200)          # kVK_ANSI_2, cmdKey | shiftKey
    assert carbon_keys(parse("Ctrl+Option+`")) == (0x32, 0x1000 | 0x0800)        # kVK_ANSI_Grave, controlKey | optionKey
    assert carbon_keys(parse("F5")) == (0x60, 0)
    assert carbon_keys(parse("Alt+A")) == (0x00, 0x0800)
    with pytest.raises(UnsupportedKey):
        carbon_keys(parse("Alt+PrintScreen"))                                     # no such key on a Mac keyboard


def test_MAC_04_pasteboard_items_keep_png_html_and_text_and_drop_windows_only_formats():
    from capture_tool.core.clipboard_payload import DIB, GVML, HTML, PNG, UNICODE, cf_html
    from capture_tool.platform.mac.clipboard import pasteboard_items
    items = pasteboard_items({PNG: b"\x89PNG", DIB: b"dib", GVML: b"g", HTML: cf_html("<b>x</b>"), UNICODE: "hi"})
    assert items["public.png"] == b"\x89PNG" and items["public.utf8-plain-text"] == "hi"
    assert items["public.html"] == "<b>x</b>"                                       # the CF_HTML wrapper taken off
    assert set(items) == {"public.png", "public.html", "public.utf8-plain-text"}
    assert pasteboard_items({HTML: "<p>raw</p>"})["public.html"] == "<p>raw</p>"
    assert pasteboard_items({UNICODE: "x".encode("utf-16-le") + b"\x00\x00"})["public.utf8-plain-text"] == "x"
    assert pasteboard_items({}) == {}


def test_MAC_05_launch_agent_plist(monkeypatch, tmp_path):
    from capture_tool.platform.mac import startup
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    text = startup.plist_text("/Applications/CaptureTool.app/Contents/MacOS/CaptureTool")
    assert startup.LABEL == "com.capturetool.app" and f"<string>{startup.LABEL}</string>" in text
    assert "<string>--tray</string>" in text and "<key>RunAtLoad</key>" in text and "<true/>" in text
    assert "/Applications/CaptureTool.app/Contents/MacOS/CaptureTool" in text
    assert not startup.is_enabled()
    startup.set_enabled(True, "/Applications/CaptureTool.app/Contents/MacOS/CaptureTool")
    assert startup.is_enabled() and startup.plist_path() == tmp_path / "Library" / "LaunchAgents" / "com.capturetool.app.plist"
    assert "<string>--tray</string>" in startup.plist_path().read_text(encoding="utf-8")
    startup.set_enabled(False, "/x")
    assert not startup.is_enabled() and not startup.plist_path().exists()
    startup.set_enabled(False, "/x")                                              # off twice: nothing to remove, no error


def test_MAC_06_permission_messages_and_the_first_start_check(mac, monkeypatch):
    from capture_tool.app import main
    from capture_tool.platform.mac import permissions
    monkeypatch.setattr(permissions, "screen_recording", lambda: False)
    monkeypatch.setattr(permissions, "request_screen_recording", lambda: False)
    monkeypatch.setattr(permissions, "accessibility", lambda: False)
    assert "화면 기록" in main.mac_permission_missing("screen")
    assert "손쉬운 사용" in main.mac_permission_missing("accessibility")
    asked, opened = [], []
    assert main.check_mac_permissions(ask=lambda t: asked.append(t) or True, open_settings=lambda: opened.append(1)) is False
    assert asked == [permissions.MESSAGES["screen"]] and opened == [1]
    assert main.check_mac_permissions(ask=lambda t: False, open_settings=lambda: opened.append(2)) is False
    assert opened == [1]                                                          # "나중에": nothing opened
    monkeypatch.setattr(permissions, "screen_recording", lambda: True)
    monkeypatch.setattr(permissions, "accessibility", lambda: True)
    assert main.mac_permission_missing("screen") is None and main.mac_permission_missing("accessibility") is None
    assert main.check_mac_permissions(ask=lambda t: pytest.fail("asked although granted")) is True
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert main.mac_permission_missing("screen") is None and main.check_mac_permissions() is True


def test_MAC_07_the_guide_on_the_mac(mac, monkeypatch):
    from capture_tool.app import guide
    pages = guide.pages()
    titles = [p.title for p in pages]
    assert pages[-1].title == "맥에서 처음 쓰기" and "화면 기록" in " ".join(pages[-1].steps)
    assert not any("파워포인트" in t or "카카오톡" in t for t in titles)
    assert "Option + ~" in pages[0].title and "Alt + ~" not in " ".join(s for p in pages for s in p.steps)
    assert "Shift + Cmd + 2" not in " ".join(s for p in pages for s in (p.title, p.intro, p.tip, *p.steps))
    assert "**Option + ~**" in " ".join(pages[-1].steps)
    assert not any("Ctrl + V" in s for p in pages for s in p.steps)             # Cmd + V on the Mac
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert guide.pages()[-1].title != "맥에서 처음 쓰기" and "Alt + ~" in guide.pages()[0].title


ROOT = Path(__file__).resolve().parents[1]
# pyobjc ships one pip package per framework; every framework module the Mac backend imports must
# be a darwin dependency (a missing one only shows up as ImportError on the Mac, at run time).
_PYOBJC_PACKAGE = {"AppKit": "pyobjc-framework-Cocoa", "Foundation": "pyobjc-framework-Cocoa",
                   "objc": "pyobjc-framework-Cocoa", "Quartz": "pyobjc-framework-Quartz",
                   "ApplicationServices": "pyobjc-framework-ApplicationServices"}


def test_MAC_08_every_framework_the_mac_backend_imports_is_a_darwin_dependency():
    import re
    import tomllib
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    darwin = {re.split(r"[ ><=;]", d)[0] for d in deps if "sys_platform == 'darwin'" in d}
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    hidden = spec.split("MAC_HIDDEN = ")[1].split("\n")[0]
    used = set()
    for py in (ROOT / "capture_tool" / "platform" / "mac").glob("*.py"):
        for m in re.findall(r"^\s*(?:from|import)\s+([A-Za-z]+)", py.read_text(encoding="utf-8"), re.M):
            if m in _PYOBJC_PACKAGE:
                used.add(m)
    assert {"AppKit", "Quartz", "ApplicationServices", "objc"} <= used, used
    for mod in used:
        assert _PYOBJC_PACKAGE[mod] in darwin, f"{mod} needs {_PYOBJC_PACKAGE[mod]} in pyproject (darwin)"
        assert f'"{mod}"' in hidden, f"{mod} missing from the PyInstaller MAC_HIDDEN list"
    assert not any(d.startswith("pyobjc") for d in deps if "darwin" not in d)       # never on Windows


def test_MAC_09_carbon_functions_get_argument_types_before_they_are_called():
    """ctypes without argtypes passes Python ints as 32-bit C ints: on arm64 a 64-bit EventRef or
    ByteCount is truncated and the hot key never arrives. Every Carbon function used gets its
    signature declared, pointer-sized parameters as c_void_p / POINTER, sizes as c_size_t."""
    import ctypes
    import types
    from capture_tool.platform.mac import hotkey
    lib = types.SimpleNamespace(**{n: types.SimpleNamespace() for n in hotkey.CARBON_FUNCTIONS})
    hotkey._declare(lib)
    for name in hotkey.CARBON_FUNCTIONS:
        f = getattr(lib, name)
        assert isinstance(f.argtypes, (list, tuple)), name
        assert f.restype in (ctypes.c_int32, ctypes.c_void_p), name
    assert lib.GetApplicationEventTarget.restype is ctypes.c_void_p and lib.GetApplicationEventTarget.argtypes == []
    a = lib.GetEventParameter.argtypes
    assert a[0] is ctypes.c_void_p and a[4] is ctypes.c_size_t and a[6] is ctypes.POINTER(hotkey.EventHotKeyID)
    r = lib.RegisterEventHotKey.argtypes
    assert r[:2] == [ctypes.c_uint32, ctypes.c_uint32] and r[2] is hotkey.EventHotKeyID and r[3] is ctypes.c_void_p
    assert r[5] is ctypes.POINTER(ctypes.c_void_p)
    i = lib.InstallEventHandler.argtypes
    assert i[0] is ctypes.c_void_p and i[1] is hotkey.HANDLER and i[2] is ctypes.c_size_t
    assert i[3] is ctypes.POINTER(hotkey.EventTypeSpec)
    assert lib.UnregisterEventHotKey.argtypes == [ctypes.c_void_p]
    assert ctypes.sizeof(hotkey.EventHotKeyID) == 8 and ctypes.sizeof(hotkey.EventTypeSpec) == 8


def test_MAC_10_exclude_from_capture_is_a_no_op_without_a_native_window(qt_app):
    # 오프스크린 Qt 의 winId 는 NSView 포인터가 아니다 - 그대로 objc 에 넘기면 세그폴트가 난다.
    from capture_tool.platform.mac import scroll
    assert scroll.exclude_from_capture(12345) is False


def test_MAC_11_file_link_on_the_mac_is_a_posix_path_and_file_url(mac):
    # 맥 파일 링크는 맥 경로 그대로여야 한다(Windows 역슬래시로 바꾸면 붙여넣은 경로가 깨진다).
    from pathlib import Path
    from capture_tool.core.share import file_link
    text, url = file_link(Path("/Users/eun/Pictures/캡처 1.png"))
    assert text == "/Users/eun/Pictures/캡처 1.png"
    assert url == "file:///Users/eun/Pictures/%EC%BA%A1%EC%B2%98%201.png"


def test_MAC_12_excel_paste_is_refused_on_the_mac_without_a_worker_thread(mac):
    # 맥에는 Excel COM 이 없다. 실제 경로로 들어가면 워커 스레드가 pythoncom 을 못 불러 죽고 종료 때 세그폴트가 난다.
    import threading
    from capture_tool.platform import excel
    before = threading.active_count()
    with pytest.raises(excel.ExcelMissing):
        excel.paste_into_excel()
    assert threading.active_count() == before


def test_MAC_13_every_mac_backend_module_is_bundled():
    # backend() 는 맥 모듈을 importlib 로 이름만 보고 불러서 PyInstaller 가 못 찾는다 - 빌드한 앱이
    # "No module named capture_tool.platform.mac.hotkey" 로 시작도 못 했다. spec 에 전부 적혀 있어야 한다.
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    listed = spec.split("MAC_BACKEND = ")[1].split("]")[0]
    for py in (ROOT / "capture_tool" / "platform" / "mac").glob("*.py"):
        if py.stem != "__init__":
            assert f'"capture_tool.platform.mac.{py.stem}"' in listed, f"{py.stem} missing from MAC_BACKEND"
    assert "*MAC_BACKEND" in spec.split("hiddenimports=")[1].split(")")[0] or "MAC_HIDDEN + MAC_BACKEND" in spec


def test_MAC_14_the_installed_mac_app_registers_its_login_item_at_start(mac, monkeypatch, tmp_path):
    # 맥에는 설치 프로그램 단계가 없어 로그인 항목이 설정 창에서 확인을 눌러야만 생겼다 - 설치한 앱이
    # 재시동 뒤 저절로 켜지지 않았다. 설치된 앱(frozen)이 시작할 때 설정대로 등록한다.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from capture_tool.app.main import ensure_mac_login_item
    from capture_tool.platform.mac import startup
    exe = "/Applications/CaptureTool.app/Contents/MacOS/CaptureTool"
    assert ensure_mac_login_item(True, frozen=True, exe=exe) is True
    assert exe in startup.plist_path().read_text(encoding="utf-8") and startup.is_enabled()
    moved = "/Users/x/Applications/CaptureTool.app/Contents/MacOS/CaptureTool"
    ensure_mac_login_item(True, frozen=True, exe=moved)                         # the app moved: the path follows
    assert moved in startup.plist_path().read_text(encoding="utf-8")
    startup.set_enabled(False, exe)
    assert ensure_mac_login_item(False, frozen=True, exe=exe) is False and not startup.is_enabled()   # turned off: stays off
    assert ensure_mac_login_item(True, frozen=False, exe=exe) is False and not startup.is_enabled()   # python run_capture.py: never
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert ensure_mac_login_item(True, frozen=True, exe=exe) is False                                  # Windows: the installer does it


def test_MAC_15_builds_are_signed_with_the_same_local_identity():
    # ad-hoc 서명은 빌드마다 정체가 바뀌어(cdhash) 업데이트할 때마다 화면 기록 권한을 다시 켜야 했다.
    # build.sh 는 tools/mac_signing.sh 의 고정 인증서로 서명하고, 없을 때만 ad-hoc 으로 돌아간다.
    build = (ROOT / "build.sh").read_text(encoding="utf-8")
    signing = (ROOT / "tools" / "mac_signing.sh").read_text(encoding="utf-8")
    assert "sh tools/mac_signing.sh identity" in build and 'codesign --force --deep -s "$SIGN_ID"' in build
    assert build.index('-s "$SIGN_ID"') < build.index("-s - dist/CaptureTool.app")          # ad-hoc only as the fallback
    assert "codesign -v dist/CaptureTool.app" in build
    assert "/usr/bin/openssl pkcs12 -export" in signing                  # Homebrew OpenSSL's .p12 cannot be imported
    assert "login.keychain" not in signing and "capturetool-signing.keychain-db" in signing
    assert "sh tools/mac_signing.sh setup" in (ROOT / "tools" / "mac_bootstrap.sh").read_text(encoding="utf-8")
