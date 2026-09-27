"""Build-time only: download the OCR model files that get bundled into the installer.

The installed app never downloads anything (capture_tool.core.ocr refuses missing models);
this script is how a build machine gets them once."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capture_tool.core import ocr  # noqa: E402

NEEDED = ocr.REQUIRED_MODELS + ocr.LATIN_MODELS


def main() -> int:
    if ocr.missing_models(NEEDED):
        ocr._build_rapidocr(ocr.ocr_params("korean"))   # RapidOCR downloads what it lacks
        ocr._build_rapidocr(ocr.ocr_params("latin"))
    missing = ocr.missing_models(NEEDED)
    if missing:
        print("missing after download:", ", ".join(missing))
        return 1
    print("models ready in", ocr.model_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
