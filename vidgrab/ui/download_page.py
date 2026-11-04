"""The Download page: link box, info card, search, queue."""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QCursor,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vidgrab.core import (
    suggest,
)
from vidgrab.core.downloader import (
    AUDIO_FORMATS,
    NAME_TEMPLATES,
    NETWORK,
    default_output_dir,
    find_ffmpeg,
    parse_link_list,
    search,
)
from vidgrab.core.fuzzy import FuzzyIndex
from vidgrab.core.jobs import DownloadJob
from vidgrab.core.network import ConnectionStatus, check_internet
from vidgrab.ui.chrome import (
    _THUMB_SIZE,
    PAGE_DOWNLOAD,
    PAGE_STUDIO,
    PAGE_SUBS,
    PAGE_TOOLS,
)
from vidgrab.ui.config import _config_dir
from vidgrab.ui.dialogs import _get_existing_directory
from vidgrab.ui.downloads_panel import (
    CANCELLED,
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    DownloadItem,
    LinkRow,
    load_history,
    save_history,
)
from vidgrab.ui.drawing import _HAND, _icon
from vidgrab.ui.helpers import _fmt_count, _fmt_duration, _thumb_cache_dir
from vidgrab.ui.pick_dialogs import FormatDialog, SearchPanel
from vidgrab.ui.ui_kit import EmptyState, attach_suggestions
from vidgrab.ui.widgets import (
    _SUB_LANGUAGES,
    _build_filter,
    _build_speed_row,
    _colored_check,
    _looks_like_url,
    _pick_summary,
    _read_speed,
    _wrap_scroll,
)
from vidgrab.ui.workers import _Worker


class DownloadPageMixin:
    """The Download page: link box, info card, search, queue."""

    def _build_download_form(self) -> QWidget:
        """Link bar (paste + Download) on top, then the video card beside the
        options card. The Download button lives in the link bar so the whole
        flow reads left to right, top to bottom."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 8)
        lay.setSpacing(14)

        # ── link bar ──
        bar = QWidget()
        bar.setObjectName("url_bar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        self._dl_source_title = QLabel()  # kept for _apply_language
        self._dl_source_title.hide()
        self._url = QLineEdit()
        self._url.setObjectName("url_input")
        self._url.setPlaceholderText("Paste a link, or type to search YouTube…")
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._start_action)
        self._suggest_list = attach_suggestions(self._url, self._url_suggestions, remote=self._online_suggestions, on_pick=self._pick_suggestion,
                           merge=suggest.merge)
        bl.addWidget(self._url, stretch=1)
        pb = QPushButton("Paste")
        pb.setObjectName("secondary")
        pb.setFixedHeight(44)
        pb.setMinimumWidth(84)
        pb.setCursor(QCursor(_HAND))
        pb.clicked.connect(self._paste_url)
        bl.addWidget(pb)
        self._dl_paste = pb
        ib = QPushButton("Import…")
        ib.setObjectName("secondary")
        ib.setFixedHeight(44)
        ib.setMinimumWidth(96)
        ib.setCursor(QCursor(_HAND))
        ib.clicked.connect(self._import_links)
        bl.addWidget(ib)
        self._dl_import = ib
        self._action = QPushButton("⬇  Download")
        self._action.setObjectName("primary")
        self._action.setProperty("compact", True)
        self._action.setFixedHeight(48)
        self._action.setMinimumWidth(190)
        self._action.setCursor(QCursor(_HAND))
        self._action.setEnabled(False)
        self._action.clicked.connect(self._start_action)
        bl.addWidget(self._action)
        lay.addWidget(bar)
        self._update_note = QPushButton()  # only shown when a newer yt-dlp exists
        self._update_note.setObjectName("secondary")
        self._update_note.setCursor(QCursor(_HAND))
        self._update_note.clicked.connect(self._update_note_clicked)
        self._update_note.hide()
        lay.addWidget(self._update_note, alignment=Qt.AlignLeft)
        self._release_note = QPushButton()  # only shown when a newer VidGrab was released
        self._release_note.setObjectName("secondary")
        self._release_note.setCursor(QCursor(_HAND))
        self._release_note.clicked.connect(self._release_clicked)
        self._release_note.hide()
        lay.addWidget(self._release_note, alignment=Qt.AlignLeft)

        body = QHBoxLayout()
        body.setSpacing(14)
        body_page = QWidget()
        body_page.setLayout(body)
        # the video card + options, or (while a search is open) its results
        self._body_stack = QStackedWidget()
        self._body_stack.addWidget(body_page)
        self._search_panel = SearchPanel(lambda *a, **k: self._t(*a, **k), _thumb_cache_dir())
        self._search_panel.chosen.connect(self._search_chosen)
        self._search_panel.closed.connect(self._close_search)
        self._body_stack.addWidget(self._search_panel)

        # ── video card ──
        info, info_title, card_lay = self._card("VIDEO INFO", "info_card", "source")
        self._dl_info_title = info_title
        # two views: one video's details, or a list when several links are pasted
        self._info_stack = QStackedWidget()
        card_lay.addWidget(self._info_stack, stretch=1)
        single = QWidget()
        ivl = QVBoxLayout(single)
        ivl.setContentsMargins(0, 0, 0, 0)
        ivl.setSpacing(6)
        self._info_stack.addWidget(single)
        multi = QWidget()
        mvl = QVBoxLayout(multi)
        mvl.setContentsMargins(0, 0, 0, 0)
        mvl.setSpacing(6)
        self._multi_lbl = QLabel()
        self._multi_lbl.setObjectName("info_name")
        mvl.addWidget(self._multi_lbl)
        self._link_list = QListWidget()
        self._link_list.setObjectName("dl_list")
        self._link_list.setSelectionMode(QListWidget.NoSelection)
        self._link_list.setFocusPolicy(Qt.NoFocus)
        self._link_list.setSpacing(2)
        self._link_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        mvl.addWidget(self._link_list, stretch=1)
        self._info_stack.addWidget(multi)
        self._info_empty = EmptyState(lambda c: self.icon("download", c, 56).pixmap(56, 56))
        self._info_empty.add_button("", self._paste_url, primary=True)
        self._info_empty.add_button("", lambda: (self._url.setFocus(), self._url.selectAll()))
        ivl.addWidget(self._info_empty, stretch=1)
        self._info_thumb = QLabel()
        self._info_thumb.setObjectName("info_thumb")
        self._info_thumb.setFixedSize(_THUMB_SIZE)
        self._info_thumb.setAlignment(Qt.AlignCenter)
        ivl.addWidget(self._info_thumb, alignment=Qt.AlignHCenter)
        self._info_name = QLabel()
        self._info_name.setObjectName("info_name")
        self._info_name.setWordWrap(True)
        self._info_meta = QLabel()
        self._info_meta.setObjectName("info_meta")
        self._info_meta.setWordWrap(True)
        self._playlist_cb = QCheckBox()
        self._playlist_cb.setCursor(QCursor(_HAND))
        self._playlist_cb.hide()
        self._live_cb = QCheckBox()  # shown for a live stream / premiere
        self._live_cb.setCursor(QCursor(_HAND))
        self._live_cb.hide()
        ivl.addSpacing(4)
        ivl.addWidget(self._info_name)
        ivl.addWidget(self._info_meta)
        ivl.addWidget(self._playlist_cb)
        ivl.addWidget(self._live_cb)
        ivl.addStretch()
        body.addWidget(info, stretch=5)

        # ── options card: one labelled row per setting ──
        opts, _opts_title, ol = self._card("OPTIONS", "options_card", "format")
        self._dl_options_title = _opts_title
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        def cap(attr: str) -> QLabel:
            lbl = QLabel()
            lbl.setObjectName("field_cap")
            setattr(self, attr, lbl)
            return lbl

        self._mp4 = _colored_check("MP4 (video)", "#10b981")
        self._mp4.setChecked(True)
        self._mp3 = _colored_check("MP3 (audio)", "#f59e0b")
        self._mp4.toggled.connect(self._populate_quality)
        self._mp3.toggled.connect(self._populate_quality)
        fr = QHBoxLayout()
        fr.setSpacing(16)
        fr.addWidget(self._mp4)
        fr.addWidget(self._mp3)
        self._audio_fmt = QComboBox()  # MP3 / M4A / Opus / FLAC / WAV, only with Audio ticked
        self._audio_fmt.setCursor(QCursor(_HAND))
        self._audio_fmt.activated.connect(lambda _i: self._sync_audio_options())
        fr.addWidget(self._audio_fmt)
        fr.addStretch()
        self._mp4.toggled.connect(self._sync_audio_options)
        self._mp3.toggled.connect(self._sync_audio_options)
        grid.addWidget(cap("_dl_format_title"), 0, 0)
        grid.addLayout(fr, 0, 1)

        self._quality_lbl = cap("_quality_lbl")
        self._quality = QComboBox()
        self._quality.setCursor(QCursor(_HAND))
        self._quality.setMinimumWidth(170)
        qr = QHBoxLayout()
        qr.setSpacing(10)
        qr.addWidget(self._quality)
        self._exact_btn = QPushButton()
        self._exact_btn.setObjectName("secondary")
        self._exact_btn.setCursor(QCursor(_HAND))
        self._exact_btn.setEnabled(False)
        self._exact_btn.clicked.connect(self._choose_format)
        self._exact_pick: dict | None = None
        qr.addWidget(self._exact_btn)
        qr.addStretch()
        grid.addWidget(self._quality_lbl, 1, 0)
        grid.addLayout(qr, 1, 1)
        self._populate_quality()

        self._ts = QLineEdit()
        self._ts.setPlaceholderText("0:00")
        self._ts.setMaximumWidth(100)
        self._te = QLineEdit()
        self._te.setPlaceholderText("∞")
        self._te.setMaximumWidth(100)
        self._ts_lbl = QLabel("Start:")
        self._te_lbl = QLabel("End:")
        tr = QHBoxLayout()
        tr.setSpacing(8)
        for w in (self._ts_lbl, self._ts):
            tr.addWidget(w)
        tr.addSpacing(8)
        for w in (self._te_lbl, self._te):
            tr.addWidget(w)
        tr.addStretch()
        grid.addWidget(cap("_dl_trim_title"), 2, 0)
        grid.addLayout(tr, 2, 1)

        self._hflip = QCheckBox("Horizontal")
        self._vflip = QCheckBox("Vertical")
        flr = QHBoxLayout()
        flr.setSpacing(16)
        flr.addWidget(self._hflip)
        flr.addWidget(self._vflip)
        flr.addStretch()
        grid.addWidget(cap("_dl_flip_title"), 3, 0)
        grid.addLayout(flr, 3, 1)

        self._speed, _sv, srow = _build_speed_row()
        grid.addWidget(cap("_dl_speed_title"), 4, 0)
        grid.addLayout(srow, 4, 1)

        self._out = QLineEdit(str(default_output_dir()))
        self._out.setClearButtonEnabled(True)
        bb = QPushButton("Browse…")
        bb.setObjectName("secondary")
        bb.setCursor(QCursor(_HAND))
        bb.clicked.connect(lambda: self._browse_folder(self._out))
        self._dl_browse = bb
        sr = QHBoxLayout()
        sr.setSpacing(8)
        sr.addWidget(self._out, stretch=1)
        sr.addWidget(bb)
        self._sub_cb = QCheckBox("Download subtitles")
        self._sub_cb.setCursor(QCursor(_HAND))
        self._sub_lang = QComboBox()
        self._sub_mode = QComboBox()
        for w in (self._sub_lang, self._sub_mode):
            w.setCursor(QCursor(_HAND))
            w.setEnabled(False)
            # wide enough for the longest entry (it was clipped to "Traditional Chir")
            w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._sub_lang.setToolTip("If the video has no subtitles in this language, YouTube's "
                                  "automatic translation is used.")
        self._sub_cb.toggled.connect(self._sync_sub_options)
        self._mp4.toggled.connect(self._sync_sub_options)
        self._mp3.toggled.connect(self._sync_sub_options)
        subr = QVBoxLayout()  # the checkbox, then its two lists: one row was too narrow for the language name
        subr.setSpacing(8)
        subr.addWidget(self._sub_cb)
        subc = QHBoxLayout()
        subc.setSpacing(10)
        subc.addWidget(self._sub_lang)
        subc.addWidget(self._sub_mode)
        subc.addStretch()
        subr.addLayout(subc)
        grid.addWidget(cap("_dl_subs_title"), 5, 0)
        grid.addLayout(subr, 5, 1)

        grid.addWidget(cap("_dl_save_title"), 6, 0)
        grid.addLayout(sr, 6, 1)
        ol.addLayout(grid)
        ol.addStretch()
        body.addWidget(opts, stretch=6)
        lay.addWidget(self._body_stack)
        # progress + log fill the rest of the page
        self._bottom = self._build_bottom()
        lay.addWidget(self._bottom, stretch=1)
        return _wrap_scroll(page)

    def _paste_url(self) -> None:
        """Ctrl+V. A text box with the focus (the Channels link, a search box…) pastes
        for itself; the Download page's link box and the Studio take it otherwise."""
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit | QPlainTextEdit | QTextEdit) and focus is not self._url \
                and not focus.isReadOnly():
            focus.paste()
            return
        page = self._stack.currentIndex()
        if page == PAGE_STUDIO:  # Ctrl+V there pastes Studio items
            self._studio.paste()
        elif page == PAGE_SUBS:
            self._subs.url.setText(QApplication.clipboard().text().strip())
            self._subs.url.setFocus()
        elif page == PAGE_DOWNLOAD:
            text = QApplication.clipboard().text()
            if text:
                links = re.findall(r"https?://\S+", text)
                self._url.setText(" ".join(links) if len(links) > 1 else text.strip())

    def _import_links(self) -> None:
        """Fill the link box from a text file with one link per line."""
        path = self.pick_file(self._t("Choose a list of links"), ("Documents", "Downloads"),
                              self._t("Text files (*.txt *.csv *.md)") + ";;" + self._t("All files (*)"))
        if not path:
            return
        try:
            links = parse_link_list(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            QMessageBox.warning(self, self._t("Import…"), str(exc))
            return
        if not links:
            QMessageBox.information(self, self._t("Import…"),
                                    self._t("No links found in that file."))
            return
        self._url.setText(" ".join(links))

    def _setup_probe(self) -> None:
        """Debounce URL edits; fetching metadata starts ~700 ms after the
        user stops typing (or pastes a link)."""
        self._probe_token = 0
        self._probe_workers: list[_Worker] = []
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(700)
        self._probe_timer.timeout.connect(self._start_probe)
        self._url.textChanged.connect(self._on_url_changed)

    def _on_url_changed(self, text: str) -> None:
        # Ctrl+V of a multi-line list keeps line breaks in the one-line box;
        # show the links separated by spaces instead
        if "\n" in text or "\r" in text or "\t" in text:
            clean = " ".join(text.split())
            self._url.blockSignals(True)
            self._url.setText(clean)
            self._url.blockSignals(False)
        self._update_action_label()
        self._probe_timer.start()

    def _start_probe(self) -> None:
        self._probe_token += 1
        links = self._links()
        if (self._body_stack.currentIndex() == 1 and links
                and all(_looks_like_url(link) for link in links)):
            self._close_search()  # a link was typed: back to the video card
        if len(links) > 1:
            self._show_links(links)
            return
        self._info_stack.setCurrentIndex(0)
        url = links[0] if links else ""
        if url and not _looks_like_url(url):  # words: Enter searches YouTube
            self._probe_data = None
            self._reset_info_card()
            self._info_meta.setText(self._t("Press Enter to search YouTube for “{q}”", q=url))
            self._sync_info_empty()
            return
        if not url or self._internet_online is not True:
            if not url:
                self._reset_info_card()
            return
        self._info_meta.setText(self._t("Loading\u2026"))
        self._sync_info_empty()
        token = self._probe_token
        worker = _Worker(
            "probe",
            url=url,
            thumb_dir=_thumb_cache_dir(),
            translate=self._t,
        )
        worker.probed.connect(lambda r, u=url: self._probe_cache.__setitem__(u, r))
        worker.probed.connect(lambda r, tok=token: self._on_probe_result(r, tok))
        worker.probe_error.connect(lambda e, tok=token: self._on_probe_error(e, tok))
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _drop_probe_worker(self, worker: _Worker) -> None:
        if worker in self._probe_workers:
            self._probe_workers.remove(worker)

    def _on_probe_result(self, result: dict, token: int) -> None:
        if token != self._probe_token:
            return
        self._render_info(result)

    def _show_links(self, links: list[str]) -> None:
        """Show every pasted link with its thumbnail / title; fetch the
        details of each link once, in the background."""
        self._probe_data = None
        self._info_stack.setCurrentIndex(1)
        self._multi_lbl.setText(self._t("{n} links ready to download", n=len(links)))
        for url in [u for u in self._link_rows if u not in links]:
            item, _row = self._link_rows.pop(url)
            self._link_list.takeItem(self._link_list.row(item))
        for pos, url in enumerate(links):
            if url in self._link_rows:
                item, _row = self._link_rows[url]
                cur = self._link_list.row(item)
                if cur != pos:
                    widget = self._link_list.itemWidget(item)
                    self._link_list.takeItem(cur)
                    self._link_list.insertItem(pos, item)
                    self._link_list.setItemWidget(item, widget)
                continue
            row = LinkRow(url, self._t, lambda kind: _icon(kind, "#7b80aa", 22))
            row.remove_requested.connect(self._remove_link)
            item = QListWidgetItem()
            item.setSizeHint(QSize(100, 70))
            self._link_list.insertItem(pos, item)
            self._link_list.setItemWidget(item, row)
            self._link_rows[url] = (item, row)
            if url in self._probe_cache:
                row.set_info(self._probe_cache[url])
            elif url in self._probe_errors:
                row.set_info(None, self._probe_errors[url])
            elif self._internet_online:
                self._probe_link(url)

    def _probe_link(self, url: str) -> None:
        worker = _Worker("probe", url=url, thumb_dir=_thumb_cache_dir(), translate=self._t)

        def ok(result: dict, u=url) -> None:
            self._probe_cache[u] = result
            if u in self._link_rows:
                self._link_rows[u][1].set_info(result)

        def fail(msg: str, u=url) -> None:
            self._probe_errors[u] = msg
            if u in self._link_rows:
                self._link_rows[u][1].set_info(None, msg)

        worker.probed.connect(ok)
        worker.probe_error.connect(fail)
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _remove_link(self, url: str) -> None:
        links = [u for u in self._links() if u != url]
        self._url.setText(" ".join(links))
        self._start_probe()

    def _on_probe_error(self, msg: str, token: int) -> None:
        if token != self._probe_token:
            return
        self._probe_data = None
        self._info_name.setText("")
        self._info_thumb.setPixmap(QPixmap())
        self._playlist_cb.hide()
        self._info_meta.setText(msg)
        self._sync_info_empty()

    def _sync_info_empty(self) -> None:
        """The video card shows a "paste a link" invitation until there is something to show."""
        empty = not self._info_name.text() and self._info_meta.text() == self._t(
            "Paste a link to see its details\u2026")
        self._info_empty.setVisible(empty)
        for w in (self._info_thumb, self._info_name, self._info_meta):
            w.setVisible(not empty)

    def _reset_info_card(self) -> None:
        self._probe_data = None
        self._info_stack.setCurrentIndex(0)
        self._info_name.setText("")
        self._info_thumb.setPixmap(QPixmap())
        self._playlist_cb.hide()
        self._info_meta.setText(
            self._t("Paste a link to see its details\u2026")
        )
        self._sync_info_empty()
        self._live_cb.hide()
        self._exact_pick = None
        self._exact_btn.setEnabled(False)
        self._sync_audio_options()

    def _render_info(self, result: dict) -> None:
        self._probe_data = result
        self._info_name.setText(result.get("title") or "")
        meta: list[str] = []
        uploader = result.get("uploader") or ""
        if uploader:
            meta.append(uploader)
        duration = result.get("duration")
        if duration:
            meta.append(_fmt_duration(duration))
        if result.get("is_playlist"):
            count = result.get("playlist_count")
            if count:
                meta.append(self._t("{count} videos", count=count))
                self._playlist_cb.setText(
                    self._t("Download playlist ({count} videos)", count=count)
                )
            else:
                self._playlist_cb.setText(self._t("Download playlist"))
            self._playlist_cb.setVisible(True)
        else:
            formats = result.get("formats") or []
            if formats:
                top = formats[0].split(" \u00b7 ", 1)[0]
                meta.append(self._t("Up to {res}", res=top))
            likes = result.get("like_count")
            if likes:
                meta.append(self._t("Likes: {n}", n=_fmt_count(likes)))
            dislikes = result.get("dislike_count")
            if dislikes:
                meta.append(self._t("Dislikes: {n}", n=_fmt_count(dislikes)))
            comments = result.get("comment_count")
            if comments:
                meta.append(self._t("Comments: {n}", n=_fmt_count(comments)))
            self._playlist_cb.setVisible(False)
        status = result.get("live_status")
        live = not result.get("is_playlist") and status in ("is_live", "is_upcoming")
        if live:
            meta.append(self._t("Live now") if status == "is_live" else self._t("Not started yet"))
            self._live_cb.setText(
                self._t("Record this live stream from the start") if status == "is_live"
                else self._t("Wait for it to start, then record it"))
            self._live_cb.setChecked(True)
        self._live_cb.setVisible(live)
        self._pick_formats(result)
        self._info_meta.setText("  \u00b7  ".join(meta))
        self._sync_info_empty()
        self._info_thumb.setPixmap(QPixmap())
        thumb = result.get("thumbnail_local")
        if thumb and Path(thumb).is_file():
            pm = QPixmap(thumb)
            if not pm.isNull():
                scaled = pm.scaled(
                    _THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._info_thumb.setPixmap(scaled)

    def _fill_audio_formats(self) -> None:
        prev = self._audio_fmt.currentData() or self.setting("audio_format") or "mp3"
        self._audio_fmt.blockSignals(True)
        self._audio_fmt.clear()
        for key, label in (("mp3", "MP3"), ("m4a", "M4A (AAC)"), ("opus", "Opus"),
                           ("flac", self._t("FLAC (lossless)")), ("wav", self._t("WAV (lossless)"))):
            self._audio_fmt.addItem(label, key)
        self._audio_fmt.setCurrentIndex(max(0, self._audio_fmt.findData(prev)))
        self._audio_fmt.blockSignals(False)

    def _sync_audio_options(self) -> None:
        """The audio format choice shows with Audio ticked; lossless formats have
        no bitrate; a picked exact format only fits the kind of download it was for."""
        audio = self._mp3.isChecked()
        self._audio_fmt.setVisible(audio)
        lossless = not AUDIO_FORMATS[self._audio_fmt.currentData() or "mp3"][3]
        if self._exact_pick and bool(self._exact_pick["vcodec"]) == self._audio_only():
            self._exact_pick = None
        self._update_exact_btn()
        self._quality.setEnabled(not (audio and not self._mp4.isChecked() and lossless)
                                 and not (self._exact_pick and self._exact_btn.isEnabled()))

    def _audio_only(self) -> bool:
        return self._mp3.isChecked() and not self._mp4.isChecked()

    def _pick_formats(self, result: dict) -> None:
        """A new video was described: forget an earlier pick; enable the button
        when there is a list to choose from."""
        self._exact_pick = None
        self._exact_btn.setEnabled(bool(result.get("format_list")) and not result.get("is_playlist"))
        self._sync_audio_options()

    def _update_exact_btn(self) -> None:
        pick = self._exact_pick
        self._exact_btn.setText(self._t("Exact format…") if not pick else
                                self._t("Exact: {what}", what=_pick_summary(pick)))
        self._exact_btn.setToolTip(self._t("Choose one exact resolution and codec from the "
                                           "formats this video offers"))

    def _choose_format(self) -> None:
        data = self._probe_data
        if not data or not data.get("format_list"):
            return
        dlg = FormatDialog(self, self._t, data["format_list"], self._audio_only(),
                           self._exact_pick["id"] if self._exact_pick else None)
        self._format_dlg = dlg  # for tests
        if dlg.exec() == QDialog.Accepted:
            self._exact_pick = dlg.chosen()
            self._sync_audio_options()

    def _url_suggestions(self, text: str) -> list[str]:
        """Best matches for words typed in the link box: earlier searches and the
        titles of what was downloaded (never for a link)."""
        if _looks_like_url(text) or "://" in text:
            return []
        ix = FuzzyIndex()
        for q in self.setting("recent_searches") or []:
            ix.add(q, q, (q, 2.0))
        for item in self._queue:
            if item.status == DONE and item.title:
                ix.add(item.title, item.title, (item.title, 1.0))
        return ix.suggest(text, 8)

    def _online_suggestions(self, text: str) -> list[str]:
        """YouTube's suggestions for the words typed (runs on a worker thread)."""
        if not self.setting("online_suggest") or _looks_like_url(text) or "://" in text \
                or self._internet_online is False:
            return []
        return suggest.youtube_suggestions(text, proxy=NETWORK.proxy,
                                           lang="zh-TW" if self._lang == "zh" else "en")

    def _pick_suggestion(self, text: str) -> None:
        """A suggestion was chosen: it is the search, no Enter needed."""
        self._url.setText(text)
        self._start_action()

    def _remember_search(self, query: str) -> None:
        keep = [q for q in (self.setting("recent_searches") or []) if q.casefold() != query.casefold()]
        self.set_setting("recent_searches", [query, *keep][:30])

    def _search_flow(self, query: str) -> None:
        """Words in the link box: show YouTube's results to tick, then fill the box with them."""
        if self._internet_online is not True:
            QMessageBox.warning(self, self._t("No internet"), self._t(
                "You appear to be offline.\nVidGrab needs a live connection."))
            return
        self._suggest_list.dismiss()  # never leave the drop-down over the results
        self._remember_search(query.strip())
        self._body_stack.setCurrentIndex(1)
        self._search_panel.start(query, lambda q: search(q, 12, translate=self._t))

    def _search_chosen(self, urls: list[str]) -> None:
        self._close_search()
        if urls:
            self._url.setText(" ".join(urls))
            self._start_probe()

    def _close_search(self) -> None:
        self._search_panel.stop()
        self._body_stack.setCurrentIndex(0)

    def _update_action_label(self) -> None:
        words = bool(self._url.text().strip()) and not _looks_like_url(self._links()[0]) \
            if self._links() else False
        self._action.setText(self._t("Search") if words else self._t("\u2b07  Download"))

    def _start_dir(self, *prefer: str) -> str:
        """Folder file pickers open in: the last folder used, else the first
        existing of ~/<prefer…>, else home (never the app's own folder)."""
        last = getattr(self, "_last_dir", None)
        if last and Path(last).is_dir():
            return last
        for name in prefer:
            d = Path.home() / name
            if d.is_dir():
                return str(d)
        return str(Path.home())

    def _remember_dir(self, path: str) -> None:
        if path:
            self._last_dir = str(Path(path).parent)

    def _browse_folder(self, target: QLineEdit) -> None:
        folder = _get_existing_directory(
            self, "Select Output Folder", target.text()
        )
        if folder:
            target.setText(folder)

    def _do_probe(self) -> None:
        if self._probe_thread is None or not self._probe_thread.is_alive():
            self._probe_thread = threading.Thread(
                target=self._probe_worker, daemon=True
            )
            self._probe_thread.start()

    def _probe_worker(self) -> None:
        self._pending_status = check_internet(timeout=2.5)

    def _poll_internet(self) -> None:
        status = self._pending_status
        if status is not None:
            self._pending_status = None
            self._apply_internet(status)

    def _apply_internet(self, status: ConnectionStatus) -> None:
        came_back = status.online and self._internet_online is False
        self._internet_online = status.online
        self._recheck.start(
            self._RECHECK_ONLINE_MS if status.online else self._RECHECK_OFFLINE_MS
        )
        if came_back and self._url.text().strip() and self._probe_data is None:
            self._probe_timer.start()  # fetch the video info we couldn't before
        if status.online:
            self._net_lbl.setText(f"\u25cf {self._t('Online')}")
            self._label_pill(self._net_lbl, "#10b981")
        else:
            self._net_lbl.setText(f"\u25cb {self._t('Offline')}")
            self._label_pill(self._net_lbl, "#ef4444")
        self._refresh_btn()

    def _refresh_btn(self) -> None:
        self._action.setEnabled(self._internet_online is True)

    def _set_busy(self, busy: bool) -> None:
        """Studio render in progress (downloads run in their own queue)."""
        self._busy = busy
        self._studio.set_busy(busy)

    def _start_action(self) -> None:
        if self._stack.currentIndex() == PAGE_DOWNLOAD:
            self._start_download()

    def _start_studio(self, task: str, kwargs: dict) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._run(task, **kwargs)

    def _links(self) -> list[str]:
        """Every link in the URL box (several can be pasted at once)."""
        text = self._url.text().strip()
        found = re.findall(r"https?://\S+", text)
        return found or ([text] if text else [])

    def _start_download(self) -> None:
        links = self._links()
        if len(links) == 1 and not _looks_like_url(links[0]):
            self._search_flow(links[0])
            return
        if not links:
            QMessageBox.warning(self, self._t("Missing URL"), self._t("Please paste a YouTube link."))
            return
        if not self._internet_online:
            QMessageBox.warning(
                self,
                self._t("No internet"),
                self._t("You appear to be offline.\nVidGrab needs a live connection."),
            )
            return
        if not find_ffmpeg() and not self._offer_ffmpeg():
            QMessageBox.critical(
                self,
                self._t("ffmpeg required"),
                self._t(
                    "Downloads need ffmpeg for MP3 and most MP4 merges. "
                    "Install ffmpeg or rebuild with an embedded copy."
                ),
            )
            return
        fmt = "both" if (self._mp4.isChecked() and self._mp3.isChecked()) else (
            "mp3" if self._mp3.isChecked() else "mp4")
        single_playlist = (len(links) == 1 and self._playlist_cb.isVisible()
                           and self._playlist_cb.isChecked())
        subs = self._sub_lang.currentData() if self._sub_cb.isChecked() else None
        exact = self._exact_pick if self._exact_btn.isEnabled() else None
        live = not self._live_cb.isHidden() and self._live_cb.isChecked()
        for url in links:
            job = DownloadJob(
                url=url,
                output_dir=self._out.text().strip() or str(default_output_dir()),
                fmt=fmt,
                quality=(f"{exact['height']}p" if exact and exact["vcodec"] and exact["height"]
                         and self._mp4.isChecked() else self._quality.currentData()),
                video_filter=_build_filter(self._hflip, self._vflip),
                speed=_read_speed(self._speed),
                section_start=self._ts.text().strip() or None,
                section_end=self._te.text().strip() or None,
                playlist=single_playlist if len(links) == 1 else (
                    url in self._link_rows and self._link_rows[url][1].whole_playlist()),
                subtitles=subs,
                burn_subtitles=bool(subs) and self._sub_mode.currentData() == "burn"
                and fmt != "mp3",
                name_template=NAME_TEMPLATES.get(self.setting("name_template") or "title",
                                                 NAME_TEMPLATES["title"]),
                audio_fmt=self._audio_fmt.currentData() or "mp3",
                format_id=exact["id"] if exact and len(links) == 1 else None,
                live=live and len(links) == 1,
                skip_downloaded=bool(self.setting("skip_downloaded")),
            )
            item = DownloadItem(job=job)
            probe = (self._probe_data if (len(links) == 1 and self._probe_data)
                     else self._probe_cache.get(url))
            if probe:
                item.title = probe.get("title") or ""
                item.thumb = probe.get("thumbnail_local") or ""
            self._queue.append(item)
            self._downloads.add(item)
            if not probe:
                self._probe_item(item)
        self._probe_token += 1  # ignore an in-flight info fetch for the old link
        self._url.clear()
        self._reset_info_card()
        self._link_list.clear()
        self._link_rows.clear()
        self._update_queue_summary()
        self._run_next_job()

    def _probe_item(self, item: DownloadItem) -> None:
        """Fill in title / thumbnail for a queued link in the background."""
        worker = _Worker("probe", url=item.job.url, thumb_dir=_thumb_cache_dir(),
                         translate=self._t)

        def done(result: dict, it=item) -> None:
            if not it.title:
                it.title = result.get("title") or ""
            it.thumb = it.thumb or result.get("thumbnail_local") or ""
            self._downloads.refresh(it.id)
            if it.status == DONE:
                save_history(self._history_path(), self._queue)

        worker.probed.connect(done)
        worker.finished.connect(lambda w=worker: self._drop_probe_worker(w))
        self._probe_workers.append(worker)
        worker.start()

    def _history_path(self) -> Path:
        return _config_dir() / "history.json"

    def _load_history(self) -> None:
        for item in load_history(self._history_path()):
            self._queue.append(item)
            self._downloads.add(item, top=False)
        self._update_queue_summary()

    def _run_next_job(self) -> None:
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        item = next((i for i in self._queue if i.status == QUEUED), None)  # oldest first
        if item is None:
            self._dl_worker = None
            self._update_queue_summary()
            if self._finished_since_idle:
                self._notify_downloads_done(self._finished_since_idle)
                self._finished_since_idle = 0
                self._refresh_storage()
            return
        item.status, item.progress, item.message = RUNNING, None, ""
        self._downloads.refresh(item.id)
        worker = _Worker("job", job=item.job, translate=self._t)
        worker.progress.connect(lambda msg, pct, it=item: self._on_job_progress(it, msg, pct))
        worker.log.connect(self._append_log)
        worker.finished.connect(lambda res, it=item: self._on_job_done(it, res))
        worker.error.connect(lambda msg, it=item: self._on_job_failed(it, msg))
        worker.cancelled.connect(lambda it=item: self._on_job_cancelled(it))
        self._dl_worker = worker
        self._dl_item = item
        self._update_queue_summary()
        worker.start()

    def _on_job_progress(self, item: DownloadItem, msg: str, pct: object) -> None:
        item.message = msg
        item.progress = float(pct) if isinstance(pct, (int, float)) else None
        self._downloads.refresh(item.id)

    def _on_job_done(self, item: DownloadItem, result: object) -> None:
        files = [str(p) for p in (result if isinstance(result, (list, tuple)) else [result])]
        item.status, item.files, item.message = DONE, files, ""
        if not files:  # a playlist with nothing new in it
            item.message = self._t("Nothing new: every video was downloaded before.")
        self._finished_since_idle += 1
        item.finished_at = datetime.now().astimezone().isoformat(timespec="minutes")
        if not item.title and item.media():
            item.title = Path(item.media()[0]).stem
        self._downloads.refresh(item.id)
        save_history(self._history_path(), self._queue)
        self._run_next_job()

    def _on_job_failed(self, item: DownloadItem, msg: str) -> None:
        item.status, item.message = FAILED, msg
        self._append_log(f"Error ({item.job.url}): {msg}")
        self._downloads.refresh(item.id)
        self._run_next_job()

    def _on_job_cancelled(self, item: DownloadItem) -> None:
        item.status, item.message = CANCELLED, ""
        self._downloads.refresh(item.id)
        self._run_next_job()

    def _update_queue_summary(self) -> None:
        waiting = sum(1 for i in self._queue if i.status in (QUEUED, RUNNING))
        done = sum(1 for i in self._queue if i.status == DONE)
        if waiting:
            text = self._t("{n} in queue", n=waiting)
        else:
            text = self._t("{n} downloaded", n=done) if done else ""
        self._queue_lbl.setText(text)
        self._clear_done_btn.setVisible(any(
            i.status in (DONE, FAILED, CANCELLED) for i in self._queue))

    def _on_download_action(self, item_id: str, action: str) -> None:
        item = next((i for i in self._queue if i.id == item_id), None)
        if item is None:
            return
        if action == "cancel" and item is self._dl_item and self._dl_worker is not None:
            self._dl_worker.cancel()
            item.message = self._t("Cancelling…")
            self._downloads.refresh(item.id)
        elif action == "retry":
            item.status, item.progress, item.message = QUEUED, 0.0, ""
            self._downloads.refresh(item.id)
            self._run_next_job()
        elif action == "remove":
            self._queue.remove(item)
            self._downloads.remove(item.id)
            save_history(self._history_path(), self._queue)
        elif action == "studio":
            self._send_to_studio(item)
        self._update_queue_summary()

    def _send_to_studio(self, item: DownloadItem) -> None:
        media = [f for f in item.media() if Path(f).is_file()]
        # MP4 + MP3 pairs: the video is what belongs on the timeline
        videos = [f for f in media if f.lower().endswith(".mp4")] or media
        if not videos:
            return
        first = not self._studio.clips()
        self._studio.add_clips(videos[:1])
        srt = item.subtitles()
        if first and srt and Path(srt).is_file():
            self._studio.load_srt(srt)
        self._sidebar.select(PAGE_STUDIO)

    def _clear_finished(self) -> None:
        for item in [i for i in self._queue if i.status in (DONE, FAILED, CANCELLED)]:
            self._queue.remove(item)
            self._downloads.remove(item.id)
        save_history(self._history_path(), self._queue)
        self._update_queue_summary()

    def _fill_sub_options(self) -> None:
        t = self._t
        for combo, items in (
            (self._sub_lang, [(t(name), key) for key, name in _SUB_LANGUAGES]),
            (self._sub_mode, [(t("Save as .srt file"), "file"),
                              (t("Burn into video"), "burn")]),
        ):
            prev = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for label, data in items:
                combo.addItem(label, data)
            combo.setCurrentIndex(max(0, combo.findData(prev)))
            combo.blockSignals(False)
        self._sync_sub_options()

    def _sync_sub_options(self) -> None:
        on = self._sub_cb.isChecked()
        self._sub_lang.setEnabled(on)
        # burning needs a video; MP3-only downloads always save a .srt
        video = self._mp4.isChecked()
        self._sub_mode.setEnabled(on and video)
        if not video:
            self._sub_mode.setCurrentIndex(0)

    def _populate_quality(self) -> None:
        """Fill the Quality combo from the checked format (video vs audio)."""
        video = self._mp4.isChecked()
        prev = self._quality.currentData()
        self._quality.blockSignals(True)
        self._quality.clear()
        if video:
            self._quality.addItem(self._t("Best available"), None)
            for label, token in (
                ("4K (2160p)", "2160p"),
                ("1440p (QHD)", "1440p"),
                ("1080p (FHD)", "1080p"),
                ("720p (HD)", "720p"),
                ("480p (SD)", "480p"),
                ("360p", "360p"),
            ):
                self._quality.addItem(label, token)
        else:
            for bitrate in ("320", "256", "192", "128"):
                self._quality.addItem(f"{bitrate} kbps", bitrate)
        idx = self._quality.findData(prev)
        self._quality.setCurrentIndex(idx if idx >= 0 else (2 if not video else 0))
        self._quality.blockSignals(False)

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not files:
            return
        if self._stack.currentIndex() == PAGE_TOOLS:  # a file dropped on Tools is that tool's file
            self._tools.set_file(files[0])
            return
        self._sidebar.select(PAGE_STUDIO)
        self._studio.add_clips(files)
