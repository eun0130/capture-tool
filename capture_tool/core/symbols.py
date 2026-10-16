"""Symbols for the 기호 tool and the text tool's picker. Every one has a glyph in Malgun Gothic
(the default font), so it renders the same in the capture and in PowerPoint; color emoji are
left out because they turn into boxes in saved images, and so are the ones Windows draws as
colour emoji whatever the font (⬅ ⌛ ⚽ …): a stamp must take the pen colour (test ST-08).
Groups are at most 72 wide so a picker tab stays small."""
from __future__ import annotations

SYMBOLS: list[tuple[str, str]] = [
    ("도형", "★☆●○◎◉■□▣▲△▼▽◆◇◈◀▷◁▶♥♡♠♤♣♧♦♢◐◑◒◓▪▫◦‣⬛⬜⬟⬢⬣"),
    ("체크·별", "✓✔✕✗✘☑☐☒※✚✛✜✠✦✧✩✪✫✬✭✮✯✰✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿❀❁❂❃❄❅❆❇❈❉❊❋"),
    ("화살표", "→←↑↓↔↕⇒⇐⇑⇓⇔⇕↗↘↙↖↩↪↰↱↲↳↴↵↶↷↺↻➔➜➝➞➟➠➡➢➣➤➩➪➫➬➭➮➯➱➲➳➴⇦⇧⇨⇩⬈⬉⬊⬋⬌⬍⤴⤵"),
    ("번호", "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳❶❷❸❹❺❻❼❽❾❿⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⒈⒉⒊⒋⒌⒍⒎⒏⒐⒑"),
    ("글자 번호", "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⒶⒷⒸⒹⒺⒻⒼⒽⒾⒿ⒜⒝⒞⒟⒠㉠㉡㉢㉣㉤㉥㉦㉧㉨㉩㉪㉫㉬㉭㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴ"),
    ("수학", "±×÷≠≒≈≡≤≥≦≧∞∴∵√∑∏∫∂∇∈∉∋⊂⊃⊆⊇∪∩∧∨¬∀∃∅∠⊥∥∝∽°′″℃℉%‰½⅓¼¾⅔⅛"),
    ("괄호", "「」『』【】《》〈〉〔〕〖〗〘〙〚〛‹›«»“”‘’"),
    ("단위", "㎜㎝㎞㎟㎠㎡㎢㎣㎤㎥㎎㎏㎍㎖㎗ℓ㎘㎳㎲㎐㎑㎒㎓㎔㎉㎈㎃㎂㎀㎾㎿㎸㎹㎷㎶㎩㎪㎫㎬㏈㏊㏄"),
    ("손·얼굴·날씨", "☚☛☜☝☞☟✌✍☺☻☹♨☀☁☂☃☄☾☽☼⚡⚠⚐⚑⚘⚙⚒⚔⚖⚜⚝⚾⛔⛽"),
    ("기타", "•·…‥‧☎☏✉✂✈✎✏✐✑✒♪♫♬♭♮♯㈜№℡™©®€¥₩£$¢§¶†‡‖♀♂☢☣☮☯☸♔♕♖♗♘♙♚♛♜♝♞♟⌘⌨⏰⏱"),
]
QUICK = "★✓✗→①※♥●▲☆"          # the 기호 tool's one-click row
DEFAULT = "★"


def all_symbols() -> list[str]:
    return [ch for _, chars in SYMBOLS for ch in chars]
