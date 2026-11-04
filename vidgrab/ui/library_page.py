"""The Library page: every media file in the output folder, searchable, with
one-click Open / Show in folder / Send to Studio / Compress / Delete."""
from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.core import library
from vidgrab.media.probe import probe_media
from vidgrab.ui.downloads_panel import human_size
from vidgrab.ui.studio_page import ThumbCache
from vidgrab.ui.ui_kit import Chips, EmptyState, attach_suggestions, chip_css

_PATH = Qt.UserRole
_KIND_ICON = {"video": "film", "audio": "music", "image": "captions"}
THUMB = QSize(128, 72)  # list rows
GRID_THUMB = QSize(208, 117)  # grid cards


def clock(seconds: float) -> str:
    """3:07 or 1:02:09, for the badge on a picture."""
    s = round(seconds)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class _DurRelay(QObject):
    done = Signal(str, float)


class _DurTask(QRunnable):
    """How long a file is, read in the background (one ffprobe each)."""

    def __init__(self, relay: _DurRelay, path: str) -> None:
        super().__init__()
        self._relay, self._path = relay, path

    def run(self) -> None:
        try:
            seconds = float(probe_media(self._path).get("duration") or 0.0)
        except (RuntimeError, OSError, ValueError):
            seconds = 0.0
        self._relay.done.emit(self._path, seconds)


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
        self._thumbs = ThumbCache(self, height=GRID_THUMB.height() + 7)  # one size serves both views
        self._thumbs.updated.connect(self._paint_thumbs)
        self._durations: dict[str, float] = {}  # seconds, 0 = unknown
        self._asked: set[str] = set()
        self._dur_pool = QThreadPool(self)
        self._dur_pool.setMaxThreadCount(2)
        self._dur_relay = _DurRelay(self)
        self._dur_relay.done.connect(self._got_duration)
        self._phase = 0.0  # the shimmer on pictures that are still loading
        self._shimmer = QTimer(self)
        self._shimmer.setInterval(110)
        self._shimmer.timeout.connect(self._tick_shimmer)

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
        self.view_btns: dict[str, QPushButton] = {}
        for mode in ("list", "grid"):  # how the files are laid out
            b = QPushButton()
            b.setObjectName("secondary")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, m=mode: self.set_view(m))
            top.addWidget(b)
            self.view_btns[mode] = b
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
        self.empty = EmptyState(lambda c: self.host.icon("folder", c, 56).pixmap(56, 56))
        self.open_folder_btn = self.empty.add_button("", lambda: self.host.open_path(str(self.host.default_output_dir())),
                                                     primary=True)
        cl.addWidget(self.empty)
        lay.addWidget(card, stretch=1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.actions: dict[str, QPushButton] = {}
        for key in ("open", "reveal", "studio", "tools", "delete"):
            b = QPushButton()
            b.setObjectName("primary" if key == "studio" else "secondary")
            if key == "studio":  # the main action, but the same height as its neighbours
                b.setProperty("compact", True)
            b.setMinimumHeight(36)
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
        saved = self.host.setting("library_view") if hasattr(self.host, "setting") else "list"
        self.set_view(saved if saved in ("list", "grid") else "list", save=False)

    # ── look ───────────────────────────────────────────────────────────

    def apply_theme(self, p: dict[str, str]) -> None:
        self._palette = p
        self.setStyleSheet(
            chip_css(p)
            + f"QFrame#lib_card {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']}; border-radius:14px; }}"
            + "QListWidget#lib_list { background:transparent; border:none; outline:none; }"
            + f"QPushButton#secondary:checked {{ border:1px solid {p['ACCENT']}; color:{p['ACCENT_HI']}; }}"
            + f"QListWidget#lib_list::item {{ padding:6px 8px; border-radius:10px; color:{p['TEXT']}; }}"
            + f"QListWidget#lib_list::item:hover {{ background:{p['SURFACE_HI']}; }}"
            + f"QListWidget#lib_list::item:selected {{ background:{p['SEL']}; color:{p['TEXT']}; }}")
        self.folder_lbl.setStyleSheet(f"color:{p['TEXT_MUTED']}; font-size:12px;")
        self.empty.apply_theme(p)
        self.count_lbl.setStyleSheet(f"color:{p['TEXT_MUTED']}; font-size:12px;")
        self._fill()

    def retranslate(self) -> None:
        t = self.host.t
        self.search.setPlaceholderText(t("Search your files…"))
        for k, label in (("all", "All"), ("video", "Videos"), ("audio", "Music"), ("image", "Pictures")):
            self.chips.buttons[k].setText(t(label))
        self.refresh_btn.setText(t("Refresh"))
        self.view_btns["list"].setText(t("List"))
        self.view_btns["grid"].setText(t("Grid"))
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

    @property
    def view(self) -> str:
        return "grid" if getattr(self, "_view", "list") == "grid" else "list"

    def set_view(self, mode: str, *, save: bool = True) -> None:
        """"list": one row per file; "grid": cards with large pictures."""
        self._view = "grid" if mode == "grid" else "list"
        for key, btn in self.view_btns.items():
            btn.setChecked(key == self._view)
        grid = self._view == "grid"
        self.list.setViewMode(QListView.IconMode if grid else QListView.ListMode)
        self.list.setIconSize(GRID_THUMB if grid else THUMB)
        self.list.setGridSize(QSize(GRID_THUMB.width() + 30, GRID_THUMB.height() + 74) if grid else QSize())
        self.list.setWrapping(grid)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWordWrap(grid)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setSpacing(10 if grid else 2)
        if save and hasattr(self.host, "set_setting"):
            self.host.set_setting("library_view", self._view)
        self._fill()

    def _thumb_size(self) -> QSize:
        return GRID_THUMB if self.view == "grid" else THUMB

    def _placeholder(self, kind: str, glow: float = 0.0) -> QIcon:
        size = self._thumb_size()
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        base = QColor(self._palette.get("SURFACE_HI", "#1c1e3c"))
        if glow:  # a soft pulse while the real picture is on its way
            base = base.lighter(100 + int(22 * glow))
        p.setBrush(base)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, size.width(), size.height(), 8, 8)
        p.end()
        glyph = self.host.icon(_KIND_ICON[kind], self._palette.get("TEXT_MUTED", "#7b80aa"), 28).pixmap(28, 28)
        p = QPainter(pm)
        p.drawPixmap((size.width() - 28) // 2, (size.height() - 28) // 2, glyph)
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
            if self.view == "list":
                item.setSizeHint(QSize(100, THUMB.height() + 16))
            self.list.addItem(item)
            if e.path in keep:
                item.setSelected(True)
        self.empty.setVisible(not shown)
        self.list.setVisible(bool(shown))
        fix = self._finder.did_you_mean(self.search.text()) if self._entries and not shown else None
        if not self._entries:
            self.empty.set_texts(t("Nothing here yet"), t("Downloads and renders you make will show up here."))
        else:
            self.empty.set_texts(t("No file matches."), (f"{t('Did you mean')} “{fix}”?" if fix else ""))
        self.open_folder_btn.setText(t("Open downloads folder"))
        self.open_folder_btn.setVisible(not self._entries)
        self.count_lbl.setText(t("{n} files", n=len(shown)))
        self._paint_thumbs()
        self._selection()

    def _paint_thumbs(self) -> None:
        waiting = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = item.data(_PATH)
            kind = library.kind_of(path)
            if kind in ("video", "audio"):
                self._want_duration(path)
            if kind != "video":
                if kind == "audio":
                    item.setIcon(QIcon(self._badged(self._placeholder("audio").pixmap(self._thumb_size()), path)))
                continue
            img = self._thumbs.frame(path, 1.0, 1.0)
            if img is not None and not img.isNull():
                item.setIcon(QIcon(self._badged(self._cover(img), path)))
            else:
                waiting = True
        if waiting and not self._shimmer.isActive():
            self._shimmer.start()
        elif not waiting:
            self._shimmer.stop()

    def _tick_shimmer(self) -> None:
        """Pulse the placeholder of every video whose frame has not arrived yet."""
        self._phase += 0.35
        glow = 0.5 + 0.5 * math.sin(self._phase)
        waiting = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = item.data(_PATH)
            if library.kind_of(path) == "video" and self._thumbs.frame(path, 1.0, 1.0) is None:
                item.setIcon(QIcon(self._placeholder("video", glow).pixmap(self._thumb_size())))
                waiting = True
        if not waiting:
            self._shimmer.stop()

    def _want_duration(self, path: str) -> None:
        if path not in self._asked:
            self._asked.add(path)
            self._dur_pool.start(_DurTask(self._dur_relay, path))

    def _got_duration(self, path: str, seconds: float) -> None:
        self._durations[path] = seconds
        if seconds:
            self._paint_thumbs()

    def _badged(self, pm: QPixmap, path: str) -> QPixmap:
        """The picture with its length in a small dark pill at the bottom right."""
        seconds = self._durations.get(path, 0.0)
        if not seconds:
            return pm
        out = QPixmap(pm)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(p.font())
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        text = clock(seconds)
        w = p.fontMetrics().horizontalAdvance(text) + 12
        h = 18
        x, y = out.width() - w - 6, out.height() - h - 6
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 175))
        p.drawRoundedRect(x, y, w, h, 6, 6)
        p.setPen(QColor("#ffffff"))
        p.drawText(x, y, w, h, Qt.AlignCenter, text)
        p.end()
        return out

    def _cover(self, img: QImage) -> QPixmap:
        size = self._thumb_size()
        pm = QPixmap(size)
        pm.fill(Qt.black)
        scaled = QPixmap.fromImage(img).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p = QPainter(pm)
        p.drawPixmap((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
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
        self._shimmer.stop()
        self._dur_pool.clear()
        self._thumbs.shutdown()
