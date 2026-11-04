"""VidGrab — professional desktop media tool (PySide6 / Qt)."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QCursor,
    QDesktopServices,
    QFont,
    QIcon,
)

# Names that scripts and the tests read from this module (their code now lives in the modules named here).
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,  # noqa: F401
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__
from vidgrab.core import (
    ffmpeg_fetch,
    opener,
    self_update,
    ytdlp_update,
)
from vidgrab.core.downloader import (
    default_output_dir,
    find_ffmpeg,
    get_app_dir,
)
from vidgrab.core.network import ConnectionStatus
from vidgrab.i18n import make_translator
from vidgrab.ui.chrome import (
    _PAGE_HEADERS,
    PAGE_DOWNLOAD,
    PAGE_HELP,
    PAGE_LIBRARY,
    PAGE_SETTINGS,
    PAGE_STUDIO,
    PAGE_SUBS,
    PAGE_TOOLS,
    _FadeStack,
    _install_wheel_guard,
    _Sidebar,
    _WheelGuard,  # noqa: F401
)
from vidgrab.ui.config import (
    DEFAULT_SETTINGS,
    _config_dir,
    _load_config,
    _models_dir,
    _save_config,
)
from vidgrab.ui.dialogs import (
    _get_existing_directory,
    _get_open_file_name,
    _get_open_file_names,
    _get_save_file_name,
)
from vidgrab.ui.download_page import DownloadPageMixin
from vidgrab.ui.downloads_panel import (
    CANCELLED,
    QUEUED,
    DownloadItem,
    DownloadsPanel,
    LinkRow,
)
from vidgrab.ui.drawing import (
    _HAND,
    _app_icon,
    _asset,  # noqa: F401
    _checkmark_path,
    _chevron_path,
    _icon,
    _qpalette,
)
from vidgrab.ui.fonts import (  # noqa: F401
    _APP_FONT_FAMILIES,
    _BUNDLED_FONTS,
    DEFAULT_UI_FONT,
    UI_FONTS,
    _enable_input_method,
    _font_chain,
    _font_families,
    _register_bundled_fonts,
)
from vidgrab.ui.help_page import HelpPage
from vidgrab.ui.helpers import _chime_path, _versions
from vidgrab.ui.library_page import LibraryPage
from vidgrab.ui.pick_dialogs import shutdown_threads
from vidgrab.ui.preview import QT_MULTIMEDIA_OK as _QT_MULTIMEDIA_OK
from vidgrab.ui.settings_page import SettingsMixin
from vidgrab.ui.studio_page import StudioPage
from vidgrab.ui.subscriptions_page import SubscriptionsPage
from vidgrab.ui.theme import (  # noqa: F401
    _CARD_ACCENTS,
    _PALETTES,
    _THEMES,
    DARK_QSS,
    LIGHT_QSS,
)
from vidgrab.ui.toast import ToastHost
from vidgrab.ui.tools_page import ToolsPage
from vidgrab.ui.updates import UpdatesMixin
from vidgrab.ui.workers import (
    _STUCK,
    _FfmpegThread,
    _HwProbe,
    _stop_thread,
    _Worker,
    _YtdlpThread,
)

# ── palette ────────────────────────────────────────────────────────────────
#
# One stylesheet template, two palettes. Brand: violet #7c5cff -> cyan #22d3ee.









# ── config ─────────────────────────────────────────────────────────────────
























# ── vector icons ────────────────────────────────────────────────────────────





# ── checkmark asset ────────────────────────────────────────────────────────








# ── brand icon ─────────────────────────────────────────────────────────────












# ── file pickers ───────────────────────────────────────────────────────────
#
# Same call shape as QFileDialog's static helpers, but the dialog opens at a
# size where Name / Size / Type / Date columns aren't truncated. (On Windows
# and macOS Qt still shows the native dialog.)













# ── worker thread ──────────────────────────────────────────────────────────




















# ── sidebar ────────────────────────────────────────────────────────────────








# ── page fade animation ────────────────────────────────────────────────────










# ── main window ────────────────────────────────────────────────────────────


class VidGrabWindow(SettingsMixin, UpdatesMixin, DownloadPageMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        _install_wheel_guard()
        cfg = _load_config()
        self._settings = cfg
        self._i18n_widgets: list[tuple[QWidget, str, str]] = []
        self._finished_since_idle = 0
        self._theme = cfg["theme"]
        self._toasts = ToastHost(self, _PALETTES[self._theme])
        self._lang = cfg["lang"]
        self._t = make_translator(self._lang)
        self._busy = False
        self._internet_online: bool | None = None
        self._subs_loaded = False
        self._worker: _Worker | None = None  # Studio render
        self._hw_encoder: object = False  # False = not checked yet, None = none works
        self._hw_probe: _HwProbe | None = None
        self._dl_worker: _Worker | None = None  # current queued download
        self._dl_item: DownloadItem | None = None
        self._queue: list[DownloadItem] = []
        self._probe_cache: dict[str, dict] = {}  # url -> video info
        self._probe_errors: dict[str, str] = {}
        self._link_rows: dict[str, tuple[QListWidgetItem, LinkRow]] = {}
        self._card_titles: list[tuple[QLabel, str]] = []
        self._probe_data: dict | None = None
        self._ytdlp_thread: _YtdlpThread | None = None
        self._ffmpeg_thread: _FfmpegThread | None = None
        # only the packaged app updates yt-dlp itself; a pip install leaves it to pip
        self._can_update_ytdlp = ytdlp_update.can_self_update()
        self._ytdlp_info: dict | None = None  # last check(): current / latest / newer
        self._ytdlp_msg = ""

        self.setWindowTitle("VidGrab")
        self.setMinimumSize(1180, 820)
        self.resize(1500, 1000)
        self.setAcceptDrops(True)

        self._apply_theme()
        self._apply_network()
        self._build_ui()
        self._setup_probe()
        self._load_history()
        self._apply_language()
        self._apply_download_defaults()
        self._refresh_ytdlp()
        self._refresh_archive()
        self._studio.set_default_resolution(self.setting("studio_resolution"))
        self._update_ffmpeg_status()
        self._start_internet_check()
        self._setup_shortcuts()
        if QApplication.platformName() != "offscreen":  # not in tests / scripts
            QTimer.singleShot(600, self._offer_recovery)
            QTimer.singleShot(1200, self.probe_hardware)
            if not find_ffmpeg():  # the macOS app / a pip install: fetch it once
                QTimer.singleShot(900, self._offer_ffmpeg)
            if getattr(sys, "frozen", False):
                self_update.cleanup()  # the version this one replaced, or a half download
            if self.setting("update_check"):
                QTimer.singleShot(6000, self.check_for_release)
            if self.setting("ytdlp_check") and self._can_update_ytdlp:  # one quiet request to pypi.org
                QTimer.singleShot(4000, lambda: self._start_ytdlp("check", quiet=True))

    # ── ui construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        body = QHBoxLayout(central)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = _Sidebar()
        self._sidebar.page_changed.connect(self._switch_page)
        body.addWidget(self._sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_header())

        self._stack = _FadeStack()
        self._stack.addWidget(self._build_download_form())
        self._studio = StudioPage(self)
        self._studio.render_requested.connect(self._start_studio)
        self._studio.cancel_requested.connect(
            lambda: self._worker.cancel() if self._worker is not None else None)
        self._studio.apply_theme(self._theme, _PALETTES[self._theme], _CARD_ACCENTS[self._theme])
        self._stack.addWidget(self._studio)
        self._library = LibraryPage(self)
        self._tools = ToolsPage(self)
        self._subs = SubscriptionsPage(self, _config_dir() / "subscriptions.json")
        for page in (self._library, self._tools, self._subs):
            page.apply_theme(_PALETTES[self._theme])
            self._stack.addWidget(page)
        self._stack.addWidget(self._build_settings_form())
        self._help = HelpPage(lambda k: self._t(k), lambda: self._lang, self._go_page, self._show_about, _icon)
        self._help.apply_theme(_PALETTES[self._theme])
        self._stack.addWidget(self._help)
        content.addWidget(self._stack, stretch=4)
        body.addLayout(content, stretch=1)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._net_lbl = QLabel("\u25cf " + self._t("checking\u2026"))
        self._net_lbl.setFixedHeight(22)
        self._net_lbl.setAlignment(Qt.AlignCenter)
        self._label_pill(self._net_lbl, "#f59e0b")
        self._ffmpeg_lbl = QLabel()
        self._version_lbl = QLabel(f"v{__version__}")
        self._statusbar.addWidget(self._net_lbl)
        self._statusbar.addWidget(self._mk_sep())
        self._statusbar.addWidget(self._ffmpeg_lbl)
        self._statusbar.addPermanentWidget(self._version_lbl)

    @staticmethod
    def _label_pill(label: QLabel, color: str, dark_text: bool = False) -> None:
        label.setStyleSheet(
            f"background-color:{color}; color:{'#0b0f14' if dark_text else '#ffffff'};"
            "border-radius:10px; padding:2px 10px; font-weight:bold; font-size:11px;"
        )

    @staticmethod
    def _mk_sep() -> QLabel:
        s = QLabel("\u2502")
        s.setStyleSheet(
            "color:#2c3a4f; font-size:11px; padding:0 4px; background:transparent;"
        )
        return s

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("header")
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setFixedHeight(64)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(24, 8, 24, 8)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._page_title = QLabel()
        self._page_title.setObjectName("page_title")
        self._page_sub = QLabel()
        self._page_sub.setObjectName("page_sub")
        col.addWidget(self._page_title)
        col.addWidget(self._page_sub)
        lay.addLayout(col)
        lay.addStretch()

        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setFixedHeight(28)
        self._theme_btn.setCursor(QCursor(_HAND))
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)
        return w

    # ── download form ──────────────────────────────────────────────────

    def _card(self, text: str, objname: str, kind: str) -> tuple[QGroupBox, QLabel, QVBoxLayout]:
        """Create a card (QGroupBox) with an accent header label + content layout.

        Returns (groupbox, title_label, content_vbox)."""
        g = QGroupBox()
        g.setObjectName(objname)
        vl = QVBoxLayout(g)
        vl.setContentsMargins(16, 12, 16, 14)
        vl.setSpacing(9)
        head = QHBoxLayout()
        head.setSpacing(8)
        bar = QFrame()
        bar.setObjectName("card_bar")
        t = QLabel(text)
        t.setProperty("card_bar", bar)
        self._style_card_title(t, kind)
        head.addWidget(bar, alignment=Qt.AlignVCenter)
        head.addWidget(t)
        head.addStretch()
        vl.addLayout(head)
        self._card_titles.append((t, kind))
        return g, t, vl

    def _style_card_title(self, label: QLabel, kind: str) -> None:
        accent = _CARD_ACCENTS[self._theme][kind]
        label.setStyleSheet(
            f"color:{accent}; background-color:transparent; font-size:11px; "
            "font-weight:800; letter-spacing:1.5px; margin:0; padding:0;"
        )
        bar = label.property("card_bar")
        if bar is not None:
            bar.setStyleSheet(
                "background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {accent}, stop:1 {_PALETTES[self._theme]['ACCENT2']});"
            )


    # ── settings form ──────────────────────────────────────────────────



    # ── settings helpers ───────────────────────────────────────────────

    def _trw(self, widget, key: str, method: str = "setText"):
        """Register *widget* so _apply_language re-applies t(key) to it."""
        self._i18n_widgets.append((widget, key, method))
        getattr(widget, method)(self._t(key))
        return widget

    def setting(self, key: str):
        return self._settings.get(key, DEFAULT_SETTINGS.get(key))

    def set_setting(self, key: str, value) -> None:
        self._settings[key] = value
        _save_config(self._theme, self._lang, {key: value})


    # ── network, download archive, yt-dlp updates ───────────────────────
































    # subtitle presets -----------------------------------------------------






    # storage ----------------------------------------------------------------







    # downloads-finished notification -------------------------------------------

    def toast(self, text: str, kind: str = "ok", action=None):
        """A message that slides in at the bottom right and goes away by itself."""
        return self._toasts.show(text, kind, action)

    def _notify_downloads_done(self, count: int) -> None:
        if not self.setting("notify"):
            return
        msg = self._t("{n} downloads finished.", n=count)
        self.toast(msg, "ok", (self._t("Open folder"), lambda: self.reveal(str(self.default_output_dir()))))
        self._statusbar.showMessage(msg, 10000)
        QApplication.alert(self)  # flash the taskbar entry
        if _QT_MULTIMEDIA_OK:
            # headless (tests, scripts): never make a sound on the speakers
            chime = _chime_path() if QApplication.platformName() != "offscreen" else None
            if chime is not None:
                from PySide6.QtMultimedia import QSoundEffect

                self._chime = QSoundEffect(self)
                self._chime.setSource(QUrl.fromLocalFile(str(chime)))
                self._chime.setVolume(0.6)
                self._chime.play()
        if QSystemTrayIcon.isSystemTrayAvailable():
            if getattr(self, "_tray", None) is None:
                self._tray = QSystemTrayIcon(_app_icon(), self)
                self._tray.show()
            self._tray.showMessage("VidGrab", msg, _app_icon(), 6000)

    # ── shared bottom (log + progress + button) ────────────────────────

    def _build_bottom(self) -> QWidget:
        """Downloads card: the queue on top, recent downloads below it."""
        g, title, ll = self._card("DOWNLOADS", "downloads_card", "settings")
        self._log_title = title
        tools = QHBoxLayout()
        tools.setSpacing(10)
        tools.addStretch()
        self._queue_lbl = QLabel()
        self._queue_lbl.setObjectName("status")
        tools.addWidget(self._queue_lbl)
        self._clear_done_btn = QPushButton()
        self._clear_done_btn.setObjectName("secondary")
        self._clear_done_btn.setCursor(QCursor(_HAND))
        self._clear_done_btn.clicked.connect(self._clear_finished)
        tools.addWidget(self._clear_done_btn)
        # put the tools on the card's title row
        ll.itemAt(0).layout().addLayout(tools)
        self._downloads = DownloadsPanel(self._t, lambda kind: _icon(kind, "#7b80aa", 28))
        self._downloads.action.connect(self._on_download_action)
        ll.addWidget(self._downloads, stretch=1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return g

    # ── page switching ─────────────────────────────────────────────────



    def _switch_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        # Force a full repaint: on some Wayland/software renderers the
        # previous page's pixels are left in the framebuffer, making pages
        # look like they overlap ("collapsed together").
        self._stack.repaint()
        self._update_page_header()
        # the log / progress / Download panel belongs to the Download page;
        # the Studio has its own toolbar with Render + progress
        self._bottom.setVisible(idx == PAGE_DOWNLOAD)
        if idx == PAGE_DOWNLOAD:
            self._update_action_label()
        if idx == PAGE_LIBRARY:
            self._library.refresh()
        elif idx == PAGE_SUBS and not self._subs_loaded:
            self._subs_loaded = True
            self._subs.refresh_all()
        if idx == PAGE_SETTINGS:  # sizes change while you work (a model was downloaded, a cache grew)
            self._refresh_storage()
            self._refresh_hardware()
            self._refresh_archive()
            self._refresh_ytdlp()
        self._refresh_btn()
        self._sidebar.retranslate(self._t, self._theme)

    def _update_page_header(self) -> None:
        title, sub = _PAGE_HEADERS[self._stack.currentIndex()]
        self._page_title.setText(self._t(title))
        self._page_sub.setText(self._t(sub))

    # ── theme ──────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        check = _checkmark_path()
        qss = _THEMES[self._theme]
        muted = _PALETTES[self._theme]["TEXT_MUTED"]
        qss = qss.replace("@ARROW_DOWN@", _chevron_path(muted, down=True))
        qss = qss.replace("@ARROW_UP@", _chevron_path(muted, down=False))
        font = self.setting("ui_font") if hasattr(self, "_settings") else DEFAULT_UI_FONT
        qss = qss.replace("@FONT_CHAIN@", _font_chain(self._lang, font))
        self.setStyleSheet(qss.replace("@CHECK@", check))
        app = QApplication.instance()
        if app is not None:
            app.setPalette(_qpalette(self._theme))
            base = QFont()
            base.setFamilies(_font_families(self._lang, font))
            app.setFont(base)
        for label, kind in self._card_titles:
            self._style_card_title(label, kind)
        if hasattr(self, "_studio"):
            self._studio.apply_theme(
                self._theme, _PALETTES[self._theme], _CARD_ACCENTS[self._theme]
            )
        if hasattr(self, "_toasts"):
            self._toasts.apply_theme(_PALETTES[self._theme])
        if hasattr(self, "_help"):
            self._help.apply_theme(_PALETTES[self._theme])
            for page in (self._library, self._tools, self._subs):
                page.apply_theme(_PALETTES[self._theme])

    def _toggle_theme(self) -> None:
        self._set_theme("light" if self._theme == "dark" else "dark")

    def _set_theme(self, name: str) -> None:
        if name not in _THEMES:
            return
        self._theme = name
        self._apply_theme()
        self._theme_combo.blockSignals(True)
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(self._theme)))
        self._theme_combo.blockSignals(False)
        self._apply_language()
        _save_config(self._theme, self._lang)

    # ── language ───────────────────────────────────────────────────────

    def _on_font_change(self) -> None:
        self.set_setting("ui_font", self._font_combo.currentData() or DEFAULT_UI_FONT)
        self._apply_theme()

    def _on_lang_change(self) -> None:
        self._lang_combo.hidePopup()
        code = self._lang_combo.currentData()
        if code and code != self._lang:
            self._lang = code
            self._t = make_translator(code)
            try:
                self._apply_language()
                self._apply_theme()
                _save_config(self._theme, self._lang)
            finally:
                # Re-applying the global stylesheet can leave the popup stuck
                # open on some platforms; always force it closed afterwards.
                self._lang_combo.hidePopup()
        self._lang_combo.view().scrollTo(
            self._lang_combo.model().index(self._lang_combo.currentIndex(), 0)
        )

    def _apply_language(self) -> None:
        t = self._t
        self._sidebar.retranslate(t, self._theme)
        self._theme_btn.setText(
            t("\u263e Dark") if self._theme == "light" else t("\u2600 Light")
        )
        self._theme_btn.setToolTip(t("tooltip_switch_theme"))
        self._action.setToolTip(t("tooltip_action_download"))
        self._update_page_header()
        self._studio.retranslate()
        self._help.retranslate()
        for page in (self._library, self._tools, self._subs):
            page.retranslate()
        # download page
        self._dl_source_title.setText(t("SOURCE"))
        self._dl_options_title.setText(t("OPTIONS"))
        self._dl_info_title.setText(t("VIDEO INFO"))
        self._dl_format_title.setText(t("FORMAT"))
        self._dl_flip_title.setText(t("FLIP"))
        self._dl_trim_title.setText(t("TRIM"))
        self._dl_speed_title.setText(t("SPEED"))
        self._dl_save_title.setText(t("SAVE TO"))
        self._url.setPlaceholderText(t("Paste a link, or type to search YouTube\u2026"))
        if self._probe_data is not None:
            self._render_info(self._probe_data)
        else:
            self._info_meta.setText(
                t("Paste a link to see its details\u2026")
            )
        self._hflip.setText(t("Horizontal"))
        self._vflip.setText(t("Vertical"))
        self._mp4.setText(t("MP4 (video)"))
        self._mp3.setText(t("Audio"))
        self._update_exact_btn()
        self._update_action_label()
        self._search_panel.retranslate()
        self._ts_lbl.setText(t("Start:"))
        self._te_lbl.setText(t("End:"))
        self._dl_paste.setText(t("Paste"))
        self._dl_import.setText(t("Import…"))
        self._dl_import.setToolTip(t("Load a text file with one link per line"))
        self._dl_browse.setText(t("Browse\u2026"))
        self._dl_paste.setToolTip(t("tooltip_paste"))
        self._dl_browse.setToolTip(t("tooltip_browse_out"))
        self._quality_lbl.setText(t("Quality:").rstrip(":：").upper())
        self._populate_quality()
        # settings page
        self._settings_title.setText(t("APPEARANCE"))
        self._theme_lbl.setText(t("Theme:"))
        self._lang_lbl.setText(t("Language:"))
        self._font_lbl.setText(t("Font:"))
        self._about_title.setText(t("ABOUT"))
        self._about_lbl.setText(
            t("about_text", ver=__version__)
        )
        for widget, key, method in self._i18n_widgets:
            getattr(widget, method)(t(key))
        self._fill_settings_combos()
        self._versions_lbl.setText(
            "<table cellspacing='4'>" + "".join(
                f"<tr><td>{name}</td><td>&nbsp;&nbsp;<b>{ver}</b></td></tr>"
                for name, ver in _versions()) + "</table>")
        # bottom
        self._log_title.setText(t("DOWNLOADS"))
        self._clear_done_btn.setText(t("Clear finished"))
        self._downloads.set_translator(t)
        for _item, row in self._link_rows.values():
            row._t = t
            row.refresh()
        if self._info_stack.currentIndex() == 1:
            self._multi_lbl.setText(t("{n} links ready to download", n=len(self._link_rows)))
        self._update_queue_summary()
        self._sub_cb.setText(t("Download subtitles"))
        self._dl_subs_title.setText(t("SUBTITLES"))
        self._fill_sub_options()
        self._fill_audio_formats()
        if not self._dl_worker:
            self._update_action_label()
        # status bar
        self._update_ffmpeg_status()
        if self._internet_online is True:
            self._net_lbl.setText(f"\u25cf {t('Online')}")
            self._label_pill(self._net_lbl, "#10b981")
        elif self._internet_online is False:
            self._net_lbl.setText(f"\u25cb {t('Offline')}")
            self._label_pill(self._net_lbl, "#ef4444")
        else:
            self._net_lbl.setText("\u25cf " + t("checking\u2026"))
            self._label_pill(self._net_lbl, "#f59e0b")
        self._refresh_btn()
        self._refresh_archive()  # labels built from a count / version stay English until refreshed
        self._refresh_ytdlp()

    # ── about ──────────────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self._t("about_title"),
            self._t("about_dialog", ver=__version__),
        )

    # ── clipboard / file dialogs ───────────────────────────────────────



    # ── URL auto-detect / info card ───────────────────────────────────────






    # ── several links: one row per link ───────────────────────────────







    # ── audio format / exact format / search ──────────────────────────


















    # ── host interface used by StudioPage ──────────────────────────────

    def t(self, key: str, **kw) -> str:
        return self._t(key, **kw)

    def icon(self, kind: str, color: str, size: int = 18) -> QIcon:
        return _icon(kind, color, size)

    # ── host interface of Library / Tools / Subscriptions ──────────────

    def use_gpu_captions(self) -> bool:
        return bool(self.setting("gpu_captions"))

    def _go_page(self, name: str) -> None:
        """Open a page by name (the Help page's buttons use this)."""
        self._sidebar.select({"download": PAGE_DOWNLOAD, "studio": PAGE_STUDIO, "library": PAGE_LIBRARY,
                              "tools": PAGE_TOOLS, "subscriptions": PAGE_SUBS,
                              "settings": PAGE_SETTINGS}[name])

    def open_path(self, path: str, reveal: bool = False) -> None:
        if not opener.open_path(path, reveal):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent if reveal else path)))
            self._statusbar.showMessage(self._t("Could not open: {path}", path=path), 8000)

    def reveal(self, path: str) -> None:
        self.open_path(path, reveal=True)

    def send_to_studio(self, paths: list[str]) -> None:
        if paths:
            self._studio.add_clips(paths)
            self._sidebar.select(PAGE_STUDIO)

    def open_tool(self, path: str) -> None:
        self._tools.set_file(path)
        self._sidebar.select(PAGE_TOOLS)

    def online(self) -> bool:
        return self._internet_online is not False

    def download_links(self, urls: list[str]) -> None:
        self._url.setText(" ".join(urls))
        self._sidebar.select(PAGE_DOWNLOAD)
        self._start_download()

    def log(self, msg: str) -> None:
        self._append_log(msg)
        self._statusbar.showMessage(msg, 8000)

    def default_output_dir(self) -> Path:
        custom = self.setting("out_dir") if hasattr(self, "_settings") else ""
        return Path(custom) if custom else default_output_dir()

    def pick_files(self, caption: str, prefer: tuple[str, ...], name_filter: str) -> list[str]:
        paths, _ = _get_open_file_names(self, caption, self._start_dir(*prefer), name_filter)
        if paths:
            self._remember_dir(paths[0])
        return paths

    def pick_file(self, caption: str, prefer: tuple[str, ...], name_filter: str) -> str:
        path, _ = _get_open_file_name(self, caption, self._start_dir(*prefer), name_filter)
        if path:
            self._remember_dir(path)
        return path

    def pick_save(self, caption: str, default_name: str, name_filter: str) -> str:
        start = str(Path(self._start_dir("Videos")) / default_name)
        path, _ = _get_save_file_name(self, caption, start, name_filter)
        return path

    def pick_dir(self, caption: str, start: str) -> str:
        return _get_existing_directory(self, caption, start)

    def autosave_path(self) -> Path:
        return _config_dir() / "studio-recovery.vgproj"

    def models_dir(self) -> Path:
        """Where the auto-caption speech models are downloaded to."""
        return _models_dir()

    def _offer_recovery(self) -> None:
        """VidGrab closed with unsaved Studio work last time: offer it back."""
        path = self.autosave_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return
        when = data.get("autosaved_at", "")
        answer = QMessageBox.question(
            self, self._t("Recover unsaved work?"),
            self._t("VidGrab closed before your Studio project was saved. Restore the copy "
                    "from {time}?", time=when),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._sidebar.select(PAGE_STUDIO)
            self._studio.recover(str(path))
        else:
            path.unlink(missing_ok=True)

    def _offer_ffmpeg(self) -> bool:
        """No ffmpeg on this computer (the macOS app and a pip install don't carry
        one): offer to download the pinned build once. True if there is one now."""
        if find_ffmpeg():
            return True
        t = self._t
        if ffmpeg_fetch.platform_key() is None:
            return False
        answer = QMessageBox.question(
            self, t("ffmpeg required"),
            t("VidGrab needs ffmpeg to work with video and audio, and this computer doesn't "
              "have it.\n\nDownload it now? It is a one-time download of a few tens of "
              "megabytes, checked against a known checksum."))
        if answer != QMessageBox.Yes:
            return False
        dlg = QProgressDialog(t("Downloading ffmpeg…"), t("Cancel"), 0, 100, self)
        dlg.setWindowTitle(t("ffmpeg required"))
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        thread = _FfmpegThread()
        result: dict = {}
        thread.progress.connect(lambda pct: (dlg.setMaximum(100 if pct >= 0 else 0),
                                             dlg.setValue(max(pct, 0))))
        thread.done.connect(lambda path: (result.update(path=path), dlg.accept()))
        thread.failed.connect(lambda msg: (result.update(error=msg), dlg.accept()))
        dlg.canceled.connect(thread.requestInterruption)
        self._ffmpeg_thread = thread
        thread.start()
        dlg.exec()
        if not thread.wait(15000) and thread not in _STUCK:
            _STUCK.append(thread)  # never destroy a running QThread
        dlg.close()
        if "error" in result and result["error"] != "cancelled":
            self._append_log(f"ffmpeg download failed: {result['error']}")
            QMessageBox.critical(self, t("ffmpeg required"),
                                 t("Could not get ffmpeg: {err}", err=result["error"]))
        self._update_ffmpeg_status()
        return bool(find_ffmpeg())

    def ffmpeg_ok(self) -> bool:
        if find_ffmpeg() or self._offer_ffmpeg():
            return True
        QMessageBox.critical(
            self, self._t("ffmpeg required"),
            self._t("ffmpeg is required for the Studio. "
                    "Install ffmpeg or place it next to the app."),
        )
        return False

    # ── log ────────────────────────────────────────────────────────────

    def _append_log(self, msg: str) -> None:
        """Technical details go to vidgrab.log (not shown in the UI)."""
        try:
            path = _config_dir() / "vidgrab.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > 1_000_000:
                path.unlink()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass

    # ── ffmpeg status ──────────────────────────────────────────────────

    def _update_ffmpeg_status(self) -> None:
        ff = find_ffmpeg()
        if ff:
            if Path(ff).is_relative_to(get_app_dir()):
                self._ffmpeg_lbl.setText(self._t("ffmpeg: embedded"))
            else:
                self._ffmpeg_lbl.setText(self._t("ffmpeg: {name}", name=Path(ff).name))
        else:
            self._ffmpeg_lbl.setText(self._t("ffmpeg: not found"))

    # ── internet ───────────────────────────────────────────────────────

    # how often the connection is re-checked (ms): quickly while offline so
    # the app notices a reconnect, more lazily while online
    _RECHECK_OFFLINE_MS = 5_000
    _RECHECK_ONLINE_MS = 30_000

    def _start_internet_check(self) -> None:
        self._pending_status: ConnectionStatus | None = None
        self._probe_thread: threading.Thread | None = None
        # the probe runs on a plain thread; this timer hands its result to the UI
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_internet)
        self._poll.start(200)
        self._recheck = QTimer(self)
        self._recheck.setSingleShot(True)
        self._recheck.timeout.connect(self._do_probe)
        self._do_probe()





    # ── busy / button state ────────────────────────────────────────────



    # ── start action ───────────────────────────────────────────────────





    # ── download queue ────────────────────────────────────────────────
















    # ── drag & drop ────────────────────────────────────────────────────



    def _run(self, task: str, **kwargs) -> None:
        """Studio render on its own worker (downloads use the queue)."""
        self._worker = _Worker(task, translate=self._t, **kwargs)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._append_log)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    # ── callbacks ──────────────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: object) -> None:
        self._studio.show_progress(msg, pct if isinstance(pct, (int, float)) else None)

    def _on_result(self, result: object) -> None:
        if self._worker is not None and self._worker._task == "transcribe":
            replace_lines = bool(self._worker._kw.get("replace"))
            self._set_busy(False)
            self._studio.finish(True)
            self._studio.captions_ready(list(result), replace_lines)
            return
        if self._worker is not None and self._worker._task == "combine":
            self._set_busy(False)
            self._studio.finish(True)
            self._studio.combined_ready(str(result))
            return
        self._set_busy(False)
        files = list(result) if isinstance(result, (tuple, list)) else [str(result)]
        self._studio.finish(True)
        first = str(files[0]) if files else ""
        text = (self._t("Saved: {name}", name=Path(first).name) if len(files) == 1
                else self._t("Saved {n} files", n=len(files)))
        self.toast(text, "ok", (self._t("Show in folder"), lambda: self.reveal(first)) if first else None)
        self._append_log("Saved: " + ", ".join(str(f) for f in files))

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self._studio.finish(False)
        self._studio.status.setText(self._t("Stopped"))

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._studio.finish(False)
        self._append_log(f"Error: {msg}")
        QMessageBox.critical(self, self._t("Something went wrong"), msg)

    # ── shortcuts ──────────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_url)
        QShortcut(QKeySequence("F1"), self, lambda: self._sidebar.select(PAGE_HELP))

    # ── close ──────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        if self.isVisible() and not self._studio.maybe_save():
            event.ignore()
            return
        _save_config(self._theme, self._lang)
        if self._worker is not None and self._worker.isRunning():
            if self._worker._task == "transcribe":  # captions can simply be stopped
                answer = QMessageBox.question(
                    self, self._t("Task in progress"),
                    self._t("Auto captions are still running. Stop them and quit?"))
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
                _stop_thread(self._worker)
            else:
                QMessageBox.information(
                    self,
                    self._t("Task in progress"),
                    self._t(
                        "A download or processing task is still running.\n"
                        "Please wait for it to complete before closing."
                    ),
                )
                event.ignore()
                return
        if self._dl_worker is not None and self._dl_worker.isRunning():
            answer = QMessageBox.question(
                self, self._t("Task in progress"),
                self._t("Downloads are still running. Stop them and quit?"),
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for item in self._queue:
                if item.status == QUEUED:
                    item.status = CANCELLED
            _stop_thread(self._dl_worker)
        if self._hw_probe is not None:
            _stop_thread(self._hw_probe)
        if self._ytdlp_thread is not None:
            _stop_thread(self._ytdlp_thread, 3000)
        if getattr(self, "_install_thread", None) is not None:
            _stop_thread(self._install_thread, 3000)
        if self._ffmpeg_thread is not None:
            _stop_thread(self._ffmpeg_thread, 3000)
        self._search_panel.stop()
        # a search that is still waiting on the network must not be destroyed with the window
        _STUCK.extend(t for t in shutdown_threads(3000) if t not in _STUCK)
        # give any in-flight info fetch a moment to finish before teardown
        self._probe_token += 1
        for worker in list(self._probe_workers):
            _stop_thread(worker, 3000)
        self._studio.preview.stop()
        self._studio.shutdown()
        for page in (self._library, self._tools, self._subs):
            page.shutdown()
        self._studio.clear_autosave()  # a normal close: nothing to recover
        event.accept()


# ── helpers ────────────────────────────────────────────────────────────────
























# ── entry point ────────────────────────────────────────────────────────────

















def main() -> None:
    _enable_input_method()
    app = QApplication(sys.argv)
    app.setApplicationName("VidGrab")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")

    _register_bundled_fonts()

    font = QFont()
    font.setFamilies(_APP_FONT_FAMILIES)
    app.setFont(font)

    window = VidGrabWindow()

    # Hidden build-verification flag: construct the full UI headlessly and
    # report whether QtMultimedia (inline preview) and the auto-caption speech
    # engine are available in a packaged or source build, then exit. Used by CI to catch exclusion mistakes.
    if "--selftest" in sys.argv:
        from vidgrab.ai.captions import engine_ok, openvino_error

        why = openvino_error()
        print(f"VIDGRAB_SELFTEST multimedia={int(_QT_MULTIMEDIA_OK)} "
              f"captions={int(engine_ok())} openvino={int(not why)} "
              f"ytdlp={ytdlp_update.current_version()} ytdlp_update={int(ytdlp_update.in_use())}",
              flush=True)
        if why:
            print(f"VIDGRAB_SELFTEST_ERROR openvino: {why}", flush=True)
        window.close()
        return

    window.show()
    code = app.exec()
    if any(thread.isRunning() for thread in _STUCK):
        # a thread stuck in a driver call: destroying it would abort the process
        os._exit(code)
    sys.exit(code)


if __name__ == "__main__":
    main()
