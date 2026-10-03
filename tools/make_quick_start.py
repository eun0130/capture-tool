"""Write docs/QUICK_START.md from the in-app guide (capture_tool/app/guide.py), so the document
and the pop-up never differ. Run after editing the guide: python tools/make_quick_start.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_tool.app.guide import as_markdown  # noqa: E402

if __name__ == "__main__":
    (ROOT / "docs" / "QUICK_START.md").write_text(as_markdown(), encoding="utf-8")
    print("docs/QUICK_START.md written")
