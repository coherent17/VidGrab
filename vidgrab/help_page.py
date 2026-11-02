"""The Help page: a home with a search box, one tile per section and quick-start
chips, and a reader (topic list + guide) for a section or a search. The text is
in `help_content`; a button under a guide jumps to the page it is about."""
from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from vidgrab import help_content

_ID = Qt.UserRole
_PAGE_NAMES = {0: "Download", 1: "Studio", 2: "Settings"}
# section -> (icon kind, palette key of its colour)
_LOOK = {"start": ("clipboard", "ACCENT_HI"), "download": ("download", "ACCENT2"),
         "studio": ("film", "ACCENT"), "captions": ("captions", "AMBER"), "faq": ("help", "ACCENT2_HI")}


def _rgba(color: str, alpha: float) -> str:
    """A stylesheet colour with transparency (Qt reads #RRGGBBAA as #AARRGGBB)."""
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(alpha * 255)})"


class _Tile(QFrame):
    """A clickable card: coloured icon badge, name, one line about it."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("help_tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        self.setMinimumHeight(88)
        self.badge = QLabel()
        self.badge.setFixedSize(46, 46)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name = QLabel()
        self.sub = QLabel()
        self.sub.setWordWrap(True)
        col.addStretch()
        col.addWidget(self.name)
        col.addWidget(self.sub)
        col.addStretch()
        lay.addLayout(col, stretch=1)
        for w in (self.badge, self.name, self.sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class HelpPage(QWidget):
    """*t* translates UI strings, *lang* gives the current language, *go* opens
    a page by index, *about* shows the About box and *icon* draws an icon."""

    def __init__(self, t: Callable[[str], str], lang: Callable[[], str],
                 go: Callable[[int], None], about: Callable[[], None],
                 icon: Callable[[str, str, int], object]) -> None:
        super().__init__()
        self._t, self._lang, self._go, self._icon = t, lang, go, icon
        self._palette: dict[str, str] = {}
        self._page: int | None = None
        self._section: str | None = None
        self._topics = {tid: (sec, page, title, body)
                        for tid, sec, page, title, body in help_content.TOPICS}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 12)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_home())
        self.stack.addWidget(self._build_reader(about))
        self.retranslate()

    # ── building ───────────────────────────────────────────────────────

    def _search_box(self) -> QLineEdit:
        box = QLineEdit()
        box.setClearButtonEnabled(True)
        box.setMinimumHeight(40)
        box.textChanged.connect(self._searched)
        return box

    def _build_home(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)

        self.hero = QFrame()
        self.hero.setObjectName("help_hero")
        hl = QVBoxLayout(self.hero)
        hl.setContentsMargins(36, 26, 36, 28)
        hl.setSpacing(6)
        self.hero_title = QLabel()
        self.hero_sub = QLabel()
        self.home_search = self._search_box()
        self.home_search.setMaximumWidth(560)
        for w in (self.hero_title, self.hero_sub):
            w.setStyleSheet("background:transparent;")
        hl.addWidget(self.hero_title)
        hl.addWidget(self.hero_sub)
        hl.addSpacing(10)
        hl.addWidget(self.home_search)
        lay.addWidget(self.hero)

        self.sec_head = QLabel()
        lay.addWidget(self.sec_head)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.tiles: dict[str, _Tile] = {}
        for i, sec in enumerate(help_content.SECTIONS):
            tile = _Tile()
            tile.clicked.connect(lambda s=sec: self._open_section(s))
            self.tiles[sec] = tile
            grid.addWidget(tile, i // 3, i % 3)
        self.about_tile = _Tile()
        self.about_tile.clicked.connect(lambda: self._about())
        grid.addWidget(self.about_tile, 1, 2)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)

        self.quick_head = QLabel()
        lay.addWidget(self.quick_head)
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(10)
        self.chips: list[tuple[QPushButton, str]] = []
        for tid in help_content.FEATURED:
            b = QPushButton()
            b.setObjectName("help_chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, x=tid: self._open_topic(x))
            self.chip_row.addWidget(b)
            self.chips.append((b, tid))
        self.chip_row.addStretch()
        lay.addLayout(self.chip_row)
        lay.addStretch()
        return page

    def _build_reader(self, about: Callable[[], None]) -> QWidget:
        self._about = about
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("secondary")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.show_home)
        left.addWidget(self.back_btn)
        self.search = self._search_box()
        left.addWidget(self.search)
        self.topic_list = QListWidget()
        self.topic_list.setObjectName("help_list")
        self.topic_list.setFixedWidth(270)
        self.topic_list.currentItemChanged.connect(self._show)
        left.addWidget(self.topic_list, stretch=1)
        lay.addLayout(left)

        card = QFrame()
        card.setObjectName("help_article")
        card.setAttribute(Qt.WA_StyledBackground, True)
        right = QVBoxLayout(card)
        right.setContentsMargins(34, 26, 34, 24)
        right.setSpacing(8)
        self.chip = QLabel()
        self.title = QLabel()
        self.title.setWordWrap(True)
        right.addWidget(self.chip, alignment=Qt.AlignLeft)
        right.addWidget(self.title)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setFrameShape(QTextBrowser.NoFrame)
        right.addWidget(self.body, stretch=1)
        foot = QHBoxLayout()
        self.open_btn = QPushButton()
        self.open_btn.setObjectName("primary")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(lambda: self._page is not None and self._go(self._page))
        foot.addWidget(self.open_btn)
        foot.addStretch()
        right.addLayout(foot)
        lay.addWidget(card, stretch=1)
        return page

    # ── theme / language ───────────────────────────────────────────────

    def _color(self, sec: str) -> str:
        return self._palette.get(_LOOK[sec][1], "#7c5cff")

    def apply_theme(self, palette: dict[str, str]) -> None:
        self._palette = p = palette
        self.hero.setStyleSheet(
            "QFrame#help_hero { border-radius:16px; border:1px solid " + p["BORDER_HI"] + ";"
            f" background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {_rgba(p['ACCENT'], .38)},"
            f" stop:0.6 {p['SURFACE_HI']}, stop:1 {_rgba(p['ACCENT2'], .26)}); }}")
        self.hero_title.setStyleSheet(f"font-size:30px; font-weight:800; color:{p['TEXT']}; background:transparent;")
        self.hero_sub.setStyleSheet(f"font-size:14px; color:{p['TEXT_DIM']}; background:transparent;")
        head = (f"font-size:11px; font-weight:800; letter-spacing:1.5px; color:{p['TEXT_MUTED']};"
                " background:transparent;")
        self.sec_head.setStyleSheet(head)
        self.quick_head.setStyleSheet(head)
        tile_css = (f"QFrame#help_tile {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']};"
                    " border-radius:14px; }"
                    f"QFrame#help_tile:hover {{ border:1px solid {p['ACCENT_HI']}; background:{p['SURFACE_HI']}; }}")
        for sec, tile in {**self.tiles, "about": self.about_tile}.items():
            tile.setStyleSheet(tile_css)
            tile.name.setStyleSheet(f"font-size:15px; font-weight:700; color:{p['TEXT']}; background:transparent;")
            tile.sub.setStyleSheet(f"font-size:12px; color:{p['TEXT_MUTED']}; background:transparent;")
            c = QColor(self._color(sec) if sec != "about" else p["ACCENT"])
            kind = _LOOK[sec][0] if sec != "about" else "help"
            tile.badge.setPixmap(self._icon(kind, c.name(), 24).pixmap(24, 24))
            tile.badge.setStyleSheet(f"background:{_rgba(c.name(), .18)}; border-radius:14px;")
        for b, _tid in self.chips:
            b.setStyleSheet(
                f"QPushButton#help_chip {{ background:{p['SURFACE']}; color:{p['TEXT_DIM']};"
                f" border:1px solid {p['BORDER']}; border-radius:16px; padding:7px 16px; font-size:13px; }}"
                f"QPushButton#help_chip:hover {{ color:{p['TEXT']}; border-color:{p['ACCENT_HI']};"
                f" background:{p['SURFACE_HI']}; }}")
        self.search.setStyleSheet("")
        self.title.setStyleSheet(f"font-size:24px; font-weight:800; color:{p['TEXT']}; background:transparent;")
        self.topic_list.setIconSize(QSize(18, 18))
        self.body.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.body.document().setDefaultStyleSheet(
            f"body, p, li {{ color:{p['TEXT_DIM']}; font-size:14px; }}"
            f"b {{ color:{p['TEXT']}; }} i {{ color:{p['ACCENT2']}; font-style:normal; }}"
            "li { margin-bottom: 6px; } p { margin-bottom: 8px; }")
        self.setStyleSheet(
            f"QFrame#help_article {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']};"
            " border-radius:16px; }")
        self._fill(keep=self.current_id())

    def retranslate(self) -> None:
        t, lang = self._t, self._lang()
        for box in (self.home_search, self.search):
            box.setPlaceholderText(t("Search the help…"))
        self.hero_title.setText(t("How can we help?"))
        self.hero_sub.setText(t("Guides for every feature, and answers to common questions."))
        self.sec_head.setText(t("BROWSE BY TOPIC"))
        self.quick_head.setText(t("QUICK START"))
        self.back_btn.setText("←  " + t("All help"))
        for sec, tile in self.tiles.items():
            tile.name.setText(help_content.SECTIONS[sec][lang])
            tile.sub.setText(help_content.BLURBS[sec][lang])
        self.about_tile.name.setText(t("About VidGrab"))
        self.about_tile.sub.setText(t("Version, licence and credits"))
        for b, tid in self.chips:
            b.setText(self._topics[tid][2][lang])
        self._fill(keep=self.current_id())
        if self._palette:
            self.apply_theme(self._palette)

    # ── navigation ─────────────────────────────────────────────────────

    def show_home(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.home_search.clear()
        self.search.blockSignals(False)
        self._section = None
        self.stack.setCurrentIndex(0)

    def _open_section(self, sec: str) -> None:
        self._section = sec
        self.stack.setCurrentIndex(1)
        self._fill()

    def _open_topic(self, tid: str) -> None:
        self.open_topic(tid)

    def open_topic(self, tid: str) -> None:
        """Show a guide with its whole section beside it."""
        self.search.blockSignals(True)
        self.search.clear()
        self.home_search.clear()
        self.search.blockSignals(False)
        self._section = self._topics[tid][0]
        self.stack.setCurrentIndex(1)
        self._fill(keep=tid)

    def _searched(self, text: str) -> None:
        src = self.sender()
        other = self.search if src is self.home_search else self.home_search
        if other.text() != text:
            other.blockSignals(True)
            other.setText(text)
            other.blockSignals(False)
        if text.strip():
            self._section = None
            self.stack.setCurrentIndex(1)
            if src is self.home_search:
                self.search.setFocus()
        self._fill()

    # ── the list and the guide ─────────────────────────────────────────

    def current_id(self) -> str | None:
        item = self.topic_list.currentItem()
        return item.data(_ID) if item is not None else None

    def _fill(self, *_a, keep: str | None = None) -> None:
        lang = self._lang()
        query = self.search.text()
        hits = set(help_content.search(query, lang))
        keep = keep or self.current_id()
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        first = chosen = None
        for sec, names in help_content.SECTIONS.items():
            if self._section and not query.strip() and sec != self._section:
                continue
            rows = [tid for tid, s, *_ in help_content.TOPICS if s == sec and tid in hits]
            if not rows:
                continue
            head = QListWidgetItem(names[lang].upper())
            head.setFlags(Qt.NoItemFlags)
            f = head.font()
            f.setBold(True)
            f.setPointSizeF(max(f.pointSizeF() - 1.5, 7))
            head.setFont(f)
            if self._palette:
                head.setForeground(QColor(self._color(sec)))
            self.topic_list.addItem(head)
            for tid in rows:
                item = QListWidgetItem("   " + self._topics[tid][2][lang])
                item.setData(_ID, tid)
                self.topic_list.addItem(item)
                first = first or item
                if tid == keep:
                    chosen = item
        self.topic_list.blockSignals(False)
        chosen = chosen or first
        if chosen is not None:
            self.topic_list.setCurrentItem(chosen)
        self._show(self.topic_list.currentItem())

    def _steps(self, body: str) -> str:
        """<ol> as numbered cards (a QTextBrowser has no CSS counters)."""
        p = self._palette
        out, rest = [], body
        while "<ol>" in rest:
            before, _, rest = rest.partition("<ol>")
            items, _, rest = rest.partition("</ol>")
            out.append(before)
            for n, li in enumerate(items.split("<li>")[1:], 1):
                text = li.replace("</li>", "").strip()
                out.append(
                    f'<table width="100%" cellspacing="0" cellpadding="11" style="margin-bottom:8px;">'
                    f'<tr><td width="34" align="center" bgcolor="{p["ACCENT"]}">'
                    f'<span style="color:#ffffff; font-size:16px; font-weight:800;">{n}</span></td>'
                    f'<td bgcolor="{p["SURFACE_HI"]}" style="color:{p["TEXT_DIM"]}; font-size:14px;"><span style="font-size:14px;">&nbsp;{text}</span></td></tr></table>'
                    '<p style="margin:0; font-size:4px;">&nbsp;</p>')
        return "".join(out) + rest

    def _show(self, item: QListWidgetItem | None, *_a) -> None:
        lang = self._lang()
        tid = item.data(_ID) if item is not None else None
        if tid is None:
            self.chip.setText("")
            self.chip.hide()
            self.title.setText(self._t("Nothing found"))
            self.body.setHtml("<p>" + html.escape(
                self._t("Try a different word, such as “captions” or “download”.")) + "</p>")
            self._page = None
            self.open_btn.hide()
            return
        sec, page, title, body = self._topics[tid]
        color = self._color(sec) if self._palette else "#7c5cff"
        self.chip.setText(help_content.SECTIONS[sec][lang].upper())
        self.chip.setStyleSheet(f"color:{color}; background:{_rgba(color, .16)}; border-radius:9px; padding:3px 12px;"
                                " font-size:11px; font-weight:800; letter-spacing:1.2px;")
        self.chip.show()
        self.title.setText(title[lang])
        self.body.setHtml(self._steps(body[lang]) if self._palette else body[lang])
        self._page = page
        self.open_btn.setVisible(page is not None)
        if page is not None:
            self.open_btn.setText(self._t("Open {page}").format(page=self._t(_PAGE_NAMES[page])))
