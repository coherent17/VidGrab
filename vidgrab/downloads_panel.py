"""The Downloads list on the Download page: queue + recent downloads.

Every Download click (or every pasted link) becomes a row. Rows move through
queued → downloading → done / failed / cancelled. Finished rows are saved
to ``history.json`` so recent downloads survive a restart, and offer Send to
Studio.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.jobs import MEDIA_SUFFIXES, DownloadJob

HISTORY_LIMIT = 100
THUMB = QSize(112, 63)
LINK_THUMB = QSize(96, 54)

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


@dataclass
class DownloadItem:
    job: DownloadJob
    title: str = ""
    thumb: str = ""  # local thumbnail path
    status: str = QUEUED
    progress: float | None = 0.0
    message: str = ""
    files: list[str] = field(default_factory=list)
    finished_at: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def media(self) -> list[str]:
        return [f for f in self.files if Path(f).suffix.lower() in MEDIA_SUFFIXES]

    def subtitles(self) -> str | None:
        return next((f for f in self.files if f.lower().endswith(".srt")), None)

    def size(self) -> int:
        return sum(Path(f).stat().st_size for f in self.files if Path(f).is_file())

    def missing(self) -> bool:
        return bool(self.files) and not any(Path(f).is_file() for f in self.media())


# ── history ───────────────────────────────────────────────────────────────


def load_history(path: Path) -> list[DownloadItem]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = []
    for d in raw if isinstance(raw, list) else []:
        try:
            job = DownloadJob(**d.pop("job"))
            items.append(DownloadItem(job=job, **d))
        except (TypeError, KeyError):
            continue
    return items


def save_history(path: Path, items: list[DownloadItem]) -> None:
    done = [asdict(i) for i in items if i.status == DONE][:HISTORY_LIMIT]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ── one row ───────────────────────────────────────────────────────────────


class DownloadRow(QWidget):
    action = Signal(str, str)  # item id, action name

    def __init__(self, item: DownloadItem, t, icon) -> None:
        super().__init__()
        self.item = item
        self._t = t
        self._icon = icon
        self.setObjectName("dl_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)
        self.thumb = QLabel()
        self.thumb.setObjectName("dl_thumb")
        self.thumb.setFixedSize(THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("dl_title")
        self.status = QLabel()
        self.status.setObjectName("dl_status")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        col.addStretch()
        col.addWidget(self.title)
        col.addWidget(self.status)
        col.addWidget(self.bar)
        col.addStretch()
        lay.addLayout(col, stretch=1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        self._btns: dict[str, QPushButton] = {}
        for name in ("studio", "cancel", "retry", "remove"):
            b = QPushButton()
            b.setObjectName("primary_small" if name == "studio" else "secondary")
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _c=False, n=name: self.action.emit(self.item.id, n))
            self.buttons.addWidget(b)
            self._btns[name] = b
        self.refresh()

    def refresh(self) -> None:
        t, it = self._t, self.item
        self.title.setText(it.title or it.job.url)
        self.title.setToolTip(it.job.url)
        if it.thumb and Path(it.thumb).is_file():
            pm = QPixmap(it.thumb)
            if not pm.isNull():
                self.thumb.setPixmap(pm.scaled(THUMB, Qt.KeepAspectRatioByExpanding,
                                               Qt.SmoothTransformation))
        else:
            self.thumb.setPixmap(self._icon("music" if it.job.fmt == "mp3" else "film")
                                 .pixmap(28, 28))

        audio = it.job.audio_fmt.upper()
        kind = {"mp4": "MP4", "mp3": audio, "both": f"MP4 + {audio}"}.get(it.job.fmt, "")
        if it.job.live:
            kind = t("Live") + " · " + kind
        if it.job.playlist:
            kind = t("Playlist") + " · " + kind
        if it.status == QUEUED:
            text = t("Waiting…") + f"  ·  {kind}"
        elif it.status == RUNNING:
            text = it.message or t("Starting…")
        elif it.status == DONE:
            when = it.finished_at.replace("T", " ")[:16]
            if not it.files and it.message:  # e.g. nothing new in a playlist
                text = it.message
            elif it.missing():
                text = t("File was moved or deleted") + f"  ·  {when}"
            else:
                bits = [kind, human_size(it.size()), when]
                if it.subtitles():
                    bits.insert(1, t("subtitles"))
                text = "  ·  ".join(b for b in bits if b)
        elif it.status == CANCELLED:
            text = t("Cancelled")
        else:
            text = t("Failed: {msg}", msg=it.message)
        self.status.setText(text)
        self.status.setToolTip(it.message if it.status == FAILED else "")
        self.setProperty("state", it.status)
        self.status.setProperty("state", it.status)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        self.bar.setVisible(it.status == RUNNING)
        if it.status == RUNNING:
            if it.progress is None:
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(it.progress))

        has_media = it.status == DONE and not it.missing()
        visible = {
            "studio": has_media,
            "cancel": it.status == RUNNING,
            "retry": it.status in (FAILED, CANCELLED),
            "remove": it.status != RUNNING,
        }
        labels = {
            "studio": t("Send to Studio"),
            "cancel": t("Cancel"), "retry": t("Retry"), "remove": "✕",
        }
        tips = {"remove": t("Remove from list"),
                "studio": t("Add this file to the Studio timeline")}
        for name, b in self._btns.items():
            b.setVisible(visible[name])
            b.setText(labels[name])
            b.setToolTip(tips.get(name, ""))
            if name == "remove":
                b.setFixedWidth(36)


# ── the panel ─────────────────────────────────────────────────────────────


class DownloadsPanel(QWidget):
    """List of DownloadRows plus an empty-state hint."""

    action = Signal(str, str)  # item id, action name

    def __init__(self, t, icon) -> None:
        super().__init__()
        self._t = t
        self._icon = icon
        self._rows: dict[str, tuple[QListWidgetItem, DownloadRow]] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.list = QListWidget()
        self.list.setObjectName("dl_list")
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setSpacing(3)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setMinimumHeight(THUMB.height() + 24)  # one row; the rest scroll
        lay.addWidget(self.list, stretch=1)
        self.empty = QLabel()
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty, stretch=1)
        self._sync_empty()

    def set_translator(self, t) -> None:
        self._t = t
        self.empty.setText(t(
            "Downloads you start appear here. Paste several links at once to queue "
            "them; finished files can be opened or sent to the Studio."))
        for _item, row in self._rows.values():
            row._t = t
            row.refresh()

    def add(self, item: DownloadItem, *, top: bool = True) -> None:
        row = DownloadRow(item, self._t, self._icon)
        row.action.connect(self.action)
        li = QListWidgetItem()
        li.setSizeHint(QSize(100, THUMB.height() + 18))
        if top:
            self.list.insertItem(0, li)
        else:
            self.list.addItem(li)
        self.list.setItemWidget(li, row)
        self._rows[item.id] = (li, row)
        self._sync_empty()

    def refresh(self, item_id: str) -> None:
        if item_id in self._rows:
            self._rows[item_id][1].refresh()

    def remove(self, item_id: str) -> None:
        li, _row = self._rows.pop(item_id, (None, None))
        if li is not None:
            self.list.takeItem(self.list.row(li))
        self._sync_empty()

    def row(self, item_id: str) -> DownloadRow | None:
        pair = self._rows.get(item_id)
        return pair[1] if pair else None

    def _sync_empty(self) -> None:
        has = bool(self._rows)
        self.list.setVisible(has)
        self.empty.setVisible(not has)


# ── pasted-links preview ──────────────────────────────────────────────────


class LinkRow(QWidget):
    """One pasted link in the Video Info card: thumbnail, title, details, ✕."""

    remove_requested = Signal(str)  # url

    def __init__(self, url: str, t, icon) -> None:
        super().__init__()
        self.url = url
        self._t = t
        self._icon = icon
        self.info: dict | None = None
        self.error = ""
        self.setObjectName("dl_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setObjectName("dl_thumb")
        self.thumb.setFixedSize(LINK_THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("dl_title")
        self.meta = QLabel()
        self.meta.setObjectName("dl_status")
        col.addStretch()
        col.addWidget(self.title)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)
        meta_row.addWidget(self.meta)
        self.playlist_cb = QCheckBox()
        self.playlist_cb.setChecked(True)
        self.playlist_cb.setCursor(QCursor(Qt.PointingHandCursor))
        self.playlist_cb.hide()
        meta_row.addWidget(self.playlist_cb)
        meta_row.addStretch()
        col.addLayout(meta_row)
        col.addStretch()
        lay.addLayout(col, stretch=1)
        rm = QPushButton("✕")
        rm.setObjectName("secondary")
        rm.setFixedWidth(36)
        rm.setCursor(QCursor(Qt.PointingHandCursor))
        rm.clicked.connect(lambda: self.remove_requested.emit(self.url))
        self._rm = rm
        lay.addWidget(rm)
        self.refresh()

    def whole_playlist(self) -> bool:
        return bool(self.info and self.info.get("is_playlist")) and self.playlist_cb.isChecked()

    def set_info(self, info: dict | None, error: str = "") -> None:
        self.info, self.error = info, error
        self.refresh()

    def refresh(self) -> None:
        t, info = self._t, self.info
        self._rm.setToolTip(t("Remove this link"))
        if info is None:
            self.title.setText(self.url)
            self.meta.setText(self.error or t("Loading…"))
            self.meta.setProperty("state", "failed" if self.error else "")
            self.thumb.setPixmap(self._icon("film").pixmap(22, 22))
        else:
            self.title.setText(info.get("title") or self.url)
            bits = [info.get("uploader") or ""]
            if info.get("is_playlist"):
                count = info.get("playlist_count")
                bits.append(t("{count} videos", count=count) if count else t("Playlist"))
                self.playlist_cb.setText(t("Download whole playlist"))
            elif info.get("duration"):
                m, s = divmod(int(info["duration"]), 60)
                h, m = divmod(m, 60)
                bits.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
            self.meta.setText("  ·  ".join(b for b in bits if b))
            self.meta.setProperty("state", "")
            self.playlist_cb.setVisible(bool(info.get("is_playlist")))
            thumb = info.get("thumbnail_local")
            pm = QPixmap(thumb) if thumb and Path(thumb).is_file() else QPixmap()
            if not pm.isNull():
                self.thumb.setPixmap(pm.scaled(LINK_THUMB, Qt.KeepAspectRatioByExpanding,
                                               Qt.SmoothTransformation))
        self.title.setToolTip(self.url)
        self.meta.style().unpolish(self.meta)
        self.meta.style().polish(self.meta)
