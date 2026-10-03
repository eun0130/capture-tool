# PyInstaller spec: one-folder build (starts faster than one-file), windowed, offline OCR models bundled.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
UNUSED_MODELS = ("PP-OCRv6_det_small", "latin_PP-OCRv5_rec_mobile")   # v6 small reader replaces the v5 Latin one

datas = [d for d in collect_data_files("rapidocr") if not any(m in d[0] for m in UNUSED_MODELS)]
datas += collect_data_files("sacremoses")            # tokenizer rules of some translation packs
# pictures of the in-app beginner's guide (tools/make_guide_images.py)
GUIDE = os.path.join(ROOT, "capture_tool", "app", "guide_images")
datas += [(os.path.join(GUIDE, f), os.path.join("capture_tool", "app", "guide_images")) for f in os.listdir(GUIDE)]
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
                   "win32com.client", "pythoncom", "pywintypes",
                   "ctranslate2", "sentencepiece", "onnxruntime_genai", "sacremoses", "subword_nmt.apply_bpe"],
    excludes=[
        "tkinter", "matplotlib", "pytest", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtDesigner",
    ],
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
    icon=os.path.join(ROOT, "assets", "app.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CaptureTool", upx=False)
