"""The Settings page."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QFont,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab.ai.captions import (
    speech_device,
)
from vidgrab.core.downloader import (
    BROWSERS,
    configure_cookies,
    configure_network,
    default_output_dir,
    find_ffmpeg,
)
from vidgrab.i18n import LANGUAGES
from vidgrab.ui.config import DEFAULT_SETTINGS, _config_dir, _load_config, _models_dir
from vidgrab.ui.dialogs import _get_existing_directory, _get_save_file_name
from vidgrab.ui.downloads_panel import (
    DONE,
    human_size,
)
from vidgrab.ui.drawing import _HAND, _flag_icon
from vidgrab.ui.fonts import UI_FONTS
from vidgrab.ui.helpers import _dir_size
from vidgrab.ui.studio_page import StudioPage
from vidgrab.ui.widgets import _SUB_LANGUAGES, _wrap_scroll
from vidgrab.ui.workers import _HwProbe


class SettingsMixin:
    """The Settings page."""

    def _build_settings_form(self) -> QWidget:
        """Three tabs, so nothing needs scrolling: General (look, storage, about),
        Downloads (defaults, network, yt-dlp) and Studio (render, hardware)."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 12, 24, 8)
        outer.setSpacing(10)
        seg = QWidget()
        seg.setObjectName("segmented")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(4)
        self._set_stack = QStackedWidget()
        self._set_tabs: list[QPushButton] = []

        def column_page() -> tuple[QWidget, QVBoxLayout, QVBoxLayout]:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 2, 0, 0)
            h.setSpacing(14)
            a, b = QVBoxLayout(), QVBoxLayout()
            a.setSpacing(12)
            b.setSpacing(12)
            h.addLayout(a, stretch=1)
            h.addLayout(b, stretch=1)
            return w, a, b

        gen, gen_l, gen_r = column_page()
        dl_page, dl_l, dl_r = column_page()
        st_page, st_l, st_r = column_page()
        for k, (label, tab) in enumerate((("General", gen), ("Downloads", dl_page),
                                          ("Studio", st_page))):
            b = QPushButton()
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setMinimumWidth(110)
            b.setCursor(QCursor(_HAND))
            self._trw(b, label)
            b.clicked.connect(lambda _c=False, i=k: self._set_stack.setCurrentIndex(i))
            sl.addWidget(b)
            self._set_tabs.append(b)
            self._set_stack.addWidget(_wrap_scroll(tab))
        self._set_tabs[0].setChecked(True)
        sl.addStretch()
        outer.addWidget(seg, alignment=Qt.AlignLeft)
        outer.addWidget(self._set_stack, stretch=1)

        # appearance ----------------------------------------------------------
        g1, a_title, fl = self._card("APPEARANCE", "settings_card", "settings")
        self._settings_title = a_title
        afl = QFormLayout()
        afl.setSpacing(8)
        self._theme_combo = QComboBox()
        self._theme_combo.setCursor(QCursor(_HAND))
        self._theme_combo.activated.connect(
            lambda _i: self._set_theme(self._theme_combo.currentData() or "dark")
        )
        self._lang_combo = QComboBox()
        self._lang_combo.setCursor(QCursor(_HAND))
        for code, name in LANGUAGES.items():
            label = name.split(" ", 1)[1] if " " in name else name
            self._lang_combo.addItem(_flag_icon(code), label, code)
        idx = self._lang_combo.findData(self._lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_change)
        self._theme_lbl = QLabel("Theme:")
        self._lang_lbl = QLabel("Language:")
        self._font_lbl = QLabel("Font:")
        self._font_combo = QComboBox()
        self._font_combo.setCursor(QCursor(_HAND))
        self._font_combo.activated.connect(lambda _i: self._on_font_change())
        afl.addRow(self._theme_lbl, self._theme_combo)
        afl.addRow(self._lang_lbl, self._lang_combo)
        afl.addRow(self._font_lbl, self._font_combo)
        fl.addLayout(afl)
        gen_l.addWidget(g1)

        # download defaults ---------------------------------------------------
        g2, t2, dl = self._card("DOWNLOAD DEFAULTS", "settings_card", "format")
        self._trw(t2, "DOWNLOAD DEFAULTS")
        form = QFormLayout()
        form.setSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._set_out = QLineEdit(self.setting("out_dir") or str(default_output_dir()))
        self._set_out.editingFinished.connect(
            lambda: self._set_default_dir(self._set_out.text().strip()))
        browse = QPushButton()
        browse.setObjectName("secondary")
        browse.setCursor(QCursor(_HAND))
        browse.clicked.connect(self._browse_default_dir)
        self._trw(browse, "Browse…")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._set_out, stretch=1)
        row.addWidget(browse)
        form.addRow(self._trw(QLabel(), "Save to:"), row)
        self._set_fmt = QComboBox()
        self._set_vq = QComboBox()
        self._set_aq = QComboBox()
        self._set_afmt = QComboBox()
        self._set_sub_lang = QComboBox()
        self._set_sub_mode = QComboBox()
        self._set_name = QComboBox()
        self._set_sub_lang.setMinimumWidth(170)
        for combo in (self._set_fmt, self._set_vq, self._set_aq, self._set_afmt,
                      self._set_sub_lang, self._set_sub_mode, self._set_name):
            combo.setCursor(QCursor(_HAND))
        self._set_fmt.activated.connect(lambda _i: self._default_changed("fmt", self._set_fmt))
        self._set_vq.activated.connect(
            lambda _i: self._default_changed("video_quality", self._set_vq))
        self._set_aq.activated.connect(
            lambda _i: self._default_changed("audio_quality", self._set_aq))
        self._set_afmt.activated.connect(
            lambda _i: self._default_changed("audio_format", self._set_afmt))
        self._set_sub_lang.activated.connect(
            lambda _i: self._default_changed("sub_lang", self._set_sub_lang))
        self._set_sub_mode.activated.connect(
            lambda _i: self._default_changed("sub_mode", self._set_sub_mode))
        self._set_name.activated.connect(
            lambda _i: self._default_changed("name_template", self._set_name))
        form.addRow(self._trw(QLabel(), "Format:"), self._set_fmt)
        form.addRow(self._trw(QLabel(), "Video quality:"), self._set_vq)
        form.addRow(self._trw(QLabel(), "Audio format:"), self._set_afmt)
        form.addRow(self._trw(QLabel(), "Audio quality:"), self._set_aq)
        self._set_sub = QCheckBox()
        self._set_sub.setCursor(QCursor(_HAND))
        self._set_sub.setChecked(bool(self.setting("sub_enabled")))
        self._set_sub.toggled.connect(lambda on: self._default_changed("sub_enabled", on))
        self._trw(self._set_sub, "Download subtitles")
        sub_row = QVBoxLayout()  # the checkbox, then its two lists (side by side they cut "Traditional Chinese")
        sub_row.setSpacing(8)
        sub_row.addWidget(self._set_sub)
        sub_lists = QHBoxLayout()
        sub_lists.setSpacing(8)
        sub_lists.addWidget(self._set_sub_lang, stretch=1)
        sub_lists.addWidget(self._set_sub_mode, stretch=1)
        sub_row.addLayout(sub_lists)
        form.addRow(self._trw(QLabel(), "Subtitles:"), sub_row)
        form.addRow(self._trw(QLabel(), "File names:"), self._set_name)
        self._set_name_example = QLabel()
        self._set_name_example.setObjectName("hint")
        form.addRow(QLabel(), self._set_name_example)
        self._set_notify = QCheckBox()
        self._set_notify.setCursor(QCursor(_HAND))
        self._set_notify.setChecked(bool(self.setting("notify")))
        self._set_notify.toggled.connect(lambda on: self.set_setting("notify", on))
        self._trw(self._set_notify, "Play a sound and show a message when downloads finish")
        form.addRow(QLabel(), self._set_notify)
        dl.addLayout(form)
        hint = QLabel()
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self._trw(hint, "These are the options the Download page starts with; you can still "
                        "change them there for each download.")
        dl.addWidget(hint)
        dl_l.addWidget(g2)
        dl_l.addStretch()

        # studio ----------------------------------------------------------------
        g3, t3, sl = self._card("STUDIO", "settings_card", "clips")
        self._trw(t3, "STUDIO")
        sform = QFormLayout()
        sform.setSpacing(9)
        sform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._set_rq = QComboBox()
        self._set_res = QComboBox()
        for combo in (self._set_rq, self._set_res):
            combo.setCursor(QCursor(_HAND))
        self._set_rq.activated.connect(
            lambda _i: self._default_changed("render_quality", self._set_rq))
        self._set_res.activated.connect(
            lambda _i: self._default_changed("studio_resolution", self._set_res))
        sform.addRow(self._trw(QLabel(), "Render quality:"), self._set_rq)
        sform.addRow(self._trw(QLabel(), "Default resolution:"), self._set_res)
        sl.addLayout(sform)
        sl.addWidget(self._trw(QLabel(), "Subtitle style presets:"))
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self._set_presets = QListWidget()
        self._set_presets.setObjectName("preset_list")
        self._set_presets.setFixedHeight(86)
        prow.addWidget(self._set_presets, stretch=1)
        delete = QPushButton()
        delete.setObjectName("secondary")
        delete.setCursor(QCursor(_HAND))
        delete.clicked.connect(self._delete_preset_from_settings)
        self._trw(delete, "Delete")
        prow.addWidget(delete, alignment=Qt.AlignTop)
        sl.addLayout(prow)
        phint = QLabel()
        phint.setObjectName("hint")
        phint.setWordWrap(True)
        self._trw(phint, "Save a preset from the subtitle panel in the Studio to reuse fonts, "
                         "colours and position in other projects.")
        sl.addWidget(phint)
        st_l.addWidget(g3)
        st_l.addStretch()

        # hardware --------------------------------------------------------------
        g6, t6, hl = self._card("HARDWARE", "settings_card", "speed")
        self._trw(t6, "HARDWARE")
        self._set_gpu_render = QCheckBox()
        self._set_gpu_captions = QCheckBox()
        self._gpu_render_hint = QLabel()
        self._gpu_captions_hint = QLabel()
        for box, key, label, hint in (
                (self._set_gpu_render, "gpu_render", "Render videos on the graphics card",
                 self._gpu_render_hint),
                (self._set_gpu_captions, "gpu_captions", "Make auto captions on the graphics card",
                 self._gpu_captions_hint)):
            box.setCursor(QCursor(_HAND))
            box.setChecked(bool(self.setting(key)))
            box.toggled.connect(lambda on, k=key: (self.set_setting(k, on),
                                                   self._refresh_hardware()))
            self._trw(box, label)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            hl.addWidget(box)
            hl.addWidget(hint)
        st_r.addWidget(g6)
        st_r.addStretch()

        # storage ---------------------------------------------------------------
        g4, t4, stl = self._card("STORAGE", "settings_card", "save")
        self._trw(t4, "STORAGE")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        self._cache_lbl = QLabel()
        self._history_lbl = QLabel()
        self._log_lbl = QLabel()
        self._models_lbl = QLabel()
        rows = (
            (self._cache_lbl, "Clear", self._clear_cache),
            (self._history_lbl, "Clear", self._clear_history),
            (self._models_lbl, "Delete", self._clear_models),
            (self._log_lbl, "Export…", self._export_log),
        )
        self._models_btn: QPushButton | None = None
        for r, (lbl, key, slot) in enumerate(rows):
            b = QPushButton()
            b.setObjectName("secondary")
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(slot)
            self._trw(b, key)
            if lbl is self._models_lbl:
                self._models_btn = b
            grid.addWidget(lbl, r, 0)
            grid.addWidget(b, r, 1)
        stl.addLayout(grid)
        reset = QPushButton()
        reset.setObjectName("secondary")
        reset.setCursor(QCursor(_HAND))
        reset.clicked.connect(self._reset_settings)
        self._trw(reset, "Reset all settings…")
        stl.addWidget(reset, alignment=Qt.AlignLeft)
        gen_r.addWidget(g4)

        # about -----------------------------------------------------------------
        g5, b_title, al = self._card("ABOUT", "settings_card", "settings")
        self._about_title = b_title
        self._about_lbl = QLabel()
        self._about_lbl.setWordWrap(True)
        self._about_lbl.setTextFormat(Qt.RichText)
        al.addWidget(self._about_lbl)
        self._versions_lbl = QLabel()
        self._versions_lbl.setObjectName("hint")
        self._versions_lbl.setTextFormat(Qt.RichText)
        self._versions_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        al.addWidget(self._versions_lbl)
        gen_l.addWidget(g5)
        gen_l.addStretch()
        gen_r.addStretch()

        # network ---------------------------------------------------------------
        g7, t7, nl = self._card("NETWORK", "settings_card", "speed")
        self._trw(t7, "NETWORK")
        nform = QFormLayout()
        nform.setSpacing(9)
        nform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._set_rate = QComboBox()
        self._set_retries = QComboBox()
        for combo in (self._set_rate, self._set_retries):
            combo.setCursor(QCursor(_HAND))
            combo.activated.connect(lambda _i: self._network_changed())
        self._set_proxy = QLineEdit()
        self._set_proxy.setClearButtonEnabled(True)
        self._set_proxy.setPlaceholderText("http://host:8080  /  socks5://host:1080")
        self._set_proxy.setText(self.setting("proxy") or "")
        self._set_proxy.editingFinished.connect(self._network_changed)
        nform.addRow(self._trw(QLabel(), "Speed limit:"), self._set_rate)
        nform.addRow(self._trw(QLabel(), "Proxy:"), self._set_proxy)
        nform.addRow(self._trw(QLabel(), "Retries:"), self._set_retries)
        self._set_cookies = QComboBox()
        self._set_cookies.setCursor(QCursor(_HAND))
        self._set_cookies.activated.connect(self._cookies_changed)
        self._trw(self._set_cookies, "Lets VidGrab use the login of a browser, for age-restricted "
                                     "or members-only videos. If it fails, close that browser "
                                     "and try again.", "setToolTip")
        nform.addRow(self._trw(QLabel(), "Use login of:"), self._set_cookies)
        nl.addLayout(nform)
        self._set_skip = QCheckBox()
        self._set_skip.setCursor(QCursor(_HAND))
        self._set_skip.setChecked(bool(self.setting("skip_downloaded")))
        self._set_skip.toggled.connect(lambda on: self.set_setting("skip_downloaded", on))
        self._trw(self._set_skip, "Playlists: skip videos I already downloaded")
        nl.addWidget(self._set_skip)
        self._set_suggest = QCheckBox()
        self._set_suggest.setCursor(QCursor(_HAND))
        self._set_suggest.setChecked(bool(self.setting("online_suggest")))
        self._set_suggest.toggled.connect(lambda on: self.set_setting("online_suggest", bool(on)))
        self._trw(self._set_suggest, "Suggest searches while I type (asks YouTube)")
        self._trw(self._set_suggest, "Sends the words you type in the link box to YouTube's suggestion "
                                     "service, as its own search box does. Links are never sent.", "setToolTip")
        nl.addWidget(self._set_suggest)
        self._set_sponsor = QCheckBox()
        self._set_sponsor.setCursor(QCursor(_HAND))
        self._set_sponsor.setChecked(bool(self.setting("sponsorblock")))
        self._set_sponsor.toggled.connect(self._sponsor_changed)
        self._trw(self._set_sponsor, "Cut out sponsor and self-promotion parts (SponsorBlock)")
        self._trw(self._set_sponsor, "Uses the community list at sponsor.ajay.app. "
                                     "Videos nobody has marked are left as they are.", "setToolTip")
        nl.addWidget(self._set_sponsor)
        arow = QHBoxLayout()
        self._archive_lbl = QLabel()
        self._archive_lbl.setObjectName("hint")
        arow.addWidget(self._archive_lbl, stretch=1)
        self._archive_btn = QPushButton()
        self._archive_btn.setObjectName("secondary")
        self._archive_btn.setCursor(QCursor(_HAND))
        self._archive_btn.clicked.connect(self._forget_archive)
        self._trw(self._archive_btn, "Forget the list")
        arow.addWidget(self._archive_btn)
        nl.addLayout(arow)
        dl_r.addWidget(g7)

        # download engine (yt-dlp) -----------------------------------------------
        g8, t8, yl = self._card("DOWNLOAD ENGINE", "settings_card", "source")
        self._trw(t8, "DOWNLOAD ENGINE")
        self._ytdlp_lbl = QLabel()
        yl.addWidget(self._ytdlp_lbl)
        self._ytdlp_status = QLabel()
        self._ytdlp_status.setObjectName("hint")
        self._ytdlp_status.setWordWrap(True)
        yl.addWidget(self._ytdlp_status)
        yrow = QHBoxLayout()
        self._ytdlp_btn = QPushButton()
        self._ytdlp_btn.setObjectName("secondary")
        self._ytdlp_btn.setCursor(QCursor(_HAND))
        self._ytdlp_btn.clicked.connect(self._ytdlp_action)
        self._ytdlp_reset = QPushButton()
        self._ytdlp_reset.setObjectName("secondary")
        self._ytdlp_reset.setCursor(QCursor(_HAND))
        self._ytdlp_reset.clicked.connect(self._ytdlp_use_builtin)
        self._trw(self._ytdlp_reset, "Use the built-in version")
        yrow.addWidget(self._ytdlp_btn)
        yrow.addWidget(self._ytdlp_reset)
        yrow.addStretch()
        yl.addLayout(yrow)
        self._set_ytdlp_auto = QCheckBox()
        self._set_ytdlp_auto.setCursor(QCursor(_HAND))
        self._set_ytdlp_auto.setChecked(bool(self.setting("ytdlp_check")))
        self._set_ytdlp_auto.toggled.connect(lambda on: self.set_setting("ytdlp_check", on))
        self._trw(self._set_ytdlp_auto, "Look for a newer version when VidGrab starts")
        yl.addWidget(self._set_ytdlp_auto)
        self._set_release_auto = QCheckBox()
        self._set_release_auto.setCursor(QCursor(_HAND))
        self._set_release_auto.setChecked(bool(self.setting("update_check")))
        self._set_release_auto.toggled.connect(lambda on: self.set_setting("update_check", on))
        self._trw(self._set_release_auto, "Tell me when a new VidGrab is out")
        yl.addWidget(self._set_release_auto)
        yhint = QLabel()
        yhint.setObjectName("hint")
        yhint.setWordWrap(True)
        self._trw(yhint, "yt-dlp is the part that talks to YouTube and other sites; it needs "
                         "updating when a site changes. A new version is used after a restart.")
        yl.addWidget(yhint)
        self._ytdlp_hint = yhint
        self._ytdlp_pip = QLabel()
        self._ytdlp_pip.setObjectName("hint")
        self._ytdlp_pip.setWordWrap(True)
        self._trw(self._ytdlp_pip, "VidGrab was installed with pip. Update yt-dlp the same way: "
                                   "pip install -U yt-dlp")
        yl.addWidget(self._ytdlp_pip)
        dl_r.addWidget(g8)
        dl_r.addStretch()
        return page

    def _fill_settings_combos(self) -> None:
        t = self._t
        fill = StudioPage._fill
        fill(self._theme_combo, [(t("Dark"), "dark"), (t("Light"), "light")])
        fill(self._font_combo, [*((family, key) for key, family in UI_FONTS.items()),
                                (t("System default"), "system")])
        for i in range(self._font_combo.count()):  # each name in its own typeface
            family = UI_FONTS.get(self._font_combo.itemData(i))
            if family:
                self._font_combo.setItemData(i, QFont(family), Qt.FontRole)
        self._font_combo.setCurrentIndex(max(0, self._font_combo.findData(self.setting("ui_font"))))
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(self._theme)))
        fill(self._set_fmt, [("MP4", "mp4"), ("MP3", "mp3"), ("MP4 + MP3", "both")])
        fill(self._set_vq, [(t("Best available"), "")] + [(label, token) for label, token in (
            ("4K (2160p)", "2160p"), ("1440p (QHD)", "1440p"), ("1080p (FHD)", "1080p"),
            ("720p (HD)", "720p"), ("480p (SD)", "480p"), ("360p", "360p"))])
        fill(self._set_aq, [(f"{b} kbps", b) for b in ("320", "256", "192", "128")])
        fill(self._set_sub_lang, [(t(name), key) for key, name in _SUB_LANGUAGES])
        fill(self._set_afmt, [("MP3", "mp3"), ("M4A (AAC)", "m4a"), ("Opus", "opus"),
                              (t("FLAC (lossless)"), "flac"), (t("WAV (lossless)"), "wav")])
        fill(self._set_rate, [(t("No limit"), 0)] + [
            (label, kb * 1024) for label, kb in (
                ("256 KB/s", 256), ("512 KB/s", 512), ("1 MB/s", 1024), ("2 MB/s", 2048),
                ("5 MB/s", 5120), ("10 MB/s", 10240))])
        fill(self._set_retries, [(t("Fewer (3)"), 3), (t("Normal (10)"), 10),
                                 (t("Persistent (30)"), 30)])
        fill(self._set_sub_mode, [(t("Save as .srt file"), "file"),
                                  (t("Burn into video"), "burn")])
        fill(self._set_cookies, [(t("No browser"), "")] + [
            (b.capitalize(), b) for b in BROWSERS if b != "safari" or sys.platform == "darwin"])
        fill(self._set_name, [(t("Title"), "title"), (t("Title [video ID]"), "title_id"),
                              (t("Channel - Title"), "uploader_title"),
                              (t("Upload date + Title"), "date_title")])
        fill(self._set_rq, [(t("Fast (smaller file)"), "fast"), (t("Balanced"), "balanced"),
                            (t("High quality (larger file)"), "high")])
        fill(self._set_res, [
            (t("Same as first clip"), "auto"), (t("1080p landscape (16:9)"), "1080p"),
            (t("720p landscape (16:9)"), "720p"), (t("480p landscape (16:9)"), "480p"),
            (t("Vertical 1080×1920 (9:16)"), "vertical"),
            (t("Square 1080×1080 (1:1)"), "square")])
        for combo, key in ((self._set_fmt, "fmt"), (self._set_vq, "video_quality"),
                           (self._set_aq, "audio_quality"), (self._set_sub_lang, "sub_lang"),
                           (self._set_sub_mode, "sub_mode"), (self._set_name, "name_template"),
                           (self._set_rq, "render_quality"),
                           (self._set_res, "studio_resolution"),
                           (self._set_afmt, "audio_format"), (self._set_rate, "rate_limit"),
                           (self._set_cookies, "cookies_browser"),
                           (self._set_retries, "retries")):
            want = self.setting(key)
            idx = combo.findData(want if want is not None else "")
            combo.setCurrentIndex(max(idx, 0))
        if self._set_rate.findData(self.setting("rate_limit")) < 0:  # a custom value from the file
            self._set_rate.setCurrentIndex(0)
        self._update_name_example()
        self._refresh_storage()
        self._refresh_presets()
        self._refresh_hardware()

    def _archive_path(self) -> Path:
        return _config_dir() / "downloaded.txt"

    def _apply_network(self) -> None:
        """Hand the Settings to the downloader (speed limit, proxy, retries, archive)."""
        configure_network(rate_limit=int(self.setting("rate_limit") or 0),
                          proxy=self.setting("proxy") or "",
                          retries=int(self.setting("retries") or 10),
                          archive=self._archive_path(),
                          sponsorblock=bool(self.setting("sponsorblock")))
        configure_cookies(self.setting("cookies_browser") or "")

    def _sponsor_changed(self, on: bool) -> None:
        self.set_setting("sponsorblock", bool(on))
        self._apply_network()

    def _cookies_changed(self, _i: int = 0) -> None:
        self.set_setting("cookies_browser", self._set_cookies.currentData() or "")
        configure_cookies(self.setting("cookies_browser") or "")

    def _network_changed(self) -> None:
        self.set_setting("rate_limit", int(self._set_rate.currentData() or 0))
        self.set_setting("retries", int(self._set_retries.currentData() or 10))
        self.set_setting("proxy", self._set_proxy.text().strip())
        self._apply_network()

    def _refresh_archive(self) -> None:
        path = self._archive_path()
        n = 0
        try:
            n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            pass
        self._archive_lbl.setText(self._t("{n} videos remembered", n=n))
        self._archive_btn.setEnabled(n > 0)

    def _forget_archive(self) -> None:
        answer = QMessageBox.question(
            self, self._t("Forget the list"),
            self._t("Forget which videos were downloaded? Playlists will download everything again."))
        if answer == QMessageBox.Yes:
            self._archive_path().unlink(missing_ok=True)
            self._refresh_archive()

    def probe_hardware(self) -> None:
        """Check (in the background) which graphics encoder ffmpeg can use."""
        if self._hw_probe is not None and self._hw_probe.isRunning():
            return
        self._hw_probe = _HwProbe(find_ffmpeg())
        self._hw_probe.found.connect(self._on_hardware)
        self._hw_probe.start()

    def _on_hardware(self, encoder: object) -> None:
        self._hw_encoder = encoder
        self._refresh_hardware()

    def _refresh_hardware(self) -> None:
        """The status lines under the two hardware switches."""
        t, enc = self._t, self._hw_encoder
        if enc is False:
            video = t("Checking this computer…")
        elif enc:
            video = t("Ready: {name}. Faster at Balanced and High quality (little at Fast); "
                      "if it ever fails, VidGrab renders on the CPU instead.", name=enc.label)
        else:
            video = t("No supported graphics encoder found (NVIDIA, Intel or AMD), so videos "
                      "are rendered on the CPU.")
        self._gpu_render_hint.setText(video)
        key, fill = speech_device(bool(self.setting("gpu_captions")), _models_dir())
        self._gpu_captions_hint.setText(t(key, **fill))

    def _update_name_example(self) -> None:
        examples = {
            "title": "Me at the zoo.mp4",
            "title_id": "Me at the zoo [jNQXAC9IVRw].mp4",
            "uploader_title": "jawed - Me at the zoo.mp4",
            "date_title": "2005-04-24 Me at the zoo.mp4",
        }
        key = self.setting("name_template") or "title"
        self._set_name_example.setText(self._t("e.g. {name}", name=examples.get(key, "")))

    def _default_changed(self, key: str, source) -> None:
        value = source if isinstance(source, bool) else (source.currentData() or None)
        if key in ("fmt", "audio_quality", "audio_format", "sub_lang", "sub_mode",
                   "name_template", "render_quality", "studio_resolution") and value is None:
            value = DEFAULT_SETTINGS[key]
        self.set_setting(key, value)
        if key == "name_template":
            self._update_name_example()
        if key == "studio_resolution":
            self._studio.set_default_resolution(value)
        else:
            self._apply_download_defaults()

    def _apply_download_defaults(self) -> None:
        """Start the Download page from the saved defaults."""
        self._out.setText(self.setting("out_dir") or str(default_output_dir()))
        fmt = self.setting("fmt") or "mp4"
        self._mp4.setChecked(fmt in ("mp4", "both"))
        self._mp3.setChecked(fmt in ("mp3", "both"))
        idx = self._audio_fmt.findData(self.setting("audio_format") or "mp3")
        if idx >= 0:
            self._audio_fmt.setCurrentIndex(idx)
        self._populate_quality()
        want = self.setting("video_quality") if self._mp4.isChecked() \
            else self.setting("audio_quality")
        idx = self._quality.findData(want)
        if idx >= 0:
            self._quality.setCurrentIndex(idx)
        self._sub_cb.setChecked(bool(self.setting("sub_enabled")))
        for combo, key in ((self._sub_lang, "sub_lang"), (self._sub_mode, "sub_mode")):
            idx = combo.findData(self.setting(key))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._sync_sub_options()
        self._sync_audio_options()

    def _set_default_dir(self, path: str) -> None:
        self.set_setting("out_dir", path)
        self._out.setText(path or str(default_output_dir()))
        self._studio.out_dir.setText(path or str(default_output_dir()))

    def _browse_default_dir(self) -> None:
        folder = _get_existing_directory(self, self._t("Save to:"), self._set_out.text())
        if folder:
            self._set_out.setText(folder)
            self._set_default_dir(folder)

    def subtitle_presets(self) -> dict:
        return dict(self.setting("subtitle_presets") or {})

    def save_subtitle_preset(self, name: str, style: dict) -> None:
        presets = self.subtitle_presets()
        presets[name] = style
        self.set_setting("subtitle_presets", presets)
        self._refresh_presets()

    def delete_subtitle_preset(self, name: str) -> None:
        presets = self.subtitle_presets()
        presets.pop(name, None)
        self.set_setting("subtitle_presets", presets)
        self._refresh_presets()

    def _refresh_presets(self) -> None:
        self._set_presets.clear()
        names = sorted(self.subtitle_presets())
        for name in names:
            self._set_presets.addItem(name)
        if not names:
            item = QListWidgetItem(self._t("No presets yet"))
            item.setFlags(Qt.NoItemFlags)
            self._set_presets.addItem(item)
        self._studio.refresh_presets()

    def _delete_preset_from_settings(self) -> None:
        item = self._set_presets.currentItem()
        if item is not None and item.text() in self.subtitle_presets():
            self.delete_subtitle_preset(item.text())

    def _refresh_storage(self) -> None:
        cache = _dir_size(_config_dir() / "cache")
        self._cache_lbl.setText(self._t("Thumbnail cache: {size}", size=human_size(cache)))
        done = sum(1 for i in self._queue if i.status == DONE)
        self._history_lbl.setText(self._t("Download history: {n} items", n=done))
        log = _config_dir() / "vidgrab.log"
        size = log.stat().st_size if log.is_file() else 0
        self._log_lbl.setText(self._t("Log file: {size}", size=human_size(size)))
        models = _dir_size(_models_dir())
        self._models_lbl.setText(self._t("Speech models: {size}", size=human_size(models)))
        if self._models_btn is not None:
            self._models_btn.setEnabled(models > 0)

    def _clear_cache(self) -> None:
        shutil.rmtree(_config_dir() / "cache", ignore_errors=True)
        self._refresh_storage()

    def _clear_models(self) -> None:
        size = human_size(_dir_size(_models_dir()))
        answer = QMessageBox.question(
            self, self._t("Delete"),
            self._t("Delete the downloaded speech models ({size})? They are downloaded again "
                    "the next time you use auto captions.", size=size))
        if answer == QMessageBox.Yes:
            shutil.rmtree(_models_dir(), ignore_errors=True)
            self._refresh_storage()

    def _clear_history(self) -> None:
        self._clear_finished()
        self._refresh_storage()

    def _export_log(self) -> None:
        log = _config_dir() / "vidgrab.log"
        if not log.is_file():
            QMessageBox.information(self, self._t("Export…"), self._t("The log is empty."))
            return
        start = str(Path(self._start_dir("Desktop", "Downloads")) / "vidgrab.log")
        path, _ = _get_save_file_name(self, self._t("Export…"), start, "Log (*.log *.txt)")
        if path:
            shutil.copy2(log, path)

    def _reset_settings(self) -> None:
        answer = QMessageBox.question(
            self, self._t("Reset all settings…"),
            self._t("Reset every setting (including subtitle presets) to its default? "
                    "Downloaded files and the download history are kept."),
        )
        if answer != QMessageBox.Yes:
            return
        try:
            (_config_dir() / "config.json").unlink(missing_ok=True)
        except OSError:
            pass
        self._settings = _load_config()
        self._set_out.setText(str(default_output_dir()))
        self._set_sub.setChecked(False)
        self._set_notify.setChecked(True)
        self._fill_settings_combos()
        self._apply_download_defaults()
        self._studio.set_default_resolution("auto")
        self._studio.out_dir.setText(str(default_output_dir()))
        if self._theme != "dark":
            self._set_theme("dark")
        if self._lang != "en":
            self._lang_combo.setCurrentIndex(self._lang_combo.findData("en"))
