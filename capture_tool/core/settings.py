"""User settings: tolerant load (bad fields fall back one by one), atomic save."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .color import normalize_hex
from .hotkey import HotkeyError, parse

DEFAULT_HOTKEYS = {"capture": "Alt + ~", "ocr": "", "shapes": "", "fullscreen": "", "scroll": ""}
SETTINGS_VERSION = 2
OLD_DEFAULT_CAPTURE = "Win + ~"  # v1 default; Windows Terminal's quake mode owns it on many PCs
TOOLS = {"select", "rect", "ellipse", "line", "arrow", "curve", "pen", "text", "step", "highlight", "mosaic",
         "lasso"}


@dataclass
class Settings:
    hotkeys: dict = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    save_dir: str = ""
    filename_pattern: str = "Capture_{date}_{time}"
    image_format: str = "png"
    jpg_quality: int = 90
    auto_save: bool = False
    launch_at_startup: bool = True
    redact_pii: bool = True
    recent_colors: list = field(default_factory=list)
    last_tool: str = "rect"
    last_color: str = "#E03131"
    last_width: int = 4
    last_save_dir: str = ""
    last_font_family: str = "Malgun Gothic"
    drm_notice_shown: bool = False
    ppt_new_slide: bool = True           # PPT: insert on a new slide after the current one
    auto_copy: bool = True               # choosing an area copies it at once (Ctrl+V without Ctrl+C)
    keep_style: bool = True              # PPT/shapes/tables keep colours and fonts (off: plain)
    last_highlight_color: str = "#FFE066"
    last_text_bg: str | None = None
    ai_summary_engine: str = "local"     # "local" (offline) or "cloud" (Gemini, own key)
    ai_cloud_translate: bool = False     # translate with Gemini too (better quality) when a key is set
    ai_cloud_consent: bool = False       # agreed that text is sent to Google
    ai_key: str = ""                     # Gemini key, DPAPI-encrypted (never plain text)
    ai_target_lang: str = ""             # "" = automatic (Korean <-> English)
    share_expiry: str = "24h"            # internet link: deleted by the host after 1h/12h/24h/72h
    share_consent: bool = False          # agreed that internet links upload the picture
    tip_count: int = 0                   # "click a title bar = whole window" tip shown this often
    version: int = SETTINGS_VERSION


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _apply(s: Settings, data: dict, warnings: list[str]) -> None:
    d = Settings()
    for f in fields(Settings):
        if f.name not in data:
            continue
        v = data[f.name]
        name = f.name
        try:
            if name == "hotkeys":
                if not isinstance(v, dict):
                    raise TypeError
                hk = dict(DEFAULT_HOTKEYS)
                for action in DEFAULT_HOTKEYS:
                    if action not in v:
                        continue
                    text = v[action]
                    if text == "":
                        hk[action] = ""
                        continue
                    try:
                        hk[action] = str(parse(text))
                    except (HotkeyError, AttributeError, TypeError):
                        warnings.append(f"단축키 '{action}' 값이 잘못되어 기본값으로 되돌렸습니다: {text!r}")
                s.hotkeys = hk
            elif name == "version":
                if not _is_int(v):
                    raise TypeError
                s.version = SETTINGS_VERSION
            elif name == "last_font_family":
                if not isinstance(v, str) or not v.strip():
                    raise TypeError
                s.last_font_family = v.strip()[:100]
            elif name in ("save_dir", "filename_pattern", "last_save_dir"):
                if not isinstance(v, str):
                    raise TypeError
                setattr(s, name, v)
            elif name == "image_format":
                if v not in ("png", "jpg"):
                    raise TypeError
                s.image_format = v
            elif name == "jpg_quality":
                if not _is_int(v):
                    raise TypeError
                s.jpg_quality = min(100, max(1, v))
            elif name in ("auto_save", "launch_at_startup", "redact_pii", "drm_notice_shown", "ppt_new_slide", "auto_copy", "keep_style",
                          "ai_cloud_translate", "ai_cloud_consent", "share_consent"):
                if not isinstance(v, bool):
                    raise TypeError
                setattr(s, name, v)
            elif name == "recent_colors":
                if not isinstance(v, list):
                    raise TypeError
                out: list[str] = []
                for c in v:
                    try:
                        c = normalize_hex(c)
                    except ValueError:
                        continue
                    if c not in out:
                        out.append(c)
                s.recent_colors = out[:8]
            elif name == "last_tool":
                if v not in TOOLS:
                    raise TypeError
                s.last_tool = v
            elif name == "last_color":
                s.last_color = normalize_hex(v)
            elif name == "share_expiry":
                from .share import EXPIRIES
                if v not in EXPIRIES:
                    raise TypeError
                s.share_expiry = v
            elif name == "tip_count":
                if not _is_int(v):
                    raise TypeError
                s.tip_count = max(0, min(100, v))
            elif name == "ai_summary_engine":
                if v not in ("local", "cloud"):
                    raise TypeError
                s.ai_summary_engine = v
            elif name == "ai_key":
                if not isinstance(v, str) or len(v) > 4096:
                    raise TypeError
                s.ai_key = v
            elif name == "ai_target_lang":
                from .ai_text import LANGS
                if v != "" and v not in LANGS:
                    raise TypeError
                s.ai_target_lang = v
            elif name == "last_highlight_color":
                s.last_highlight_color = normalize_hex(v)
            elif name == "last_text_bg":
                s.last_text_bg = None if v is None else normalize_hex(v)
            elif name == "last_width":
                if not _is_int(v):
                    raise TypeError
                s.last_width = min(50, max(1, v))
        except (TypeError, ValueError):
            setattr(s, name, getattr(d, name))
            warnings.append(f"설정 '{name}' 값이 잘못되어 기본값으로 되돌렸습니다: {v!r}")


def load(path) -> tuple[Settings, list[str]]:
    path = Path(path)
    s = Settings()
    warnings: list[str] = []
    if not path.exists():
        return s, warnings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root is not an object")
    except (ValueError, UnicodeDecodeError) as e:
        bak = path.with_name(path.name + ".bak")
        os.replace(path, bak)
        warnings.append(f"설정 파일이 손상되어 기본값으로 시작합니다. 원본: {bak.name} ({e})")
        return s, warnings
    _apply(s, data, warnings)
    old = data.get("version", 1)
    if _is_int(old) and old < 2 and s.hotkeys.get("capture") == OLD_DEFAULT_CAPTURE:
        s.hotkeys["capture"] = DEFAULT_HOTKEYS["capture"]
        warnings.append(f"기본 캡처 단축키가 {DEFAULT_HOTKEYS['capture']} 로 바뀌었습니다. "
                        "(Win + ~ 는 Windows Terminal과 겹칩니다. 설정에서 다시 바꿀 수 있습니다.)")
    return s, warnings


def save(s: Settings, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(s), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
