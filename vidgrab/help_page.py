"""The Help page: a searchable list of how-to guides and answers (text in
`help_content`), with a button that jumps to the page a guide is about."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from vidgrab import help_content

_ID = Qt.UserRole
_PAGE_NAMES = {0: "Download", 1: "Studio", 2: "Settings"}


class HelpPage(QWidget):
    """*t* translates UI strings, *lang* gives the current language, *go* opens
    a page by index and *about* shows the About box."""

    def __init__(self, t: Callable[[str], str], lang: Callable[[], str],
                 go: Callable[[int], None], about: Callable[[], None]) -> None:
        super().__init__()
        self._t, self._lang, self._go = t, lang, go
        self._palette: dict[str, str] = {}
        self._page: int | None = None
        self._topics = {tid: (sec, page, title, body)
                        for tid, sec, page, title, body in help_content.TOPICS}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        left.addWidget(self.search)
        self.topic_list = QListWidget()
        self.topic_list.setObjectName("help_list")
        self.topic_list.setFixedWidth(270)
        self.topic_list.currentItemChanged.connect(self._show)
        left.addWidget(self.topic_list, stretch=1)
        self.about_btn = QPushButton()
        self.about_btn.setObjectName("secondary")
        self.about_btn.setCursor(Qt.PointingHandCursor)
        self.about_btn.clicked.connect(about)
        left.addWidget(self.about_btn)
        lay.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("help_title")
        self.title.setWordWrap(True)
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
        lay.addLayout(right, stretch=1)

        self.retranslate()

    # ── content ────────────────────────────────────────────────────────

    def apply_theme(self, palette: dict[str, str]) -> None:
        self._palette = palette
        p = palette
        self.title.setStyleSheet(f"font-size:20px; font-weight:800; color:{p['TEXT']};"
                                 " background:transparent;")
        self.body.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.body.document().setDefaultStyleSheet(
            f"body, p, li {{ color:{p['TEXT_DIM']}; font-size:14px; }}"
            f"b {{ color:{p['TEXT']}; }} i {{ color:{p['ACCENT2']}; font-style:normal; }}"
            "li { margin-bottom: 6px; } p { margin-bottom: 8px; }")
        self._show(self.topic_list.currentItem())

    def retranslate(self) -> None:
        t = self._t
        self.search.setPlaceholderText(t("Search the help…"))
        self.about_btn.setText(t("About VidGrab"))
        keep = self.current_id()
        self._fill(keep=keep)

    def current_id(self) -> str | None:
        item = self.topic_list.currentItem()
        return item.data(_ID) if item is not None else None

    def _fill(self, *_a, keep: str | None = None) -> None:
        lang = self._lang()
        hits = set(help_content.search(self.search.text(), lang))
        keep = keep or self.current_id()
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        first = chosen = None
        for sec, names in help_content.SECTIONS.items():
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
                head.setForeground(QColor(self._palette["TEXT_MUTED"]))
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

    def open_topic(self, tid: str) -> None:
        self.search.clear()
        for i in range(self.topic_list.count()):
            if self.topic_list.item(i).data(_ID) == tid:
                self.topic_list.setCurrentRow(i)
                return

    def _show(self, item: QListWidgetItem | None, *_a) -> None:
        lang = self._lang()
        tid = item.data(_ID) if item is not None else None
        if tid is None:
            self.title.setText(self._t("Nothing found"))
            self.body.setHtml("<p>" + self._t("Try a different word, such as “captions” or “download”.") + "</p>")
            self._page = None
            self.open_btn.hide()
            return
        _sec, page, title, body = self._topics[tid]
        self.title.setText(title[lang])
        self.body.setHtml(body[lang])
        self._page = page
        self.open_btn.setVisible(page is not None)
        if page is not None:
            self.open_btn.setText(self._t("Open {page}").format(page=self._t(_PAGE_NAMES[page])))
