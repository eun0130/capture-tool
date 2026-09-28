"""Build-time only: download the models bundled into the installer — OCR, and the offline
Korean<->English translation packs (other languages and the summary model are downloaded by
the app on first use, after asking).

The installed app never downloads OCR models (capture_tool.core.ocr refuses missing models);
this script is how a build machine gets them once."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capture_tool.core import model_store as ms  # noqa: E402
from capture_tool.core import ocr  # noqa: E402

NEEDED = ocr.REQUIRED_MODELS + ocr.LATIN_MODELS
BUNDLED_PACKS = [ms.mt_pack_id("ko", "en"), ms.mt_pack_id("en", "ko")]


def main() -> int:
    if ocr.missing_models(NEEDED):
        ocr._build_rapidocr(ocr.ocr_params("korean"))   # RapidOCR downloads what it lacks
        ocr._build_rapidocr(ocr.ocr_params("latin"))
    missing = ocr.missing_models(NEEDED)
    if missing:
        print("missing after download:", ", ".join(missing))
        return 1
    print("models ready in", ocr.model_dir())
    root = ms.bundled_root()
    for pid in BUNDLED_PACKS:
        pack = ms.CATALOG[pid]
        if ms.installed_dir(pack, [root]) is None:
            ms.download(pack, root)          # verified against the pinned SHA-256
        print("translation pack ready:", pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
