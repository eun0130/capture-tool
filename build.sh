#!/bin/sh
# Build CaptureTool on a Mac: tests -> icon -> PyInstaller (dist/CaptureTool.app) -> ad-hoc codesign
# -> installer/Output/CaptureTool-<version>-mac.dmg (+ .sha256 for the in-app updater).
# Home edition only (the work edition is Windows-only). `./build.sh --skip-tests` skips the test run.
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
if [ "$1" != "--skip-tests" ]; then
    QT_QPA_PLATFORM=offscreen $PY -m pytest -q -m "not windows and not slow and not timing"
fi
$PY tools/fetch_models.py
$PY tools/make_icon.py
rm -rf dist/CaptureTool.app dist/dmg
$PY -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/capture_tool.spec
V=$($PY -c "import capture_tool; print(capture_tool.__version__)")
codesign --force --deep -s - dist/CaptureTool.app            # ad-hoc: no developer account; "우클릭 > 열기" on first run
mkdir -p dist/dmg installer/Output
cp -R dist/CaptureTool.app dist/dmg/
ln -s /Applications dist/dmg/Applications
OUT="installer/Output/CaptureTool-$V-mac.dmg"
rm -f "$OUT" "$OUT.sha256"
hdiutil create -volname "CaptureTool $V" -srcfolder dist/dmg -ov -format UDZO "$OUT"
HASH=$(shasum -a 256 "$OUT" | awk '{print $1}')
printf '%s *CaptureTool-%s-mac.dmg\n' "$HASH" "$V" > "$OUT.sha256"
ls -l installer/Output/*-mac.dmg*
