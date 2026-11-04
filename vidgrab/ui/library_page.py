"""The Library page: every media file in the output folder, searchable, with
one-click Open / Show in folder / Send to Studio / Compress / Delete."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.core import library
from vidgrab.ui.downloads_panel import human_size
from vidgrab.ui.studio_page import ThumbCache
from vidgrab.ui.ui_kit import Chips, attach_suggestions, chip_css

_PATH = Qt.UserRole
_KIND_ICON = {"video": "film", "audio": "music", "image": "captions"}
THUMB = QSize(128, 72)


def ago(mtime: float, t) -> str:
    secs = max(time.time() - mtime, 0)
    if secs < 90:
        return t("just now")
    if secs < 3600:
        return t("{n} min ago", n=int(secs // 60))
    if secs < 86400:
        return t("{n} h ago", n=int(secs // 3600))
    days = int(secs // 86400)
    return t("yesterday") if days == 1 else t("{n} days ago", n=days)


class LibraryPage(QWidget):
    """*host* gives t(), icon(), default_output_dir(), send_to_studio(paths),
    open_tool(path), reveal(path) and open_path(path)."""

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self._palette: dict[str, str] = {}
        self._entries: list[library.Entry] = []
        self._finder = library.Finder([])
        self._thumbs = ThumbCache(self)
        self._thumbs.updated.connect(self._paint_thumbs)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        self.search.setMinimumWidth(240)
        self.search.setMaximumWidth(380)
        self.search.textChanged.connect(self._fill)
        attach_suggestions(self.search, lambda text: self._finder.suggest(text))
        top.addWidget(self.search)
        self.chips = Chips(list(library.KINDS))
        self.chips.changed.connect(lambda _k: self._fill())
        top.addWidget(self.chips, stretch=1)
        self.folder_lbl = QLabel()
        top.addWidget(self.folder_lbl)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        lay.addLayout(top)

        card = QFrame()
        card.setObjectName("lib_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        self.list = QListWidget()
        self.list.setObjectName("lib_list")
        self.list.setIconSize(THUMB)
        self.list.setSpacing(2)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._selection)
        self.list.itemDoubleClicked.connect(lambda it: self.host.open_path(it.data(_PATH)))
        cl.addWidget(self.list)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        cl.addWidget(self.empty)
        lay.addWidget(card, stretch=1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.actions: dict[str, QPushButton] = {}
        for key in ("open", "reveal", "studio", "tools", "delete"):
            b = QPushButton()
            b.setObjectName("primary" if key == "studio" else "secondary")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._act(k))
            bar.addWidget(b)
            self.actions[key] = b
        bar.addStretch()
        self.count_lbl = QLabel()
        bar.addWidget(self.count_lbl)
        lay.addLayout(bar)
        self.retranslate()
        self._selection()

    # ── look ───────────────────────────────────────────────────────────

    def apply_theme(self, p: dict[str, str]) -> None:
        self._palette = p
        self.setStyleSheet(
            chip_css(p)
            + f"QFrame#lib_card {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']}; border-radius:14px; }}"
            + "QListWidget#lib_list { background:transparent; border:none; outline:none; }"
            + f"QListWidget#lib_list::item {{ padding:6px 8px; border-radius:10px; color:{p['TEXT']}; }}"
            + f"QListWidget#lib_list::item:hover {{ background:{p['SURFACE_HI']}; }}"
            + f"QListWidget#lib_list::item:selected {{ background:{p['SEL']}; color:{p['TEXT']}; }}")
        self.folder_lbl.setStyleSheet(f"color:{p['TEXT_MUTED']}; font-size:12px;")
        self.empty.setStyleSheet(f"color:{p['TEXT_MUTED']}; font-size:14px;")
        self.count_lbl.setStyleSheet(f"color:{p['TEXT_MUTED']}; font-size:12px;")
        self._fill()

    def retranslate(self) -> None:
        t = self.host.t
        self.search.setPlaceholderText(t("Search your files…"))
        for k, label in (("all", "All"), ("video", "Videos"), ("audio", "Music"), ("image", "Pictures")):
            self.chips.buttons[k].setText(t(label))
        self.refresh_btn.setText(t("Refresh"))
        for k, label in (("open", "Open"), ("reveal", "Show in folder"), ("studio", "Send to Studio"),
                         ("tools", "Compress / convert…"), ("delete", "Delete")):
            self.actions[k].setText(t(label))
        self._fill()

    # ── content ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        folder = self.host.default_output_dir()
        self._entries = library.scan(folder)
        self._finder = library.Finder(self._entries)
        self.folder_lbl.setText(str(folder))
        self._fill()

    def _placeholder(self, kind: str) -> QIcon:
        pm = QPixmap(THUMB)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(self._palette.get("SURFACE_HI", "#1c1e3c")))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, THUMB.width(), THUMB.height(), 8, 8)
        p.end()
        glyph = self.host.icon(_KIND_ICON[kind], self._palette.get("TEXT_MUTED", "#7b80aa"), 28).pixmap(28, 28)
        p = QPainter(pm)
        p.drawPixmap((THUMB.width() - 28) // 2, (THUMB.height() - 28) // 2, glyph)
        p.end()
        return QIcon(pm)

    def _fill(self, *_a) -> None:
        t = self.host.t
        shown = self._finder.filter(self.chips.current(), self.search.text())
        keep = {i.data(_PATH) for i in self.list.selectedItems()}
        self.list.clear()
        for e in shown:
            item = QListWidgetItem(self._placeholder(e.kind),
                                   f"{e.name}\n{human_size(e.size)}  ·  {ago(e.mtime, t)}  ·  "
                                   f"{t({'video': 'Video', 'audio': 'Music', 'image': 'Picture'}[e.kind])}")
            item.setData(_PATH, e.path)
            item.setToolTip(e.path)
            item.setSizeHint(QSize(100, THUMB.height() + 16))
            self.list.addItem(item)
            if e.path in keep:
                item.setSelected(True)
        self.empty.setVisible(not shown)
        self.list.setVisible(bool(shown))
        fix = self._finder.did_you_mean(self.search.text()) if self._entries and not shown else None
        self.empty.setText(t("Nothing here yet. Downloads and renders you make will show up in this list.")
                           if not self._entries else
                           t("No file matches.") + (f"  {t('Did you mean')} “{fix}”?" if fix else ""))
        self.count_lbl.setText(t("{n} files", n=len(shown)))
        self._paint_thumbs()
        self._selection()

    def _paint_thumbs(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = item.data(_PATH)
            if library.kind_of(path) != "video":
                continue
            img = self._thumbs.frame(path, 1.0, 1.0)
            if img is not None and not img.isNull():
                item.setIcon(QIcon(self._cover(img)))

    @staticmethod
    def _cover(img: QImage) -> QPixmap:
        pm = QPixmap(THUMB)
        pm.fill(Qt.black)
        scaled = QPixmap.fromImage(img).scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p = QPainter(pm)
        p.drawPixmap((THUMB.width() - scaled.width()) // 2, (THUMB.height() - scaled.height()) // 2, scaled)
        p.end()
        return pm

    # ── actions ────────────────────────────────────────────────────────

    def selected(self) -> list[str]:
        return [i.data(_PATH) for i in self.list.selectedItems()]

    def _selection(self) -> None:
        n = len(self.selected())
        for k, b in self.actions.items():
            b.setEnabled(n == 1 if k in ("open", "reveal", "tools") else n >= 1)

    def _act(self, key: str) -> None:
        paths = self.selected()
        if not paths:
            return
        if key == "open":
            self.host.open_path(paths[0])
        elif key == "reveal":
            self.host.reveal(paths[0])
        elif key == "studio":
            self.host.send_to_studio([p for p in paths if library.kind_of(p) in ("video", "audio")])
        elif key == "tools":
            self.host.open_tool(paths[0])
        elif key == "delete":
            t = self.host.t
            ask = QMessageBox.question(self, t("Delete"), t("Delete {n} file(s) from your computer?", n=len(paths)))
            if ask == QMessageBox.Yes:
                for p in paths:
                    try:
                        Path(p).unlink()
                    except OSError as exc:
                        self.host.log(f"delete {p}: {exc}")
                self.refresh()

    def shutdown(self) -> None:
        self._thumbs.shutdown()
