"""Release build: the installer's OCR models are fetched by tools/fetch_models.py, not by the
app (whose offline guard refuses downloads) - BUG-019."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_BUILD_01_release_workflow_fetches_models_with_the_build_tool():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "python tools/fetch_models.py" in wf
    tool = (ROOT / "tools" / "fetch_models.py").read_text(encoding="utf-8")
    assert "capture_tool.app" not in tool                     # never through the app's offline guard
