"""Two small pickers for the Download page: the results of a YouTube search
(several can be ticked) and the exact formats of one video."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.downloader import _fetch_thumbnail, _human_size

_THUMB = QSize(112, 63)


def _clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _count(n: int | None) -> str:
    if not n:
        return ""
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= limit:
            return f"{n / limit:.1f}{suffix}".replace(".0", "")
    return str(n)


class _SearchThread(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], list[dict]]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _ThumbThread(QThread):
    """Fetch the thumbnails of the results one by one (cached on disk)."""

    got = Signal(int, str)

    def __init__(self, urls: list[str], cache: Path) -> None:
        super().__init__()
        self._urls, self._cache = urls, cache

    def run(self) -> None:
        for i, url in enumerate(self._urls):
            if self.isInterruptionRequested():
                return
            path = _fetch_thumbnail(url, self._cache) if url else None
            if path:
                self.got.emit(i, path)


class ResultRow(QWidget):
    """One search result: a tick box, its picture, title and details."""

    toggled = Signal()

    def __init__(self, result: dict, t: Callable[..., str]) -> None:
        super().__init__()
        self.url = result["url"]
        self.setObjectName("dl_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(12)
        self.check = QCheckBox()
        self.check.setCursor(QCursor(Qt.PointingHandCursor))
        self.check.toggled.connect(lambda _on: self.toggled.emit())
        lay.addWidget(self.check)
        self.thumb = QLabel()
        self.thumb.setObjectName("dl_thumb")
        self.thumb.setFixedSize(_THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(result["title"])
        title.setObjectName("dl_title")
        title.setWordWrap(True)
        bits = [result["uploader"], _clock(result["duration"]),
                t("{n} views", n=_count(result["views"])) if result["views"] else ""]
        meta = QLabel("  ·  ".join(b for b in bits if b))
        meta.setObjectName("dl_status")
        col.addStretch()
        col.addWidget(title)
        col.addWidget(meta)
        col.addStretch()
        lay.addLayout(col, stretch=1)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def set_thumb(self, path: str) -> None:
        pm = QPixmap(path)
        if not pm.isNull():
            self.thumb.setPixmap(pm.scaled(_THUMB, Qt.KeepAspectRatioByExpanding,
                                           Qt.SmoothTransformation))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.check.toggle()


class SearchPanel(QWidget):
    """The results of a YouTube search, shown in the page itself (replacing the
    video card and options while it is open). Emits `chosen(urls)` or `closed()`."""

    chosen = Signal(list)
    closed = Signal()

    def __init__(self, t: Callable[..., str], thumb_dir: Path) -> None:
        super().__init__()
        self.t = t
        self._thumb_dir = thumb_dir
        self._rows: list[ResultRow] = []
        self._thumbs: _ThumbThread | None = None
        self._search: _SearchThread | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.head = QLabel()
        self.head.setObjectName("info_name")
        head.addWidget(self.head, 1)
        self._back = QPushButton()
        self._back.setObjectName("secondary")
        self._back.setCursor(QCursor(Qt.PointingHandCursor))
        self._back.clicked.connect(self.closed)
        head.addWidget(self._back)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setObjectName("dl_list")
        self.list.setMinimumHeight(300)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setSpacing(3)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lay.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.note = QLabel()
        self.note.setObjectName("hint")
        foot.addWidget(self.note, 1)
        self.add = QPushButton()
        self.add.setObjectName("primary")
        self.add.setProperty("compact", True)
        self.add.setFixedHeight(40)
        self.add.setMinimumWidth(200)
        self.add.setCursor(QCursor(Qt.PointingHandCursor))
        self.add.clicked.connect(lambda: self.chosen.emit(self.urls()))
        foot.addWidget(self.add)
        lay.addLayout(foot)
        self._query = ""
        self._state = "idle"  # idle | searching | ready | empty | error:<message>
        self.retranslate()

    def retranslate(self) -> None:
        """Re-apply every text (the window's language can change while this is open)."""
        t = self.t
        self._back.setText(t("Close results"))
        if self._query:
            self.head.setText(t("Results for “{q}”", q=self._query))
        self.note.setText({
            "searching": t("Searching…"),
            "ready": t("Tick the videos you want, then add them to your downloads."),
            "empty": t("Nothing found."),
        }.get(self._state, self._state.removeprefix("error:") if self._state.startswith("error:") else ""))
        self._update()

    def start(self, query: str, search: Callable[[str], list[dict]]) -> None:
        """Show "searching…" and run *search* in the background."""
        self.stop()
        self.list.clear()
        self._rows = []
        self._query, self._state = query, "searching"
        self.retranslate()
        self._search = _SearchThread(lambda: search(query))
        self._search.done.connect(self._show)
        self._search.failed.connect(lambda m: (setattr(self, "_state", f"error:{m}"),
                                               self.retranslate()))
        self._search.start()

    def stop(self) -> None:
        for thread in (self._search, self._thumbs):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.wait(5000)

    def _show(self, results: list[dict]) -> None:
        if not results:
            self._state = "empty"
            self.retranslate()
            return
        self._state = "ready"
        self.retranslate()
        for r in results:
            row = ResultRow(r, self.t)
            row.toggled.connect(self._update)
            item = QListWidgetItem()
            item.setSizeHint(QSize(100, _THUMB.height() + 16))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows.append(row)
        self._thumbs = _ThumbThread([r["thumbnail"] for r in results], self._thumb_dir)
        self._thumbs.got.connect(lambda i, path: self._rows[i].set_thumb(path)
                                 if i < len(self._rows) else None)
        self._thumbs.start()

    def _update(self) -> None:
        n = len(self.urls())
        self.add.setEnabled(n > 0)
        self.add.setText(self.t("Add {n} to downloads", n=n) if n > 0
                         else self.t("Add to downloads"))

    def urls(self) -> list[str]:
        return [r.url for r in self._rows if r.check.isChecked()]


def format_label(f: dict, t: Callable[..., str]) -> str:
    """One line for a format from `downloader.probe()['format_list']`."""
    bits: list[str] = []
    if f["vcodec"]:
        bits.append(f"{f['height']}p" if f["height"] else (f["note"] or "?"))
        if f["fps"] and f["fps"] > 30:
            bits.append(f"{int(f['fps'])} fps")
        bits.append(f["vcodec"])
    else:
        bits.append(f["acodec"] or "audio")
        if f["abr"]:
            bits.append(f"{int(f['abr'])} kbps")
    bits.append(f["ext"].upper())
    if f["size"]:
        bits.append(_human_size(f["size"]))
    text = "  ·  ".join(bits)
    if f["vcodec"] and not f["acodec"]:
        text += "    " + t("(picture only; sound is added)")
    return text


class FormatDialog(QDialog):
    """Pick one exact format; `chosen()` is its dict, or None for Automatic."""

    def __init__(self, parent: QWidget, t: Callable[..., str], formats: list[dict],
                 audio_only: bool, current: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Choose exact format"))
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        intro = QLabel(t("Automatic picks the best format for the quality you chose. Pick "
                         "one here to get exactly that resolution and codec."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()  # the plain field style: a border and a highlighted row
        self.list.setSpacing(1)
        auto = QListWidgetItem(t("Automatic (best)"))
        auto.setData(Qt.UserRole, None)
        self.list.addItem(auto)
        wanted = [f for f in formats if (not f["vcodec"] if audio_only else bool(f["vcodec"]))]
        for f in wanted:
            item = QListWidgetItem(format_label(f, t))
            item.setData(Qt.UserRole, f)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        for i in range(self.list.count()):
            data = self.list.item(i).data(Qt.UserRole)
            if current and data and data["id"] == current:
                self.list.setCurrentRow(i)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(t("Cancel"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t("Use this format"))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def chosen(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None
