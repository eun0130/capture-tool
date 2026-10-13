"""Build-time only: download the models bundled into the installer — OCR, and the offline
Korean<->English translation packs (other languages and the summary model are downloaded by
the app on first use, after asking).

The installed app never downloads OCR models (capture_tool.core.ocr refuses missing models);
this script is how a build machine gets them once. The OCR models live on ModelScope, which is
sometimes slow/flaky from CI runners, so each file is fetched directly with retries and a long
timeout (more reliable than RapidOCR's own fetch), falling back to RapidOCR if a URL is unknown."""
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capture_tool.core import model_store as ms  # noqa: E402
from capture_tool.core import ocr  # noqa: E402

NEEDED = ocr.REQUIRED_MODELS + ocr.LATIN_MODELS
BUNDLED_PACKS = [ms.mt_pack_id("ko", "en"), ms.mt_pack_id("en", "ko")]


def _urls_for(name: str) -> list[str]:
    """Download URLs for a model file, read from RapidOCR's own model catalogue (ONNX only)."""
    import rapidocr
    y = (Path(rapidocr.__file__).parent / "default_models.yaml").read_text(encoding="utf-8")
    found = re.findall(r"model_dir:\s*(https://\S+/" + re.escape(name) + r")", y)
    seen, out = set(), []
    for u in found:
        if u.endswith(".onnx") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _download(url: str, dest: Path, attempts: int = 4) -> bool:
    for k in range(attempts):
        try:
            tmp = dest.with_suffix(dest.suffix + ".part")
            req = urllib.request.Request(url, headers={"User-Agent": "capture-tool-build"})
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if tmp.stat().st_size < 10_000:              # an error page, not a model
                tmp.unlink(missing_ok=True)
                raise OSError(f"too small ({tmp.stat().st_size} B)")
            tmp.replace(dest)
            return True
        except Exception as e:  # noqa: BLE001 - network/source hiccup: retry
            print(f"  attempt {k + 1}/{attempts} failed for {url}: {e}")
            if k < attempts - 1:
                time.sleep(5 * (k + 1))
    return False


def _fetch_ocr() -> list[str]:
    mdir = ocr.model_dir()
    mdir.mkdir(parents=True, exist_ok=True)
    for name in ocr.missing_models(NEEDED):
        urls = _urls_for(name)
        if not any(_download(u, mdir / name) for u in urls):
            print(f"direct download failed for {name}; trying RapidOCR")
            try:
                ocr._build_rapidocr(ocr.ocr_params("korean"))
                ocr._build_rapidocr(ocr.ocr_params("latin"))
            except Exception as e:  # noqa: BLE001
                print("  RapidOCR fallback failed:", e)
            break
    return ocr.missing_models(NEEDED)


def main() -> int:
    missing = _fetch_ocr()
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
