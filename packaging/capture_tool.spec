# PyInstaller spec: one-folder build (starts faster than one-file), windowed, offline OCR models bundled.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
UNUSED_MODELS = ("PP-OCRv6_det_small", "PP-OCRv6_rec_small")

datas = [d for d in collect_data_files("rapidocr") if not any(m in d[0] for m in UNUSED_MODELS)]
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    [os.path.join(ROOT, "run_capture.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=["rapidocr", "onnxruntime", "PySide6.QtSvg", "PySide6.QtNetwork"],
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
