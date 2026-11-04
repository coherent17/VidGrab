"""The Studio page: toolbar, preview, inspector and timeline wired together (the code is in ui/studio/)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCursor,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab.media.studio import (
    SUBTITLE_FONT_NAME,
    ImageOverlay,
    SubtitleCue,
    SubtitleStyle,
    canvas_size,
    transition_overlaps,
)
from vidgrab.ui.preview import (
    Segment,
    StudioPreview,
    TransitionMark,
    fmt_time,
)
from vidgrab.ui.studio.clips import _MediaClip, _Song
from vidgrab.ui.studio.common import (
    _HAND,
    AUTOSAVE_MS,
    FRAME,
    SHORTCUTS,
    TRANSITION_LABELS,
    _arrow_icon,
)
from vidgrab.ui.studio.editing import EditingMixin
from vidgrab.ui.studio.history import HistoryMixin
from vidgrab.ui.studio.images import ImagesMixin
from vidgrab.ui.studio.inspector_clip import ClipInspectorMixin
from vidgrab.ui.studio.inspector_cue import CueInspectorMixin
from vidgrab.ui.studio.inspector_project import ProjectInspectorMixin
from vidgrab.ui.studio.music import MusicMixin
from vidgrab.ui.studio.render import RenderMixin
from vidgrab.ui.studio.tasks import ThumbCache
from vidgrab.ui.studio.timeline import TrackTimeline
from vidgrab.ui.ui_kit import FlowLayout


class StudioPage(ProjectInspectorMixin, CueInspectorMixin, ClipInspectorMixin, MusicMixin, ImagesMixin, EditingMixin, HistoryMixin, RenderMixin, QWidget):
    """Editor workspace. Talks to the main window through *host*:
    ``host.t``, ``host.icon``, ``host.log``, ``host.pick_*``, ``host.ffmpeg_ok``,
    ``host.default_output_dir``."""

    render_requested = Signal(str, dict)  # worker task name, kwargs
    cancel_requested = Signal()  # stop the running job (auto captions)

    INSP_PROJECT, INSP_CUE, INSP_MUSIC, INSP_CLIP, INSP_IMAGE = range(5)

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self._clips: list[_MediaClip] = []
        self._cues: list[SubtitleCue] = []
        self._songs: list[_Song] = []  # background music, in timeline order of adding
        self._images: list[ImageOverlay] = []  # pictures over the video
        # multi-select: everything picked together with the main selection
        # (empty when only one thing is selected); Ctrl+C keeps copies here
        self._picked: set[tuple[str, int]] = set()
        self._keep_picked = False
        self._clipboard: dict | None = None
        self._sel: tuple[str, int] | None = None
        self._export = "auto"  # key of EXPORT_PRESETS
        self._busy = False
        self._busy_job = "render"  # or "captions"
        self._i18n: list[tuple[object, str, str]] = []
        # probed media by path, so undo / redo / open never re-probe a file
        self._media: dict[str, _MediaClip] = {}
        self._music_media: dict[str, tuple[dict, list[float]]] = {}
        self._history: list[dict] = []
        self._hist_pos = -1
        self._last_edit = ("", 0.0)  # (kind, time) of the last recorded edit
        self._restoring = False
        self._project_path = ""
        self._saved_state: dict | None = None
        # a recovery copy of unsaved work, written now and then (see autosave())
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()
        self._build()
        self._wire_shortcuts()
        self._on_mode()  # show the controls for the starting mode
        self._reset_history()

    # helpers -------------------------------------------------------------

    def t(self, key: str, **kw) -> str:
        return self.host.t(key, **kw)

    def _tr(self, widget, key: str, method: str = "setText"):
        self._i18n.append((widget, key, method))
        getattr(widget, method)(self.t(key))
        return widget

    def _btn(self, key: str, slot, tip: str | None = None, obj: str = "secondary") -> QPushButton:
        b = QPushButton()
        b.setObjectName(obj)
        b.setCursor(QCursor(_HAND))
        b.clicked.connect(slot)
        self._tr(b, key)
        if tip:
            self._tr(b, tip, "setToolTip")
        return b

    def _label(self, key: str, obj: str | None = None) -> QLabel:
        lbl = QLabel()
        if obj:
            lbl.setObjectName(obj)
        lbl.setWordWrap(obj == "hint")
        return self._tr(lbl, key)

    @staticmethod
    def _panel() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("panel")
        w.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        return w, lay

    def is_video(self) -> bool:
        return self.mode_video.isChecked()

    # construction --------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(self._build_toolbar())
        top = QSplitter(Qt.Horizontal)
        top.setChildrenCollapsible(False)
        top.setHandleWidth(8)
        viewer, vl = self._panel()
        self.preview = StudioPreview()
        self.preview.cue_moved.connect(self._on_cue_moved)
        self.preview.cue_clicked.connect(self.select_cue)
        self.preview.pan_dragged.connect(self._on_pan_dragged)
        self.preview.image_clicked.connect(self.select_image)
        self.preview.image_changed.connect(self._on_image_placed)
        self.preview.position_changed.connect(self.track_playhead)
        vl.addWidget(self.preview)
        top.addWidget(viewer)
        top.addWidget(self._build_inspector())
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 0)
        top.setSizes([880, 350])
        root.addWidget(top, stretch=1)
        root.addWidget(self._build_timeline())

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(10)
        seg = QWidget()
        seg.setObjectName("segmented")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(4)
        self.mode_video = QPushButton()
        self.mode_audio = QPushButton()
        for b, key in ((self.mode_video, "Video montage"), (self.mode_audio, "Music medley")):
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.setIconSize(QSize(16, 16))
            self._tr(b, key)
            sl.addWidget(b)
        self.mode_video.setChecked(True)
        self.mode_video.toggled.connect(lambda _c: self._on_mode())
        lay.addWidget(seg)
        self.project_btn = QPushButton()
        self.project_btn.setObjectName("secondary")
        self.project_btn.setCursor(QCursor(_HAND))
        self._tr(self.project_btn, "Project")
        self.project_menu = QMenu(self)
        self.project_menu.aboutToShow.connect(self._fill_project_menu)
        self.project_btn.setMenu(self.project_menu)
        lay.addWidget(self.project_btn)
        self.undo_btn = self._btn("", self.undo, "Undo (Ctrl+Z)")
        self.redo_btn = self._btn("", self.redo, "Redo (Ctrl+Y)")
        for b in (self.undo_btn, self.redo_btn):
            b.setFixedWidth(40)
            b.setIconSize(QSize(18, 18))
            lay.addWidget(b)
        self.project_lbl = QLabel()
        self.project_lbl.setObjectName("status")
        lay.addWidget(self.project_lbl)
        lay.addStretch()
        self.status = QLabel()
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(170)
        lay.addWidget(self.progress)
        self.render_btn = QPushButton()
        self.render_btn.setObjectName("primary")
        self.render_btn.setProperty("compact", True)
        self.render_btn.setFixedHeight(42)
        self.render_btn.setMinimumWidth(170)
        self.render_btn.setCursor(QCursor(_HAND))
        self.render_btn.clicked.connect(self.render)
        self._tr(self.render_btn, "tooltip_action_studio", "setToolTip")
        lay.addWidget(self.render_btn)
        return bar

    def _build_timeline(self) -> QWidget:
        panel, lay = self._panel()
        lay.setContentsMargins(8, 8, 8, 6)
        bar = FlowLayout(spacing=4)  # wraps to a second row in a narrow window
        bar.addWidget(self._btn("＋ Media…", self._add_dialog, "Add video or music files"))
        self.split_btn = self._btn("✂ Split", self.split_clip,
                                   "Split the clip under the playhead in two (S)")
        bar.addWidget(self.split_btn)
        self.add_sub_btn = self._btn("＋ Subtitle", self._add_cue,
                                     "Add a subtitle line at the playhead")
        self.captions_btn = self._btn("Auto captions…", self.auto_captions,
                                      "Turn the speech in the clips into subtitle lines")
        self.image_btn = self._btn("＋ Image…", self._image_menu,
                                   "Add a picture, a sticker, or a blur box over the video from the playhead")
        self.music_btn = self._btn("♪ Music…", self._browse_music, "Add background music")
        self.combine_btn = self._btn("Two videos…", self.combine_videos,
                                     "Play two videos at the same time, for example side by side")
        for b in (self.add_sub_btn, self.captions_btn, self.image_btn, self.music_btn,
                  self.combine_btn):
            bar.addWidget(b)
        for key, slot, tip in (("−", lambda: self.zoom_timeline(1 / 1.5), "Zoom out (Ctrl+−)"),
                               ("+", lambda: self.zoom_timeline(1.5), "Zoom in (Ctrl++)"),
                               ("Fit", self.fit_timeline, "Fit the whole project (Ctrl+0)")):
            b = self._btn(key, slot, tip)
            b.setFixedWidth(34 if key != "Fit" else 44)
            bar.addWidget(b)
        keys = self._btn("?", self.show_shortcuts, "Keyboard shortcuts")
        keys.setFixedWidth(34)
        bar.addWidget(keys)
        for key, slot, tip in (("▲", lambda: self._move_clip(-1), "Move up"),
                               ("▼", lambda: self._move_clip(1), "Move down"),
                               ("✕", self._delete_selected, "Delete selected (Del)")):
            b = self._btn(key, slot, tip)
            b.setFixedWidth(34)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.track = TrackTimeline()
        self.thumbs = ThumbCache(self)
        self.track.set_thumb_cache(self.thumbs)
        self.track.seek_requested.connect(self._on_track_seek)
        self.track.clip_selected.connect(self.select_clip)
        self.track.clip_trimming.connect(self._on_clip_trimming)
        self.track.clip_trimmed.connect(self._on_clip_trimmed)
        self.track.clip_moved.connect(self._on_clip_moved)
        self.track.clip_mute_toggled.connect(self.toggle_mute)
        self.track.cue_selected.connect(self.select_cue)
        self.track.cue_changed.connect(self._on_cue_dragged)
        self.track.cue_add_requested.connect(self._add_cue_at)
        self.track.image_selected.connect(self.select_image)
        self.track.image_timing.connect(self._on_image_timing)
        self.track.image_add_requested.connect(lambda t: self._browse_images(at=t))
        self.track.music_selected.connect(self.select_music)
        self.track.music_changed.connect(self._on_music_dragged)
        self.track.item_toggled.connect(self._on_item_toggled)
        self.track.box_selected.connect(self._on_box_selected)
        self.track.group_moved.connect(self._on_group_moved)
        self.track.item_clicked.connect(self._on_item_clicked)
        self.track.add_media_requested.connect(self._add_dialog)
        self.track.music_requested.connect(self._browse_music)
        self.track.view_changed.connect(self._sync_hscroll)
        self.track_scroll = QScrollArea()
        self.track_scroll.setObjectName("page_scroll")
        self.track_scroll.setWidgetResizable(True)
        self.track_scroll.setFrameShape(QFrame.NoFrame)
        self.track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.track_scroll.setWidget(self.track)
        lay.addWidget(self.track_scroll)
        self.hscroll = QScrollBar(Qt.Horizontal)
        self.hscroll.valueChanged.connect(lambda v: self.track.set_view(v / 1000))
        lay.addWidget(self.hscroll)
        self._fit_timeline()
        self._sync_hscroll()
        return panel

    def _sync_hscroll(self) -> None:
        """Mirror the timeline's zoomed view on the scrollbar (ms units)."""
        tl = self.track
        zoomed = tl.zoom() > 1.0
        self.hscroll.setVisible(zoomed)
        if not zoomed:
            return
        self.hscroll.blockSignals(True)
        self.hscroll.setRange(0, int(max(0.0, tl.content_span() - tl.visible_span()) * 1000))
        self.hscroll.setPageStep(max(1, int(tl.visible_span() * 1000)))
        self.hscroll.setSingleStep(max(1, int(tl.visible_span() * 100)))
        self.hscroll.setValue(int(tl.view_start() * 1000))
        self.hscroll.blockSignals(False)

    def zoom_timeline(self, factor: float) -> None:
        self.track.set_zoom(self.track.zoom() * factor)

    def fit_timeline(self) -> None:
        self.track.set_zoom(1.0)

    def _fit_timeline(self) -> None:
        """Show every row up to ~6 clips; beyond that the rows scroll."""
        self.track_scroll.setFixedHeight(min(self.track.height(), 340) + 2)

    # inspector -----------------------------------------------------------------

    def _build_inspector(self) -> QWidget:
        panel, lay = self._panel()
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(440)
        self.insp_title = QLabel()
        self.insp_title.setObjectName("panel_title")
        self.total_lbl = QLabel()  # "3 clips • 1:20", on the right of the panel title
        self.total_lbl.setObjectName("total_lbl")
        head = QHBoxLayout()
        head.addWidget(self.insp_title)
        head.addStretch()
        head.addWidget(self.total_lbl)
        lay.addLayout(head)
        self.insp = QStackedWidget()
        for build in (self._build_project_inspector, self._build_cue_inspector,
                      self._build_music_inspector, self._build_clip_inspector,
                      self._build_image_inspector):
            self.insp.addWidget(self._scrolled(build()))
        lay.addWidget(self.insp, stretch=1)
        return panel

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        """An inspector page that scrolls up and down when the window is short (so the
        window can be as low as a 768-pixel laptop screen) and looks the same when it fits."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        area.setStyleSheet("QScrollArea { background: transparent; }")
        page.setAutoFillBackground(False)
        area.setWidget(page)
        return area

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        return w, lay























    # picture effects -------------------------------------------------------------------

    FX_LOOKS = (("none", "Original"), ("cinematic", "Cinematic"), ("warm", "Warm"),
                ("cool", "Cool"), ("bw", "Mono"), ("vivid", "Vivid"), ("vintage", "Vintage"))
    # key, label, slider range (hundredths for most), unit shown after the number
    FX_SLIDERS = (
        ("brightness", "Brightness", -50, 50, ""), ("contrast", "Contrast", 50, 180, ""),
        ("saturation", "Colour", 0, 200, ""), ("warmth", "Warmth", -100, 100, ""),
        ("denoise", "Smooth noise", 0, 100, "%"), ("sharpen", "Sharpen", 0, 100, "%"),
        ("key_similarity", "Strength", 2, 50, "%"),
    )




    _fx_busy = False































    # zoom keyframes ---------------------------------------------------------------








    # follow the face --------------------------------------------------------------











    def _wire_shortcuts(self) -> None:
        for keys, slot in (
            (("Space", "K"), self.preview.toggle_play),
            (("J",), lambda: self.step(-1.0)),
            (("L",), lambda: self.step(1.0)),
            (("Left",), lambda: self.step(-FRAME)),
            (("Right",), lambda: self.step(FRAME)),
            (("Home",), lambda: self.preview.seek(0.0)),
            (("End",), lambda: self.preview.seek(self.track.total())),
            (("I",), lambda: self.trim_at_playhead("start")),
            (("O",), lambda: self.trim_at_playhead("end")),
            (("S",), self.split_clip),
            (("M",), self._mute_selected),
            (("Z",), self.zoom_to_clip),
            (("Delete",), self._delete_selected),
            (("Ctrl+C",), self.copy_selection),
            (("Ctrl+D",), self.duplicate_selection),
            (("Ctrl+A",), self.select_all),
            (("Escape",), self.deselect),
            ((QKeySequence.Undo, "Ctrl+Z"), self.undo),
            ((QKeySequence.Redo, "Ctrl+Y", "Ctrl+Shift+Z"), self.redo),
            (("Ctrl+=", "Ctrl++"), lambda: self.zoom_timeline(1.5)),
            (("Ctrl+-",), lambda: self.zoom_timeline(1 / 1.5)),
            (("Ctrl+0",), self.fit_timeline),
            (("Ctrl+N",), self.new_project),
            (("Ctrl+O",), lambda: self.open_project()),
            (("Ctrl+S",), self.save_project),
            (("Ctrl+Shift+S",), self.save_project_as),
        ):
            seen = set()
            for key in keys:
                seq = QKeySequence(key)
                if seq.isEmpty() or seq.toString() in seen:
                    continue
                seen.add(seq.toString())
                sc = QShortcut(seq, self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)

    def show_shortcuts(self) -> None:
        rows = "".join(
            f"<tr><td style='padding:3px 18px 3px 0'><b>{keys}</b></td><td>{self.t(desc)}</td></tr>"
            for keys, desc in SHORTCUTS)
        box = QMessageBox(self)
        box.setWindowTitle(self.t("Keyboard shortcuts"))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<table>{rows}</table>")
        box.exec()

    # theme / language ---------------------------------------------------------

    def apply_theme(self, theme: str, palette: dict[str, str], accents: dict[str, str]) -> None:
        self._theme = (theme, palette, accents)
        self.preview.set_colors(palette)
        self.track.set_colors(
            bg=palette["FIELD"], track=palette["SURFACE"], line=palette["BORDER"],
            text=palette["TEXT"], muted=palette["TEXT_MUTED"], clip=accents["clips"],
            clip2=accents["medley"], audio=accents["output"], cue=accents["subs"],
            music=accents["music"], sel=palette["TEXT"], head="#ff4d6d",
            accent=palette["ACCENT"], hdr_sel=palette["SEL"],
        )
        self.track.set_icons({
            "film": self.host.icon("film", accents["clips"], 16).pixmap(16, 16).toImage(),
            "music": self.host.icon("music", accents["output"], 16).pixmap(16, 16).toImage(),
        })
        self._style_icons()
        self._anchor_icons(palette["TEXT"])
        for sw in (self.sub_color, self.sub_bg, self.own_color, self.own_bg):
            sw.set_accent(palette["ACCENT"])
        self.undo_btn.setIcon(_arrow_icon(palette["TEXT"], redo=False))
        self.redo_btn.setIcon(_arrow_icon(palette["TEXT"], redo=True))

    def _style_icons(self) -> None:
        if not hasattr(self, "_theme"):
            return
        muted = self._theme[1]["TEXT_MUTED"]
        for b, kind in ((self.mode_video, "film"), (self.mode_audio, "music")):
            b.setIcon(self.host.icon(kind, "#ffffff" if b.isChecked() else muted, 16))

    def retranslate(self) -> None:
        t = self.t
        for widget, key, method in self._i18n:
            getattr(widget, method)(t(key))
        self._balance_tabs()
        self.track.set_labels(
            subs=t("Subtitles"), music=t("Music"), images=t("Images"),
            empty_images=t("Double-click to add a picture"),
            empty=t("＋ Drop video or music files here (or double-click)"),
            empty_subs=t("Double-click to add a subtitle"),
            empty_music=t("Double-click to add background music"),
            mute=t("Mute this clip"), unmute=t("Unmute this clip"),
        )
        self.preview.set_texts(
            empty=t("Add clips to start"), audio="♪", guides=t("Guides"),
            guides_tip=t("Show the safe area and centre lines (dragged text and pictures "
                         "always snap to them; hold Alt to place freely)"))
        self._fill(self.res, [
            (t("Same as first clip"), "auto"),
            (t("1080p landscape (16:9)"), "1080p"),
            (t("720p landscape (16:9)"), "720p"),
            (t("480p landscape (16:9)"), "480p"),
            (t("Vertical 1080×1920 (9:16)"), "vertical"),
            (t("Square 1080×1080 (1:1)"), "square"),
        ])
        for sw in (self.sub_color, self.sub_bg, self.own_color, self.own_bg):
            sw.retranslate()
        self.refresh_presets()
        self._update_project_ui()
        if not self._busy:
            self.render_btn.setText(t("✦  Render"))
            self.status.setText("")
        self._refresh_all()

    @staticmethod
    def _fill(combo: QComboBox, items: list[tuple[str, str]]) -> None:
        prev = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(combo.findData(prev), 0))
        combo.blockSignals(False)

    # mode -------------------------------------------------------------------------

    def _on_mode(self) -> None:
        video = self.is_video()
        for w in (self.add_sub_btn, self.captions_btn, self.image_btn, self.music_btn,
                  self.combine_btn, self.res_lbl, self.res, self.loud_cb,
                  self.export_cap, self.export_box):
            w.setVisible(video)
        for w in (self.xfade_lbl, self.xfade, self.afmt_lbl, self.afmt, self.abr_lbl, self.abr):
            w.setVisible(not video)
        self.export_hint.setVisible(video and bool(self.export_hint.text()))
        self.track.set_tracks(subs=video, music=video)
        if not video and self._sel and self._sel[0] in ("cue", "music", "image"):
            self.deselect()
        self._style_icons()
        self._refresh_all()
        if self._sel and self._sel[0] == "clip":
            self.select_clip(self._sel[1])  # clip panel only in video mode

    # selection ----------------------------------------------------------------------

    def _show_inspector(self, page: int, title: str) -> None:
        # a plain click elsewhere ends a multi-select; clicking one of the picked
        # items (to drag the group) keeps it
        if not self._keep_picked and self._picked and self._sel not in self._picked:
            self._picked = set()
            self.track.set_picked(self._picked)
        self.insp.setCurrentIndex(page)
        self.insp_title.setText(self.t(title))
        if hasattr(self, "_images"):
            self._push_images()  # the picture's selection box follows the selection

    def deselect(self) -> None:
        self._sel = None
        self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(None)
        self.preview.set_cues(self._preview_cues(), None)
        self.preview.set_pan_segment(None)

    def select_clip(self, i: int) -> None:
        if not 0 <= i < len(self._clips):
            return
        if self._sel != ("clip", i):
            self._sel = ("clip", i)
            # where this clip is on screen (inside a transition: past its middle)
            self.preview.seek(self.track.offsets()[i] + self.track.overlaps()[i] / 2 + 0.01)
        if self.is_video():
            self._fill_clip_inspector()
            self._show_inspector(self.INSP_CLIP, "Clip")
        else:
            self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(self._sel)
        self.preview.set_cues(self._preview_cues(), None)
        self._update_pan_target()

    def select_cue(self, i: int) -> None:
        if not 0 <= i < len(self._cues):
            return
        self._sel = ("cue", i)
        cue = self._cues[i]
        if not cue.start <= self.preview.position() < cue.end:
            self.preview.seek(cue.start + 0.01)
        self.preview.set_cues(self._preview_cues(), i)
        self._fill_cue_inspector()
        self._show_inspector(self.INSP_CUE, "Subtitle")
        self.track.set_selection(self._sel)

    def select_music(self, k: int = 0) -> None:
        if not 0 <= k < len(self._songs):
            return
        self._sel = ("music", k)
        self._fill_music_inspector()
        self._show_inspector(self.INSP_MUSIC, "Background music")
        self.track.set_selection(self._sel)

    def _on_track_seek(self, t: float) -> None:
        if self._sel and self._sel[0] == "music":
            self.deselect()
        self.preview.seek(t)

    def track_playhead(self, t: float) -> None:
        self.track.set_playhead(t)

    # refresh ---------------------------------------------------------------------

    def _segments(self, override: tuple[int, float, float] | None = None) -> list[Segment]:
        """One preview segment per clip. Where a transition overlaps two clips
        the preview switches at its middle, so segment times match the render."""
        spans = [c.span() for c in self._clips]
        if override is not None:
            spans[override[0]] = (override[1], override[2])
        outs = [(e - s) / c.speed for c, (s, e) in zip(self._clips, spans)]
        ov = transition_overlaps(outs, [(c.transition, c.transition_d) for c in self._clips])
        if not self.is_video():
            ov = [0.0] * len(spans)
        ov.append(0.0)
        segs = []
        for i, (c, (s, _e)) in enumerate(zip(self._clips, spans)):
            start = s + ov[i] / 2 * c.speed  # source seconds
            dur = max(0.0, outs[i] - ov[i] / 2 - ov[i + 1] / 2)  # montage seconds
            segs.append(Segment(c.path, start, dur, c.has_video, fit=c.fit, zoom=c.zoom,
                                pan_x=c.pan_x, pan_y=c.pan_y,
                                volume=c.gain() * self._orig_level(), speed=c.speed,
                                fx=c.fx, key_bg=c.fx.get("key_bg", "")))
        return segs

    def _transition_marks(self) -> list[TransitionMark]:
        marks = []
        for i, (off, ov) in enumerate(zip(self.track.offsets(), self.track.overlaps())):
            if ov > 0:
                kind = self._clips[i].transition
                marks.append(TransitionMark(off + ov / 2, ov, kind,
                                            self.t(TRANSITION_LABELS.get(kind, kind)), i))
        return marks

    def _reload_preview(self, position: float | None = None) -> None:
        segs = self._segments()
        if segs:
            self.preview.load_timeline(segs, position)
        else:
            self.preview.clear()
        self.preview.set_transitions(self._transition_marks() if self.is_video() else [])
        self._update_pan_target()
        self._push_music()
        self._push_images()
        sel = self._sel[1] if self._sel and self._sel[0] == "cue" else None
        self.preview.set_cues(self._preview_cues(), sel)

    def _refresh_all(self) -> None:
        self._refresh_track()
        self._refresh_aspect()
        self._push_style()
        if self._sel is None:
            self._show_inspector(self.INSP_PROJECT, "Project")
        self._reload_preview()
        self.name.setPlaceholderText("vidgrab-montage" if self.is_video() else "vidgrab-medley")

    def _refresh_track(self) -> None:
        music = None
        if self._songs:
            last = len(self._songs) - 1
            music = [{"name": Path(song.path).name, "dur": song.length, "wave": song.wave,
                      "loop": k == last and self.music_loop.isChecked(),
                      "start": song.span()[0], "end": song.span()[1],
                      "offset": song.offset, "fade": song.fade}
                     for k, song in enumerate(self._songs)]
        self.track.set_data(
            list(self._clips),
            [(c.start, c.end, c.text) for c in self._cues] if self.is_video() else [],
            music if self.is_video() else None,
            [(img.start, img.end, self._image_label(img),
              self._image_thumb(img.path) if img.is_picture() else None)
             for img in self._images] if self.is_video() else [],
        )
        self._fit_timeline()
        total = self.track.total()  # transitions overlap, so not the plain sum
        self._sync_export()
        self.total_lbl.setText(
            self.t("{n} clips · {dur}", n=len(self._clips), dur=fmt_time(total)))

    def _refresh_aspect(self) -> None:
        first = next((c for c in self._clips if c.has_video), None)
        w, h = canvas_size(
            self.res.currentData() or "auto",
            first.info.get("width", 0) if first else 1280,
            first.info.get("height", 0) if first else 720,
        )
        self.preview.set_aspect(w, h)

    def _push_style(self) -> None:
        self.preview.set_style(self._style())
        if self._sel and self._sel[0] == "cue":
            self._fill_cue_inspector()
        self._record("style")

    def _sub_position(self) -> str:
        return next((v for v, b in self.sub_pos_btns.items() if b.isChecked()), "bottom")

    def _style(self) -> SubtitleStyle:
        bg = self.sub_bg.color() or None
        self.sub_bg_opacity.setEnabled(bg is not None)
        return SubtitleStyle(size=self.sub_size.value(),
                             color=self.sub_color.color() or "#FFFFFF",
                             position=self._sub_position(),
                             background=bg,
                             bg_opacity=self.sub_bg_opacity.value() / 100,
                             font=self.sub_font.currentData() or SUBTITLE_FONT_NAME,
                             bold=self.sub_bold.isChecked(),
                             fade=self.sub_fade.value())

    def _preview_cues(self) -> list[tuple[int, SubtitleCue]]:
        if not self.is_video():
            return []
        return [(i, c) for i, c in enumerate(self._cues) if c.text.strip()]

    def _project_changed(self) -> None:
        self._refresh_track()
        self._refresh_aspect()
        self._reload_preview()

    def _cues_changed(self) -> None:
        sel_cue = self._cues[self._sel[1]] if self._sel and self._sel[0] == "cue" else None
        picked = [self._cues[i] for k, i in self._picked if k == "cue" and i < len(self._cues)]
        self._cues.sort(key=lambda c: c.start)
        if sel_cue is not None:
            self._sel = ("cue", self._cues.index(sel_cue))
            self.track.set_selection(self._sel)
        if picked:  # the selection follows the lines, not their old positions
            ids = {id(c) for c in picked}
            self._picked = {(k, i) for k, i in self._picked if k != "cue"} | {
                ("cue", i) for i, c in enumerate(self._cues) if id(c) in ids}
            self.track.set_picked(self._picked)
        self._refresh_track()
        sel = self._sel[1] if self._sel and self._sel[0] == "cue" else None
        self.preview.set_cues(self._preview_cues(), sel)

    # media ------------------------------------------------------------------------






    # multi-select, copy / paste -------------------------------------------------













    # trimming -----------------------------------------------------------------------




    # subtitles -------------------------------------------------------------------------













    # subtitle style presets (stored in the app settings) -------------------------












    # subtitle files ------------------------------------------------------------------




    # music ---------------------------------------------------------------------------
























    # images over the video --------------------------------------------------------






























    # playhead editing ------------------------------------------------------------













    # undo / redo ---------------------------------------------------------------------









    # projects ------------------------------------------------------------------------








    # recovery ------------------------------------------------------------------------












    # output ---------------------------------------------------------------------------

    def _browse_out(self) -> None:
        folder = self.host.pick_dir(self.t("Save to:"), self.out_dir.text())
        if folder:
            self.out_dir.setText(folder)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        captions = busy and self._busy_job == "captions"
        # while captions are made the Render button stops them
        self.render_btn.setEnabled(not busy or captions)
        self.captions_btn.setEnabled(not busy)
        self.combine_btn.setEnabled(not busy)
        if busy:
            self.preview.stop()
            self.progress.setMaximum(0)
            self.render_btn.setText(self.t("✕  Stop") if captions else self.t("✦  Rendering…"))
        else:
            self._busy_job = "render"
            self.progress.setMaximum(100)
            self.render_btn.setText(self.t("✦  Render"))
            self._reload_preview()

    def show_progress(self, msg: str, pct: float | None) -> None:
        if pct is None:
            self.progress.setMaximum(0)
            self.status.setText(msg)
        else:
            self.progress.setMaximum(100)
            self.progress.setValue(int(pct))
            self.status.setText(f"{msg} {int(pct)}%")

    def shutdown(self) -> None:
        """Stop background frame extraction (before the window closes)."""
        self.thumbs.shutdown()
        self._follow_cancel.set()
        self._best_pool.clear()
        self._best_pool.waitForDone(3000)
        self._beat_pool.clear()
        self._beat_pool.waitForDone(3000)
        self._follow_pool.clear()
        self._follow_pool.waitForDone(3000)
        self.fx_pool.clear()
        self.fx_pool.waitForDone(3000)

    def finish(self, ok: bool) -> None:
        self.progress.setMaximum(100)
        self.progress.setValue(100 if ok else 0)
        self.status.setText(self.t("Done") if ok else self.t("Failed"))

    # auto captions ---------------------------------------------------------------------




    # two videos at once ------------------------------------------------------------
