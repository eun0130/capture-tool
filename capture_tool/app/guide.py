"""Beginner's guide. One source for the pop-up window in the app (도움말 button, F1, tray menu,
first start) and for docs/QUICK_START.md (tools/make_quick_start.py writes it; a test keeps
the two identical)."""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QTextBrowser, QVBoxLayout, QWidget


@dataclass(frozen=True)
class Page:
    title: str
    intro: str
    steps: tuple[str, ...]
    tip: str = ""
    image: str = ""            # picture under the steps (guide_images/, docs/images/guide/)
    caption: str = ""


IMAGES = Path(__file__).with_name("guide_images")


def image_path(name: str) -> Path:
    return IMAGES / name


PAGES = (
    Page("1. 캡처하기 — Alt + ~",
         "화면의 원하는 부분을 찍어 바로 붙여 넣는 기본 사용법입니다.",
         ("키보드에서 **Alt** 를 누른 채 **~** (숫자 1 왼쪽 키)를 누릅니다. 화면이 살짝 어두워집니다.",
          "찍고 싶은 곳을 마우스로 **끌어서** 네모를 그립니다. 창 하나를 통째로 찍으려면 그 창의 **제목 줄을 한 번 클릭**하세요.",
          "다 그리면 **그 순간 복사**됩니다. 카카오톡·메일·문서에 가서 **Ctrl + V** 하면 붙습니다.",
          "취소하려면 **Esc** 를 누릅니다."),
         "단축키는 설정에서 바꿀 수 있습니다. 화면 오른쪽 아래 트레이의 캡처 도구 아이콘을 눌러도 시작됩니다.",
         "capture.png", "표를 골랐을 때: 파란 네모가 고른 곳, 바로 아래가 버튼 막대, 그 아래가 그리기 도구"),
    Page("2. 아래 버튼 막대 한눈에",
         "캡처하면 바로 아래에 버튼이 한 줄로 나옵니다.",
         ("**복사**: 복사하고 캡처 화면을 닫습니다 (Enter, Ctrl+C 도 같음).",
          "**자동저장**: 파랗게 눌려 있으면 캡처할 때마다 저장 폴더에 파일로도 저장됩니다. 누를 때마다 켜고 끕니다.",
          "**텍스트**: 그림 속 글자를 읽어 복사합니다. **표**: 그림 속 표를 칸 그대로 복사합니다.",
          "**PPT**: 파워포인트 새 슬라이드에 넣습니다. **메일** · **카톡** · **검색**: 아래 각 장을 보세요.",
          "**고정**: 캡처를 화면 위에 띄워 둡니다. **전체**: 나머지 버튼(다른 이름 저장 · 도형PPT · 스크롤 · 링크 · 저장 폴더 · 도움말)을 펼칩니다."),
         "버튼 위에 마우스를 잠시 올리면 설명이 나옵니다.",
         "bar_full.png", "전체를 누르면 둘째 줄이 펼쳐집니다 (다시 누르면 기본)"),
    Page("3. 그림 그리기 · 글자 넣기",
         "붙이기 전에 표시를 하고 싶을 때.",
         ("캡처 아래의 그리기 도구에서 **네모 · 원 · 화살표 · 펜 · 글자(T) · 번호 · 형광펜 · 모자이크** 중 하나를 고릅니다.",
          "캡처 위에서 끌어서 그립니다. 색과 굵기는 도구 막대 오른쪽에서 바꿉니다.",
          "잘못 그렸으면 **Ctrl + Z** (되돌리기). 그린 것도 클립보드 복사본에 같이 들어갑니다."),
         ""),
    Page("4. 표를 엑셀·PPT·워드로",
         "화면의 표(엑셀, 웹 페이지, 어두운 화면의 표도)를 고칠 수 있는 진짜 표로 옮깁니다.",
         ("표가 보이게 캡처하고 **표** 버튼을 누릅니다. 아래에 \"표를 읽는 중\"이 뜨고 1~2초 뒤 결과가 나옵니다.",
          "처음에는 **어디에 붙일지**(엑셀에 넣기 / PPT에 넣기 / 워드에 넣기)와 **모양**(캡처 모양 그대로 / 흰 바탕·검은 글씨)을 고릅니다.",
          "엑셀이 열려 있으면 **선택한 칸에**, 닫혀 있으면 **엑셀을 열어 새 문서에** 바로 붙습니다. PPT·워드도 바로 들어갑니다.",
          "보내고 나면 캡처 화면이 닫히고 엑셀·PPT·워드가 앞에 보입니다. 터미널처럼 선 문자로 그린 표, 줄바꿈된 칸도 됩니다.",
          "표 모양이 아닌 글이면 **미리보기**가 떠서, 칸을 나누는 방법을 고르고 칸을 고친 뒤 붙일 수 있습니다.",
          "나중에 바꾸려면 **표** 버튼 옆 **▾** 를 누르세요."),
         "\"다음부터 이 설정으로 바로\"를 켜 두면 표 버튼 한 번에 끝납니다.",
         "table_options.png", "처음 표 버튼을 누르면 나오는 창: 붙일 곳과 모양을 고릅니다"),
    Page("5. 글자 복사 · 번역 · 요약",
         "그림 속 글자를 글로 옮기고, 번역하거나 요약합니다.",
         ("캡처하고 **텍스트** 를 누르면 글자가 바로 복사됩니다.",
          "일부만 필요하면 그 글자 위를 **끌어서** 고르면 그 부분만 복사됩니다.",
          "아래 막대의 **번역** 또는 **요약** 을 누르면 결과 창이 뜹니다. 결과 창에서 **복사** · **PPT로** · **표로 복사** 를 고릅니다."),
         "번역·요약은 기본으로 이 PC 안에서만 처리되어 글이 밖으로 나가지 않습니다."),
    Page("6. 파워포인트로 보내기",
         "",
         ("**PPT** 를 누르면 캡처가 파워포인트의 **새 슬라이드**에 들어가고 파워포인트가 앞으로 나옵니다.",
          "**도형PPT** (전체 안)는 캡처 속 상자·화살표·글자를 **고칠 수 있는 도형**으로 바꿔 넣습니다.",
          "웹 화면의 입력칸·버튼·체크 상자는 제자리에 도형으로, 표는 **고칠 수 있는 PowerPoint 표**로, 아이콘은 작은 그림으로 들어갑니다.",
          "표 위에 번호·상자 등을 그려 두었다면, 표는 PowerPoint 표로, 그린 표시는 그 위에 같은 자리로 들어갑니다.",
          "파워포인트가 없거나 응답이 없으면 클립보드에 넣어 두니 직접 Ctrl+V 하세요."),
         "설정에서 \"새 슬라이드에 넣기\"를 끄면 보고 있는 슬라이드에 넣습니다."),
    Page("7. 메일로 보내기 (네이버 · Gmail 등)",
         "캡처 도구가 메일을 대신 보내지는 않습니다. 쓰기 화면까지 준비해 주고, 보내기는 직접 누릅니다.",
         ("캡처하고 **메일** 을 누릅니다.",
          "받는 사람을 고릅니다: **자주 · 최근 · 그룹 · 전체 주소록** 에서 체크하고, 사람마다 **받는 사람 / 참조** 를 정합니다. 새 주소는 위 칸에 쓰고 Enter.",
          "맨 위 **보낼 메일** 에서 **네이버 메일** 또는 **Gmail** 을 누르고(다른 메일은 옆 목록), **메일 쓰기** 를 누릅니다.",
          "브라우저에 메일 쓰기 화면이 열립니다. 네이버·Gmail은 받는 사람과 제목이 이미 채워져 있습니다.",
          "본문을 누르고 **Ctrl + V** 하면 캡처가 붙습니다. 칸이 비어 있으면 오른쪽 **도우미 창**의 \"다시 복사\"로 받는 사람·참조·제목을 하나씩 붙일 수 있습니다.",
          "확인하고 메일의 **[보내기]** 를 직접 누릅니다."),
         "로그인 화면이 나오면 로그인한 뒤 계속하세요. 주소록은 [주소·그룹 편집]에서 추가·삭제하고, 이 PC에만 암호화되어 저장됩니다.",
         "mail_helper.png", "메일 쓰기 화면 옆에 뜨는 도우미 창: 위에서부터 눌러 차례로 붙여 넣습니다"),
    Page("8. 카카오톡으로 보내기",
         "",
         ("카카오톡에서 보낼 채팅방을 **따로 창으로 열어 둡니다**.",
          "캡처하고 **카톡** 을 누르면 열려 있는 채팅방 목록이 나옵니다. 채팅방을 고르세요.",
          "그 채팅방에 캡처가 붙어 들어가고 카카오톡의 확인 창이 뜹니다. **[전송]** 을 눌러야 보내집니다."),
         "채팅방이 목록에 없으면 \"카카오톡 열기\"를 골라 채팅방에서 Ctrl+V 하세요."),
    Page("9. 검색 (구글 · 네이버)",
         "",
         ("캡처하고 **검색** 을 누릅니다.",
          "**그림으로 찾기**: 구글 렌즈의 **이미지로 검색** 창이 열리고 캡처가 **저절로 붙어** 찾습니다(안 붙으면 그 창에서 **Ctrl + V**). 네이버는 PC에서 그림 검색을 지원하지 않습니다.",
          "**글자로 찾기**: 캡처 속 글자를 읽어 구글·네이버 검색이나 파파고 번역을 바로 엽니다."),
         "그림은 직접 붙여 넣기 전에는 어디에도 올라가지 않습니다."),
    Page("10. 화면에 고정하기 (여러 장)",
         "자료를 보면서 작업할 때 캡처를 다른 창 위에 띄워 둡니다.",
         ("캡처하고 **고정** 을 누른 뒤 띄울 곳을 고릅니다: **찍은 자리 그대로(F3)** · **오른쪽 위에 쌓기** · **다른 모니터로**.",
          "여러 장을 계속 고정할 수 있습니다. 끌어서 옮기고, 마우스 휠로 크기를 바꿉니다.",
          "고정한 그림에 마우스를 올리면 작은 막대가 나옵니다: **50%**(반투명) · **+ / −** · **복사** · **✕**.",
          "여러 장을 한꺼번에 정리하려면 고정 메뉴의 **고정한 캡처 관리** 를 여세요(나란히 · 모두 숨기기 · 모두 닫기)."),
         "", "pin.png", "고정한 캡처에 마우스를 올리면 오른쪽 위에 작은 막대가 나옵니다"),
    Page("11. 긴 화면 찍기 (스크롤)",
         "웹 페이지나 PDF처럼 화면보다 긴 내용을 한 장으로 찍습니다.",
         ("캡처할 때 브라우저 창의 **제목 줄을 클릭**해 창 전체를 고르거나, 찍을 부분을 네모로 고릅니다.",
          "**전체** → **스크롤** 을 누르면 자동으로 아래로 내려가며 찍습니다. 멈추려면 **Esc**.",
          "끝나면 편집 창이 열려 그리기·텍스트·PPT 등을 똑같이 쓸 수 있습니다."),
         ""),
    Page("12. 저장한 캡처 · 그림 파일 다시 쓰기",
         "다시 캡처하지 않고, 저장해 둔 캡처나 아무 그림 파일을 열어 표·텍스트·PPT·메일 버튼을 그대로 씁니다.",
         ("**Alt + ~** 로 캡처를 시작하면 아래에 **최근 캡처**(자동저장한 것) 8장이 보입니다. 하나를 누르면 열립니다.",
          "열린 창에서 캡처할 때와 같은 버튼(표·텍스트·도형PPT·메일·고정…)을 씁니다. 다시 저장되지는 않습니다.",
          "다른 그림 파일은 그 줄이나 열린 창에 **끌어다 놓거나**, 파일을 오른쪽 클릭 → **보내기 → 캡처 도구**.",
          "트레이 아이콘 메뉴의 **이미지 열기…** 로 골라도 됩니다. 영역을 고르기 시작하면 최근 캡처 줄은 사라집니다."),
         "최근 캡처 줄이 필요 없으면 줄 오른쪽 위 ✕ (이번만) 또는 설정에서 끕니다.",
         "recent.png", "캡처를 시작하면 나오는 최근 캡처 줄: 눌러서 다시 쓰기"),
    Page("13. 저장 · 링크 · 설정",
         "",
         ("**전체** → **다른 이름 저장**: 위치를 골라 파일로 저장합니다. **저장 폴더**: 저장된 파일이 있는 폴더를 엽니다.",
          "**전체** → **링크**: 저장한 파일의 위치 링크, 또는 정해진 시간 뒤 지워지는 인터넷 공유 링크를 복사합니다.",
          "트레이 아이콘을 오른쪽 클릭 → **설정** 에서 단축키, 저장 폴더, 메일, 모양(색·글꼴 그대로) 등을 바꿉니다."),
         "이 설명서는 언제든 **전체 → 도움말**, 캡처 중 **F1**, 트레이 메뉴의 **사용 설명서** 로 다시 열 수 있습니다."),
    Page("14. 잘 안 될 때",
         "",
         ("**캡처가 검게 나와요**: 은행·보안 프로그램이 캡처를 막아 둔 창입니다. 그 프로그램의 보안 기능이라 풀 수 없습니다.",
          "**붙여넣기가 안 돼요**: 회사 보안 프로그램이 막는 경우가 있습니다. 메일 도우미의 \"파일로 저장(첨부용)\"이나 **다른 이름 저장** 후 첨부하세요.",
          "**글자를 잘못 읽어요**: 작게 찍힌 글자는 틀리기 쉽습니다. 화면을 확대해서 찍으면 정확해집니다.",
          "**단축키가 안 먹어요**: 다른 프로그램이 같은 키를 쓰고 있을 수 있습니다. 설정에서 다른 키로 바꾸세요."),
         ""),
)


def _md_bold_to_html(s: str) -> str:
    out, bold = [], False
    for i, part in enumerate(html.escape(s).split("**")):
        out.append(part if i == 0 else (("<b>" if not bold else "</b>") + part))
        bold = not bold if i > 0 else bold
    return "".join(out)


def page_html(p: Page) -> str:
    steps = "".join(f"<tr><td style='vertical-align:top;padding:4px 10px 8px 0;color:#1F5FD1;font-weight:bold'>{i}</td>"
                    f"<td style='padding:4px 0 8px 0'>{_md_bold_to_html(s)}</td></tr>"
                    for i, s in enumerate(p.steps, 1))
    intro = f"<p style='color:#3A4150'>{_md_bold_to_html(p.intro)}</p>" if p.intro else ""
    tip = (f"<p style='background:#FFF4D6;color:#5C3D00;padding:8px'>💡 {_md_bold_to_html(p.tip)}</p>"
           if p.tip else "")
    pic = ""
    if p.image and image_path(p.image).is_file():
        pic = (f"<p><img src='{image_path(p.image).as_uri()}' width='560'></p>"
               f"<p style='color:#5B6472;font-size:13px'>▲ {html.escape(p.caption)}</p>")
    return (f"<div style='font-size:15px;line-height:150%'><h2 style='color:#1D2330'>{html.escape(p.title)}</h2>"
            f"{intro}<table>{steps}</table>{pic}{tip}</div>")


def as_markdown() -> str:
    parts = ["# 캡처 도구 — 처음 쓰는 분을 위한 따라하기\n",
             "앱 안에서도 같은 내용을 볼 수 있습니다: 캡처 중 **F1**, 버튼 막대의 **전체 → 도움말**, "
             "트레이 메뉴의 **사용 설명서**. 더 자세한 내용은 [USER_GUIDE.md](USER_GUIDE.md)를 보세요.\n"]
    for p in PAGES:
        parts.append(f"## {p.title}\n")
        if p.intro:
            parts.append(p.intro + "\n")
        parts.append("\n".join(f"{i}. {s}" for i, s in enumerate(p.steps, 1)) + "\n")
        if p.image:
            parts.append(f"![{p.caption}](images/guide/{p.image})\n\n*▲ {p.caption}*\n")
        if p.tip:
            parts.append(f"> 💡 {p.tip}\n")
    return "\n".join(parts)


class GuideWindow(QWidget):
    """The guide as a pop-up: chapters on the left, one chapter at a time, 이전 / 다음."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("캡처 도구 사용 설명서 — 따라하기")
        self.resize(860, 600)
        root = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setFixedWidth(240)
        for p in PAGES:
            self.list.addItem(p.title)
        self.list.currentRowChanged.connect(self._show)
        root.addWidget(self.list)
        right = QVBoxLayout()
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        right.addWidget(self.body, 1)
        nav = QHBoxLayout()
        self.pos = QLabel()
        self.prev = QPushButton("◀ 이전")
        self.next = QPushButton("다음 ▶")
        close = QPushButton("닫기")
        self.prev.clicked.connect(lambda: self.show_page(self.list.currentRow() - 1))
        self.next.clicked.connect(lambda: self.show_page(self.list.currentRow() + 1))
        close.clicked.connect(self.close)
        nav.addWidget(self.pos)
        nav.addStretch(1)
        for b in (self.prev, self.next, close):
            nav.addWidget(b)
        right.addLayout(nav)
        root.addLayout(right, 1)
        self.show_page(0)

    def show_page(self, i: int) -> None:
        i = max(0, min(len(PAGES) - 1, i))
        if self.list.currentRow() != i:
            self.list.setCurrentRow(i)
        else:
            self._show(i)

    def _show(self, i: int) -> None:
        if not 0 <= i < len(PAGES):
            return
        self.body.setHtml(page_html(PAGES[i]))
        self.pos.setText(f"{i + 1} / {len(PAGES)}")
        self.prev.setEnabled(i > 0)
        self.next.setEnabled(i < len(PAGES) - 1)

    def show_topic(self, word: str) -> None:
        for i, p in enumerate(PAGES):
            if word in p.title:
                self.show_page(i)
                return
