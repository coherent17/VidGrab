"""The Subscriptions page: channels / playlists you follow, with their newest
videos (new ones marked) and a button that sends the ticked ones to the downloader."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import subscriptions as sb

_SUB = Qt.UserRole
_VID = Qt.UserRole + 1


class _Relay(QObject):
    done = Signal(str, str, object, str)  # url, title, items, error


class _FetchTask(QRunnable):
    def __init__(self, relay: _Relay, url: str) -> None:
        super().__init__()
        self._relay, self._url = relay, url

    def run(self) -> None:
        try:
            title, items = sb.fetch(self._url)
            self._relay.done.emit(self._url, title, items, "")
        except Exception as exc:  # noqa: BLE001 - network / yt-dlp errors are shown, not raised
            self._relay.done.emit(self._url, "", [], str(exc).splitlines()[0] if str(exc) else "error")


def minutes(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class SubscriptionsPage(QWidget):
    """*host* gives t(), config_dir(), download_links(urls) and online()."""

    def __init__(self, host, path) -> None:
        super().__init__()
        self.host = host
        self._path = path
        self.subs = sb.load(path)
        self._feeds: dict[str, list[sb.FeedItem]] = {}
        self._fresh: dict[str, set[str]] = {}
        self._palette: dict[str, str] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._relay = _Relay(self)
        self._relay.done.connect(self._fetched)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.url = QLineEdit()
        self.url.setMinimumHeight(38)
        self.url.returnPressed.connect(self._add)
        left.addWidget(self.url)
        row = QHBoxLayout()
        self.add_btn = QPushButton()
        self.add_btn.setObjectName("primary_small")
        self.add_btn.clicked.connect(self._add)
        self.remove_btn = QPushButton()
        self.remove_btn.setObjectName("secondary")
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addStretch()
        left.addLayout(row)
        self.sub_list = QListWidget()
        self.sub_list.setObjectName("sub_list")
        self.sub_list.setFixedWidth(280)
        self.sub_list.currentItemChanged.connect(lambda *_: self._show())
        left.addWidget(self.sub_list, stretch=1)
        lay.addLayout(left)

        card = QFrame()
        card.setObjectName("sub_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 16)
        cl.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel()
        head.addWidget(self.title, stretch=1)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self.refresh_current)
        head.addWidget(self.refresh_btn)
        cl.addLayout(head)
        self.status = QLabel()
        self.status.setWordWrap(True)
        cl.addWidget(self.status)
        self.feed = QListWidget()
        self.feed.setObjectName("sub_feed")
        self.feed.setFrameShape(QFrame.NoFrame)
        cl.addWidget(self.feed, stretch=1)
        foot = QHBoxLayout()
        self.new_btn = QPushButton()
        self.new_btn.setObjectName("secondary")
        self.new_btn.clicked.connect(self._tick_new)
        self.all_btn = QPushButton()
        self.all_btn.setObjectName("secondary")
        self.all_btn.clicked.connect(lambda: self._tick(True))
        self.get_btn = QPushButton()
        self.get_btn.setObjectName("primary")
        self.get_btn.clicked.connect(self._download)
        foot.addWidget(self.new_btn)
        foot.addWidget(self.all_btn)
        foot.addStretch()
        foot.addWidget(self.get_btn)
        cl.addLayout(foot)
        lay.addWidget(card, stretch=1)
        self.retranslate()
        self._fill_subs()

    # ── look / text ────────────────────────────────────────────────────

    def apply_theme(self, p: dict[str, str]) -> None:
        self._palette = p
        self.setStyleSheet(
            f"QFrame#sub_card {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']}; border-radius:16px; }}"
            f"QListWidget#sub_feed {{ background:transparent; border:none; outline:none; }}"
            f"QListWidget#sub_feed::item {{ padding:9px 8px; border-radius:8px; color:{p['TEXT']}; }}"
            f"QListWidget#sub_feed::item:hover {{ background:{p['SURFACE_HI']}; }}"
            f"QListWidget#sub_list::item {{ padding:10px 10px; }}"
            f"QListWidget#sub_feed::indicator {{ width:16px; height:16px; border-radius:4px;"
            f" border:1px solid {p['BORDER_HI']}; background:{p['FIELD']}; }}"
            f"QListWidget#sub_feed::indicator:checked {{ background:{p['ACCENT']}; border-color:{p['ACCENT']}; }}")
        self.title.setStyleSheet(f"font-size:20px; font-weight:800; color:{p['TEXT']};")
        self.status.setStyleSheet(f"font-size:12px; color:{p['TEXT_MUTED']};")
        self._show()

    def retranslate(self) -> None:
        t = self.host.t
        self.url.setPlaceholderText(t("Channel or playlist link…"))
        self.add_btn.setText(t("Follow"))
        self.remove_btn.setText(t("Unfollow"))
        self.refresh_btn.setText(t("Refresh"))
        self.new_btn.setText(t("Tick the new ones"))
        self.all_btn.setText(t("Tick all"))
        self.get_btn.setText(t("Download ticked"))
        self._show()

    # ── subscriptions ──────────────────────────────────────────────────

    def _fill_subs(self, keep: str | None = None) -> None:
        self.sub_list.blockSignals(True)
        self.sub_list.clear()
        chosen = None
        for s in self.subs:
            n = len(self._fresh.get(s.url, ()))
            item = QListWidgetItem((s.title or s.url) + (f"   ● {n}" if n else ""))
            item.setData(_SUB, s.url)
            item.setToolTip(s.url)
            self.sub_list.addItem(item)
            if s.url == keep:
                chosen = item
        self.sub_list.blockSignals(False)
        if self.sub_list.count():
            self.sub_list.setCurrentItem(chosen or self.sub_list.item(0))
        self._show()

    def _current(self) -> sb.Subscription | None:
        item = self.sub_list.currentItem()
        return next((s for s in self.subs if item and s.url == item.data(_SUB)), None)

    def _add(self) -> None:
        sub = sb.add(self.subs, self.url.text())
        self.url.clear()
        if sub is None:
            return
        sb.save(self._path, self.subs)
        self._fill_subs(keep=sub.url)
        self.refresh_current()

    def _remove(self) -> None:
        sub = self._current()
        if sub:
            self.subs.remove(sub)
            self._feeds.pop(sub.url, None)
            self._fresh.pop(sub.url, None)
            sb.save(self._path, self.subs)
            self._fill_subs()

    def refresh_current(self) -> None:
        sub = self._current()
        if sub is None:
            return
        if not self.host.online():
            self.status.setText(self.host.t("You appear to be offline."))
            return
        self.status.setText(self.host.t("Looking for new videos…"))
        self._pool.start(_FetchTask(self._relay, sub.url))

    def refresh_all(self) -> None:
        if self.host.online():
            for s in self.subs:
                self._pool.start(_FetchTask(self._relay, s.url))

    def _fetched(self, url: str, title: str, items: list, err: str) -> None:
        sub = next((s for s in self.subs if s.url == url), None)
        if sub is None:
            return
        if err:
            if (cur := self._current()) and cur.url == url:
                self.status.setText(self.host.t("Could not load this feed: {err}", err=err))
            return
        sub.title = title or sub.title
        self._feeds[url] = items
        self._fresh[url] = sb.new_ids(sub, items)
        sb.mark_seen(sub, items)
        sb.save(self._path, self.subs)
        cur = self._current()
        self._fill_subs(keep=cur.url if cur else None)

    # ── the feed ───────────────────────────────────────────────────────

    def _show(self) -> None:
        t = self.host.t
        sub = self._current()
        self.feed.clear()
        self.title.setText(sub.title or sub.url if sub else t("Follow a channel to see its newest videos here"))
        for w in (self.refresh_btn, self.new_btn, self.all_btn, self.get_btn):
            w.setEnabled(sub is not None)
        self.remove_btn.setEnabled(sub is not None)
        if sub is None:
            return
        items = self._feeds.get(sub.url)
        if items is None:
            self.status.setText(t("Press Refresh to load the newest videos."))
            return
        fresh = self._fresh.get(sub.url, set())
        self.status.setText(t("{n} videos, {new} new", n=len(items), new=len(fresh)))
        for it in items:
            row = QListWidgetItem(("●  " if it.id in fresh else "     ") + it.title
                                  + (f"    {minutes(it.duration)}" if it.duration else ""))
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Unchecked)
            row.setData(_VID, it.url)
            if it.id in fresh and self._palette:
                row.setBackground(QColor(self._palette["SEL"]))
            self.feed.addItem(row)

    def _tick(self, on: bool) -> None:
        for i in range(self.feed.count()):
            self.feed.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _tick_new(self) -> None:
        for i in range(self.feed.count()):
            self.feed.item(i).setCheckState(Qt.Checked if self.feed.item(i).text().lstrip().startswith("●")
                                            else Qt.Unchecked)

    def ticked(self) -> list[str]:
        return [self.feed.item(i).data(_VID) for i in range(self.feed.count())
                if self.feed.item(i).checkState() == Qt.Checked]

    def _download(self) -> None:
        urls = self.ticked()
        if urls:
            self.host.download_links(urls)

    def shutdown(self) -> None:
        self._pool.waitForDone(3000)


