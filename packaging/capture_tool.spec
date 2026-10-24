# PyInstaller spec: one-folder build (starts faster than one-file), windowed, offline OCR models bundled.
# On macOS the folder is wrapped into CaptureTool.app (menu-bar app, permission texts) - build.sh.
import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
MAC = sys.platform == "darwin"
with open(os.path.join(ROOT, "capture_tool", "__init__.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'__version__ = "([^"]+)"', _f.read()).group(1)
UNUSED_MODELS = ("PP-OCRv6_det_small", "latin_PP-OCRv5_rec_mobile")   # v6 small reader replaces the v5 Latin one

datas = [d for d in collect_data_files("rapidocr") if not any(m in d[0] for m in UNUSED_MODELS)]
datas += collect_data_files("sacremoses")            # tokenizer rules of some translation packs
# pictures of the in-app beginner's guide (tools/make_guide_images.py)
GUIDE = os.path.join(ROOT, "capture_tool", "app", "guide_images")
datas += [(os.path.join(GUIDE, f), os.path.join("capture_tool", "app", "guide_images")) for f in os.listdir(GUIDE)]
# edition marker (build.ps1 -Edition work writes it for the 회사용 build; absent = 집용)
EDITION = os.path.join(ROOT, "capture_tool", "edition.txt")
WORK_EXCLUDES = ["capture_tool.platform.kakao", "capture_tool.app.mail_ui",            # not even in the 회사용 bundle
                 "capture_tool.core.websearch", "capture_tool.platform.lens", "capture_tool.core.gemini"]
excludes = [
    "tkinter", "matplotlib", "pytest", "IPython",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtDesigner",
]
if os.path.exists(EDITION):
    datas.append((EDITION, "capture_tool"))
    excludes += WORK_EXCLUDES
MAC_EXCLUDES = ["win32com", "pythoncom", "pywintypes", "win32api", "win32gui", "win32con", "winreg",
                "capture_tool.platform.kakao", "capture_tool.platform.lens", "capture_tool.platform.excel",
                "capture_tool.platform.word", "capture_tool.platform.security_software"]
WIN_HIDDEN = ["win32com.client", "pythoncom", "pywintypes"]
MAC_HIDDEN = ["AppKit", "Foundation", "Quartz", "ApplicationServices", "objc"]
if MAC:
    excludes += MAC_EXCLUDES
binaries = collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime_genai")

# offline Korean<->English translation packs (tools/fetch_models.py), marker files included
AI = os.path.join(ROOT, "ai_models")
for pack in ("mt-ko_en", "mt-en_ko"):
    for base, _, files in os.walk(os.path.join(AI, pack)):
        for f in files:
            datas.append((os.path.join(base, f), os.path.join("ai_models", os.path.relpath(base, AI))))

a = Analysis(
    [os.path.join(ROOT, "run_capture.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=["rapidocr", "onnxruntime", "PySide6.QtSvg", "PySide6.QtNetwork",
                   *(MAC_HIDDEN if MAC else WIN_HIDDEN),
                   "ctranslate2", "sentencepiece", "onnxruntime_genai", "sacremoses", "subword_nmt.apply_bpe"],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CaptureTool",
    console=False,
    icon=os.path.join(ROOT, "assets", "app.icns" if MAC else "app.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CaptureTool", upx=False)
if MAC:
    app = BUNDLE(
        coll,
        name="CaptureTool.app",
        icon=os.path.join(ROOT, "assets", "app.icns"),
        bundle_identifier="com.capturetool.app",
        info_plist={
            "CFBundleName": "CaptureTool",
            "CFBundleDisplayName": "캡처 도구",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSUIElement": True,                               # menu-bar app: no Dock icon
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "NSScreenCaptureUsageDescription": "화면을 캡처하기 위해 화면 기록 권한이 필요합니다.",
            "NSAppleEventsUsageDescription": "스크롤 캡처에서 화면을 넘기기 위해 필요합니다.",
        },
    )
