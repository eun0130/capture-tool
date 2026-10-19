"""User settings: tolerant load (bad fields fall back one by one), atomic save."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .color import normalize_hex
from .hotkey import HotkeyError, parse

DEFAULT_HOTKEYS = {"capture": "Alt + ~", "ocr": "", "shapes": "", "fullscreen": "", "scroll": "", "search": ""}
SETTINGS_VERSION = 2
OLD_DEFAULT_CAPTURE = "Win + ~"  # v1 default; Windows Terminal's quake mode owns it on many PCs
TOOLS = {"select", "rect", "ellipse", "line", "arrow", "curve", "pen", "text", "step", "highlight", "mosaic",
         "lasso", "symbol"}


@dataclass
class Settings:
    hotkeys: dict = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    save_dir: str = ""
    filename_pattern: str = "{yymmdd}_{time}"      # e.g. 261004_143012.png
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
    guide_shown: bool = False             # the beginner's guide popped up once on first start
    table_target: str = "excel"           # 표 button: "excel" (clipboard), "ppt" or "word" (insert)
    table_style: str = "keep"             # "keep" the capture's look or "plain" white/black
    table_quick: bool = False             # skip the 표 options dialog (use the saved choice)
    bar_expanded: bool = False           # action bar shows every button (전체) instead of the basic row
    pdf_one_page: bool = False            # PDF: split a long capture across A4 pages (True = fit to one page)
    border_thickness: int = 8             # 테두리: last chosen border width in px
    border_color: str = "#FFFFFF"         # 테두리: last chosen border colour
    border_shadow: bool = False           # 테두리: last chose to add a drop shadow
    transparent_level: int = 2            # 배경 지우기: how strongly the background is cut (1..4)
    workplace: str = "home"               # where the person is now: "home" / "work" (own bar arrangement each)
    bar_profiles: dict = field(default_factory=dict)   # {place: {"favourites": [...], "hidden": [...]}}
    last_symbol: str = "★"                # the 기호 tool's last stamp
    styled_text: bool = True             # text mode copies the text with its look (colours, background, indent)
    read_ahead: bool = True              # read the text of a chosen area in the background (instant 텍스트/표)
    show_recent: bool = True             # newest saved captures at the bottom when a capture starts
    auto_copy: bool = True               # choosing an area copies it at once (Ctrl+V without Ctrl+C)
    keep_style: bool = True              # PPT/shapes/tables keep colours and fonts (off: plain)
    mail_provider: str = ""               # gmail / naver / naverworks / daum / outlook / mailto / custom ('' = ask)
    mail_account: str = ""                # Gmail account to send from (several signed in)
    mail_custom_url: str = ""             # company mail compose address (https://, {to} {cc} {subject})
    last_highlight_color: str = "#FFE066"
    last_text_bg: str | None = None
    ai_summary_engine: str = "local"     # "local" (offline) or "cloud" (Gemini, own key)
    ai_cloud_translate: bool = False     # translate with Gemini too (better quality) when a key is set
    ai_cloud_consent: bool = False       # agreed that text is sent to Google
    ai_key: str = ""                     # Gemini key, DPAPI-encrypted (never plain text)
    ai_target_lang: str = ""             # "" = automatic (Korean <-> English)
    ai_endpoint: str = ""                # work edition: company LLM server (http(s)://host[:port]), "" = offline only
    ai_model: str = ""                   # work edition: model name the company server expects
    update_check: bool = True            # look for a newer version once a day (tray menu: 업데이트 확인)
    update_source: str = ""              # "" = this edition's GitHub releases; "owner/repo"; or a folder of installers
    update_last: str = ""                # when it last looked (ISO date-time)
    share_expiry: str = "24h"            # internet link: deleted by the host after 1h/12h/24h/72h
    share_consent: bool = False          # agreed that internet links upload the picture
    tip_count: int = 0                   # "click a title bar = whole window" tip shown this often
    catalog_enabled: bool = True         # saved captures are catalogued for 캡처 찾기
    catalog_text: bool = True            # ... including their (masked) text
    version: int = SETTINGS_VERSION


OLD_PATTERN = "Capture_{date}_{time}"     # default before v0.8.2


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
                if name == "filename_pattern" and v == OLD_PATTERN:
                    v = Settings().filename_pattern          # the old default: now starts with the date
                setattr(s, name, v)
            elif name == "image_format":
                if v not in ("png", "jpg"):
                    raise TypeError
                s.image_format = v
            elif name == "jpg_quality":
                if not _is_int(v):
                    raise TypeError
                s.jpg_quality = min(100, max(1, v))
            elif name in ("auto_save", "launch_at_startup", "redact_pii", "drm_notice_shown", "ppt_new_slide", "auto_copy", "show_recent", "styled_text", "pdf_one_page", "border_shadow", "read_ahead", "keep_style", "bar_expanded", "table_quick", "guide_shown",
                          "ai_cloud_translate", "ai_cloud_consent", "share_consent", "catalog_enabled", "catalog_text"):
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
            elif name == "border_color":
                s.border_color = normalize_hex(v)
            elif name == "border_thickness":
                if not _is_int(v):
                    raise TypeError
                s.border_thickness = min(64, max(0, v))
            elif name == "transparent_level":
                if not _is_int(v):
                    raise TypeError
                s.transparent_level = min(4, max(1, v))
            elif name == "workplace":
                from .bar_layout import WORKPLACES
                if v not in WORKPLACES:
                    raise TypeError
                s.workplace = v
            elif name == "bar_profiles":
                from .bar_layout import WORKPLACES, clean, to_dict
                if not isinstance(v, dict):
                    raise TypeError
                s.bar_profiles = {p: to_dict(clean(v[p])) for p in WORKPLACES if isinstance(v.get(p), dict)}
            elif name == "last_symbol":
                if not isinstance(v, str) or len(v) != 1 or not v.isprintable() or v.isspace():
                    raise TypeError
                s.last_symbol = v
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
            elif name == "ai_endpoint":
                from .company_llm import clean_endpoint
                if not isinstance(v, str) or len(v) > 2000:
                    raise TypeError
                s.ai_endpoint = clean_endpoint(v)
                if v.strip() and not s.ai_endpoint:
                    raise TypeError                        # not an http(s) address: dropped with a warning
            elif name == "ai_model":
                if not isinstance(v, str) or len(v) > 200:
                    raise TypeError
                s.ai_model = v.strip()
            elif name == "ai_target_lang":
                from .ai_text import LANGS
                if v != "" and v not in LANGS:
                    raise TypeError
                s.ai_target_lang = v
            elif name == "table_target":
                if v not in ("excel", "ppt", "word"):
                    raise TypeError
                s.table_target = v
            elif name == "table_style":
                if v not in ("keep", "plain"):
                    raise TypeError
                s.table_style = v
            elif name == "mail_provider":
                from .mailcompose import PROVIDERS
                if v != "" and v not in PROVIDERS:
                    raise TypeError
                s.mail_provider = v
            elif name in ("mail_account", "mail_custom_url"):
                if not isinstance(v, str) or len(v) > 2000:
                    raise TypeError
                setattr(s, name, v)
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
