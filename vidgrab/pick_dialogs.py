"""Two small pickers for the Download page: the results of a YouTube search
(several can be ticked) and the exact formats of one video."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.downloader import _human_size


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


class SearchDialog(QDialog):
    """Search results to tick; `urls()` after accept."""

    def __init__(self, parent: QWidget, t: Callable[..., str], query: str,
                 search: Callable[[str], list[dict]]) -> None:
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(t("Search YouTube"))
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        self.head = QLabel(t("Results for “{q}”", q=query))
        self.head.setObjectName("info_name")
        lay.addWidget(self.head)
        self.list = QListWidget()
        self.list.setObjectName("dl_list")
        self.list.setSpacing(2)
        self.list.itemChanged.connect(self._changed)
        self.list.itemDoubleClicked.connect(self._double)
        lay.addWidget(self.list, 1)
        self.note = QLabel(t("Searching…"))
        self.note.setObjectName("hint")
        lay.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(t("Cancel"))
        cancel.clicked.connect(self.reject)
        self.add = QPushButton(t("Add to downloads"))
        self.add.setDefault(True)
        self.add.setEnabled(False)
        self.add.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.add)
        lay.addLayout(row)
        self._thread = _SearchThread(lambda: search(query))
        self._thread.done.connect(self._show)
        self._thread.failed.connect(lambda m: self.note.setText(m))
        self._thread.start()

    def done(self, result: int) -> None:
        if self._thread.isRunning():
            self._thread.wait(8000)
        super().done(result)

    def _show(self, results: list[dict]) -> None:
        if not results:
            self.note.setText(self.t("Nothing found."))
            return
        self.note.setText(self.t("Tick the videos to download; double-click one to add it alone."))
        self.list.blockSignals(True)
        for r in results:
            bits = [r["uploader"], _clock(r["duration"]),
                    self.t("{n} views", n=_count(r["views"])) if r["views"] else ""]
            item = QListWidgetItem(f"{r['title']}\n{'  ·  '.join(b for b in bits if b)}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, r["url"])
            self.list.addItem(item)
        self.list.blockSignals(False)

    def _changed(self, _item=None) -> None:
        n = len(self.urls())
        self.add.setEnabled(n > 0)
        self.add.setText(self.t("Add {n} to downloads", n=n) if n > 1
                         else self.t("Add to downloads"))

    def _double(self, item: QListWidgetItem) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)
        item.setCheckState(Qt.Checked)
        self.accept()

    def urls(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


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
        self.list = QListWidget()
        self.list.setObjectName("dl_list")
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
