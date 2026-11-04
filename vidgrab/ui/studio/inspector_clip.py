"""Clip inspector: trim, sound, framing, effects, keyframes, follow."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import (
    QCursor,
    QFontMetricsF,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vidgrab.ai import reframe
from vidgrab.media import effects, fx_preview
from vidgrab.media.studio import (
    SPEED_RANGE,
    TRANSITIONS,
    parse_timecode,
)
from vidgrab.ui.preview import (
    fmt_time,
)
from vidgrab.ui.studio.clips import _fmt_precise, _MediaClip
from vidgrab.ui.studio.common import _HAND, FRAME, TRANSITION_LABELS
from vidgrab.ui.studio.tasks import (
    _BeatRelay,
    _BestRelay,
    _FollowRelay,
    _FollowTask,
    _FxRelay,
    _FxTask,
)


class ClipInspectorMixin:
    """Clip inspector: trim, sound, framing, effects, keyframes, follow."""

    def _build_clip_inspector(self) -> QWidget:
        """The selected clip: how it comes in (transition) and how it fills
        the output frame (framing)."""
        inner, lay = self._page()
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        back = self._btn("←", self.deselect, "Back to the project settings")
        back.setFixedWidth(36)
        top.addWidget(back)
        self.clip_name = QLabel()
        self.clip_name.setObjectName("info_name")
        self.clip_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.clip_name, stretch=1)
        top.addWidget(self._btn("Zoom to clip", self.zoom_to_clip,
                                "Zoom the timeline to this clip for precise trimming (Z)"))
        lay.addLayout(top)
        outer = lay
        tabs, self.clip_tabs, self.clip_tab_btns = self._tab_bar(
            ("Trim", "Transition", "Sound, frame", "Effects"))
        outer.addWidget(tabs)
        outer.addWidget(self.clip_tabs, stretch=1)
        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))

        # exact in / out points, nudged by a frame or a second
        cap = QHBoxLayout()
        cap.addWidget(self._label("TRIM", "field_cap"))
        cap.addStretch()
        self.clip_info = QLabel()
        self.clip_info.setObjectName("hint")
        cap.addWidget(self.clip_info)
        lay.addLayout(cap)
        trim = QGridLayout()
        trim.setHorizontalSpacing(4)
        trim.setVerticalSpacing(6)
        self.trim_fields: dict[str, QLineEdit] = {}
        for r, (edge, key) in enumerate((("start", "Start:"), ("end", "End:"))):
            trim.addWidget(self._label(key), r, 0)
            field_ = QLineEdit()
            field_.editingFinished.connect(lambda e=edge: self._trim_typed(e))
            self.trim_fields[edge] = field_
            trim.addWidget(field_, r, 1)
            for c, (text, delta, tip) in enumerate((
                ("−1s", -1.0, "Back 1 second"), ("◀", -FRAME, "Back 1 frame"),
                ("▶", FRAME, "Forward 1 frame"), ("+1s", 1.0, "Forward 1 second"),
            )):
                b = self._btn(text, lambda _c=False, e=edge, dl=delta: self._nudge(e, dl), tip)
                b.setFixedWidth(42 if "s" in text else 32)
                b.setStyleSheet("padding: 0;")
                trim.addWidget(b, r, 2 + c)
        trim.setColumnStretch(1, 1)
        lay.addLayout(trim)
        # speed: the common ones as buttons, any value in the box
        lay.addWidget(self._label("SPEED", "field_cap"))
        speeds = QHBoxLayout()
        speeds.setSpacing(8)
        self.clip_speed = QDoubleSpinBox()
        self.clip_speed.setRange(*SPEED_RANGE)
        self.clip_speed.setSingleStep(0.25)
        self.clip_speed.setDecimals(2)
        self.clip_speed.setSuffix("×")
        self.clip_speed.setFixedWidth(92)
        self.clip_speed.valueChanged.connect(self._set_clip_speed)
        self.speed_btns: dict[float, QPushButton] = {}
        named: dict[str, QPushButton] = {}
        box = self._choice_grid([(f"{v:g}", f"{v:g}×") for v in (0.5, 1.0, 1.5, 2.0)], 4,
                                lambda v: self.clip_speed.setValue(float(v)), named)
        self.speed_btns = {float(k): b for k, b in named.items()}
        speeds.addWidget(box, stretch=1)
        speeds.addWidget(self.clip_speed)
        lay.addLayout(speeds)
        lay.addWidget(self._label("CUT", "field_cap"))
        self.silence_btn = self._btn(
            "Remove silences…", self.remove_silences,
            "Cut the quiet pauses out of this clip (it is split into pieces)")
        lay.addWidget(self.silence_btn)
        self.best_btn = self._btn(
            "Best moment…", self._best_menu,
            "Keep only the liveliest part of this clip: the loudest, most active stretch")
        lay.addWidget(self.best_btn)
        lay.addWidget(self._label(
            "Hold Shift while dragging a handle to trim finely; drag it past the edge to "
            "keep going.", "hint"))
        lay.addStretch()

        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))
        lay.addWidget(self._label("TRANSITION IN", "field_cap"))
        self.trans_btns: dict[str, QPushButton] = {}
        self.trans_box = self._choice_grid(
            [(k, TRANSITION_LABELS[k]) for k in TRANSITIONS], 3, self._set_transition,
            self.trans_btns)
        lay.addWidget(self.trans_box)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.trans_len_lbl = self._label("Duration:")
        row.addWidget(self.trans_len_lbl)
        self.trans_len = QDoubleSpinBox()
        self.trans_len.setRange(0.2, 3.0)
        self.trans_len.setSingleStep(0.1)
        self.trans_len.setDecimals(1)
        self.trans_len.setSuffix(" s")
        self.trans_len.valueChanged.connect(self._set_transition_length)
        row.addWidget(self.trans_len, stretch=1)
        self.trans_all = self._btn("Use for all cuts", self._transition_for_all,
                                   "Use this transition between every pair of clips")
        row.addWidget(self.trans_all)
        lay.addLayout(row)
        self.trans_first = self._label(
            "The first clip opens the video, so it has no transition in.", "hint")
        lay.addWidget(self.trans_first)
        lay.addStretch()

        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))
        self.sound_cap = self._label("SOUND", "field_cap")
        lay.addWidget(self.sound_cap)

        self.sound_row = QWidget()
        sr = QHBoxLayout(self.sound_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        self.clip_mute = QCheckBox()
        self.clip_mute.setCursor(QCursor(_HAND))
        self._tr(self.clip_mute, "Mute")
        self.clip_mute.toggled.connect(self._set_muted)
        sr.addWidget(self.clip_mute)
        self.clip_vol = QSlider(Qt.Horizontal)
        self.clip_vol.setObjectName("level_slider")
        self.clip_vol.setRange(0, 200)
        self.clip_vol.setCursor(QCursor(_HAND))
        self.clip_vol_lbl = QLabel("100%")
        self.clip_vol_lbl.setObjectName("level_value")
        self.clip_vol.valueChanged.connect(self._set_clip_volume)
        sr.addWidget(self.clip_vol, stretch=1)
        sr.addWidget(self.clip_vol_lbl)
        lay.addWidget(self.sound_row)
        self.clip_denoise = QCheckBox()
        self.clip_denoise.setCursor(QCursor(_HAND))
        self._tr(self.clip_denoise, "Reduce background noise")
        self._tr(self.clip_denoise, "Takes steady hiss, hum and fan noise out of this clip's sound "
                 "when you render. Speech and music are left alone. The preview does not play it.",
                 "setToolTip")
        self.clip_denoise.toggled.connect(self._set_denoise)
        lay.addWidget(self.clip_denoise)

        self.framing_cap = self._label("FRAMING", "field_cap")
        lay.addWidget(self.framing_cap)
        self.fit_btns: dict[str, QPushButton] = {}
        self.fit_box = self._choice_grid(
            [("fit", "Whole picture"), ("fill", "Fill frame")], 2, self._set_fit, self.fit_btns)
        lay.addWidget(self.fit_box)
        self.zoom_row = QWidget()
        zr = QHBoxLayout(self.zoom_row)
        zr.setContentsMargins(0, 0, 0, 0)
        zr.setSpacing(8)
        zr.addWidget(self._label("Zoom:"))
        self.clip_zoom = QSlider(Qt.Horizontal)
        self.clip_zoom.setObjectName("level_slider")
        self.clip_zoom.setRange(100, 300)
        self.clip_zoom.setCursor(QCursor(_HAND))
        self.clip_zoom_lbl = QLabel("100%")
        self.clip_zoom_lbl.setObjectName("level_value")
        self.clip_zoom.valueChanged.connect(self._set_clip_zoom)
        zr.addWidget(self.clip_zoom, stretch=1)
        zr.addWidget(self.clip_zoom_lbl)
        self.center_btn = self._btn("Center", self._center_clip, "Center the picture again")
        zr.addWidget(self.center_btn)
        lay.addWidget(self.zoom_row)
        self._tr(self.fit_box, "Fill frame crops the picture so there are no black bars. Drag "
                 "the picture in the preview to choose what stays in frame.", "setToolTip")
        self.framing_hint = self._label(
            "Fill frame crops the picture so there are no black bars. Drag the picture "
            "in the preview to choose what stays in frame.", "hint")
        lay.addWidget(self.framing_hint)
        self.follow_cap = self._label("FOLLOW", "field_cap")
        lay.addWidget(self.follow_cap)
        self.follow_btn = self._btn(
            "Follow the face", self._follow_face,
            "Finds the speaker's face and moves the crop with it, for example to turn a "
            "wide video into a tall one")
        lay.addWidget(self.follow_btn)
        self.follow_hint = self._label(
            "Keeps the speaker in frame when the picture is cropped. Works on this computer.",
            "hint")
        lay.addWidget(self.follow_hint)
        self.keys_cap = self._label("ZOOM KEYFRAMES", "field_cap")
        lay.addWidget(self.keys_cap)
        self.keys_list = QListWidget()
        self.keys_list.setMaximumHeight(92)
        self.keys_list.currentRowChanged.connect(lambda _r: self._fill_key_fields())
        lay.addWidget(self.keys_list)
        krow = QHBoxLayout()
        krow.setSpacing(6)
        self.key_add_btn = self._btn("Add keyframe here", self._add_key,
                                     "Zoom in (or out) from the playhead: the picture eases between keyframes")
        self.key_del_btn = self._btn("Remove", self._remove_key, "Remove the selected keyframe")
        krow.addWidget(self.key_add_btn)
        krow.addWidget(self.key_del_btn)
        lay.addLayout(krow)
        self.key_form = QWidget()
        kf = QFormLayout(self.key_form)
        kf.setContentsMargins(0, 0, 0, 0)
        kf.setSpacing(6)
        self.key_time = QDoubleSpinBox()
        self.key_time.setDecimals(2)
        self.key_time.setSuffix(" s")
        self.key_time.setRange(0.0, 99999.0)
        self.key_zoom = QSpinBox()
        self.key_zoom.setRange(100, 400)
        self.key_zoom.setSuffix("%")
        self.key_x = QSpinBox()
        self.key_x.setRange(0, 100)
        self.key_x.setSuffix("%")
        self.key_y = QSpinBox()
        self.key_y.setRange(0, 100)
        self.key_y.setSuffix("%")
        for w in (self.key_time, self.key_zoom, self.key_x, self.key_y):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda _v: self._edit_key())
        kf.addRow(self._label("At (clip time):"), self.key_time)
        kf.addRow(self._label("Zoom:"), self.key_zoom)
        kf.addRow(self._label("Aim left to right:"), self.key_x)
        kf.addRow(self._label("Aim top to bottom:"), self.key_y)
        lay.addWidget(self.key_form)
        self.keys_hint = self._label(
            "Add a keyframe where the move should reach its zoom. Between two keyframes the "
            "picture glides; before the first and after the last it holds still.", "hint")
        lay.addWidget(self.keys_hint)
        self._follow_gen = 0
        self._best_pool = QThreadPool(self)
        self._best_pool.setMaxThreadCount(1)
        self._best_relay = _BestRelay(self)
        self._best_relay.done.connect(self._best_done)
        self._beat_pool = QThreadPool(self)
        self._beat_pool.setMaxThreadCount(1)
        self._beat_relay = _BeatRelay(self)
        self._beat_relay.done.connect(self._beat_done)
        self._follow_pool = QThreadPool(self)
        self._follow_pool.setMaxThreadCount(1)
        self._follow_cancel = threading.Event()
        self._follow_relay = _FollowRelay(self)
        self._follow_relay.done.connect(self._follow_done)
        self._follow_relay.progress.connect(self._follow_progress)
        lay.addStretch()
        self.clip_tabs.addWidget(self._build_effects_page())
        return inner

    def _build_effects_page(self) -> QWidget:
        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.fx_pool = QThreadPool(self)
        self.fx_pool.setMaxThreadCount(1)
        self._fx_relay = _FxRelay(self)
        self._fx_relay.done.connect(self._fx_frames)
        self._fx_gen = 0
        self._fx_timer = QTimer(self)
        self._fx_timer.setSingleShot(True)
        self._fx_timer.setInterval(220)
        self._fx_timer.timeout.connect(self._fx_request)

        # the frame under the playhead, before and after
        shots = QHBoxLayout()
        shots.setSpacing(8)
        self.fx_shots: list[QLabel] = []
        for key in ("Before", "After"):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(self._label(key, "hint"))
            shot = QLabel()
            shot.setObjectName("fx_shot")
            shot.setAlignment(Qt.AlignCenter)
            shot.setFixedHeight(84)
            shot.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            col.addWidget(shot)
            shots.addLayout(col, stretch=1)
            self.fx_shots.append(shot)
        lay.addLayout(shots)
        lay.addWidget(self._label(
            "The player shows colour and green screen; clean-up, stabilising and slow "
            "motion show above and in the render." if fx_preview.available() else
            "Shown above and in the render, not in the player.",
            "hint"))

        lay.addWidget(self._label("LOOK", "field_cap"))
        self.fx_look_btns: dict[str, QPushButton] = {}
        lay.addWidget(self._choice_grid([(k, v) for k, v in self.FX_LOOKS], 4,
                                        self._fx_set_look, self.fx_look_btns))

        head = QHBoxLayout()
        head.addWidget(self._label("ADJUST", "field_cap"))
        head.addStretch()
        head.addWidget(self._btn("Reset", self._fx_reset, "Take every picture effect off this clip"))
        lay.addLayout(head)
        self.fx_sliders: dict[str, QSlider] = {}
        self.fx_rows: dict[str, list[QWidget]] = {}
        for key, label, lo, hi, unit in self.FX_SLIDERS:
            if key == "denoise":
                lay.addWidget(self._label("CLEAN UP", "field_cap"))
            if key == "key_similarity":
                continue  # shown under the green-screen switch
            lay.addLayout(self._fx_slider_row(key, label, lo, hi, unit))

        lay.addWidget(self._label("FIX", "field_cap"))
        self.fx_stab = QCheckBox()
        self.fx_stab.setCursor(QCursor(_HAND))
        self._tr(self.fx_stab, "Steady shaky video")
        self._tr(self.fx_stab, "Smooths out hand-held shake. Adds a pass before the render and "
                 "crops in slightly.", "setToolTip")
        self.fx_stab.toggled.connect(lambda on: self._fx_set("stabilize", on))
        lay.addWidget(self.fx_stab)
        self.fx_smooth = QCheckBox()
        self.fx_smooth.setCursor(QCursor(_HAND))
        self._tr(self.fx_smooth, "Smooth slow motion")
        self._tr(self.fx_smooth, "When this clip plays slower than normal, make up the in-between "
                 "frames instead of repeating them. Slower to render.", "setToolTip")
        self.fx_smooth.toggled.connect(lambda on: self._fx_set("smooth", on))
        lay.addWidget(self.fx_smooth)
        lut = QHBoxLayout()
        lut.setSpacing(6)
        self.fx_lut_btn = self._btn("Colour look file…", self._fx_pick_lut,
                                    "Apply a .cube colour look (LUT), as made by colour-grading apps")
        lut.addWidget(self.fx_lut_btn, stretch=1)
        self.fx_lut_clear = self._btn("Remove", lambda: self._fx_set("lut", ""))
        lut.addWidget(self.fx_lut_clear)
        lay.addLayout(lut)

        lay.addWidget(self._label("REMOVE BACKGROUND", "field_cap"))
        self.fx_cutout = QCheckBox()
        self.fx_cutout.setCursor(QCursor(_HAND))
        self._tr(self.fx_cutout, "Cut out the person (no green sheet needed)")
        self._tr(self.fx_cutout, "Finds the person or main object in every frame and replaces everything "
                 "behind it with the background picture below (black if none). Works best with one "
                 "subject filling a good part of the picture. Done while rendering, so the preview "
                 "does not show it; the Effects pictures do not either.", "setToolTip")
        self.fx_cutout.toggled.connect(lambda on: self._fx_set("cutout", on))
        lay.addWidget(self.fx_cutout)
        lay.addWidget(self._label(
            "Takes a while: about three times the length of the clip on a normal computer. "
            "Needs the speech add-on; a small model downloads once.", "hint"))
        lay.addWidget(self._label("GREEN SCREEN", "field_cap"))
        self.fx_key = QCheckBox()
        self.fx_key.setCursor(QCursor(_HAND))
        self._tr(self.fx_key, "Remove the background colour")
        self._tr(self.fx_key, "Makes one colour see-through, so a person filmed in front of a "
                 "green or blue sheet can stand in front of a picture.", "setToolTip")
        self.fx_key.toggled.connect(self._fx_key_toggled)
        lay.addWidget(self.fx_key)
        self.fx_key_btns: dict[str, QPushButton] = {}
        self.fx_key_box = self._choice_grid([(effects.GREEN, "Green"), ("#0000FF", "Blue")], 2,
                                            lambda v: self._fx_set("key", v), self.fx_key_btns)
        lay.addWidget(self.fx_key_box)
        lay.addLayout(self._fx_slider_row("key_similarity", "Strength", 2, 50, "%"))
        bg = QHBoxLayout()
        bg.setSpacing(6)
        self.fx_bg_btn = self._btn("Background picture…", self._fx_pick_bg,
                                   "The picture shown behind the person (black if none)")
        bg.addWidget(self.fx_bg_btn, stretch=1)
        self.fx_bg_clear = self._btn("Remove", lambda: self._fx_set("key_bg", ""))
        bg.addWidget(self.fx_bg_clear)
        lay.addLayout(bg)
        self.fx_key_widgets = [self.fx_key_box, self.fx_bg_btn, self.fx_bg_clear]
        lay.addStretch()
        return self._scroll(page)

    def _fx_slider_row(self, key: str, label: str, lo: int, hi: int, unit: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        name = self._label(label)
        name.setMinimumWidth(92)
        row.addWidget(name)
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("level_slider")
        slider.setRange(lo, hi)
        slider.setCursor(QCursor(_HAND))
        value = QLabel()
        value.setObjectName("level_value")
        value.setMinimumWidth(40)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v, k=key, lbl=value, u=unit: self._fx_slider(k, v, lbl, u))
        row.addWidget(slider, stretch=1)
        row.addWidget(value)
        slider.setProperty("fx_value", value)
        self.fx_sliders[key] = slider
        return row

    def _fx_slider(self, key: str, v: int, label: QLabel, unit: str) -> None:
        label.setText(f"{v}{unit}" if unit else f"{v:+d}" if key in ("brightness", "warmth") else str(v))
        if self._fx_busy:
            return
        # contrast / colour / strength are stored as fractions, the others too
        self._fx_set(key, v / 100, kind=f"fx_{key}")

    def _fx_set_look(self, look: str) -> None:
        self._fx_set("look", look)

    def _fx_key_toggled(self, on: bool) -> None:
        self._fx_set("key", effects.GREEN if on else "")

    def _fx_set(self, key: str, value, kind: str = "") -> None:
        clip = self._sel_clip()
        if clip is None or self._fx_busy:
            return
        fx = dict(clip.fx)
        fx[key] = value
        if key == "key" and not value and not fx.get("cutout"):
            fx["key_bg"] = ""
        if key == "cutout" and not value and not fx.get("key"):
            fx["key_bg"] = ""
        if key == "cutout" and value:
            fx["key"] = ""  # one way of cutting out at a time
        if key == "key" and value:
            fx["cutout"] = False
        clip.fx = effects.sanitize(fx)
        self._fill_clip_fx()
        self._fx_timer.start()
        self.preview.refresh_effects(self._segments())
        self._record(kind or "fx")

    def _fx_reset(self) -> None:
        clip = self._sel_clip()
        if clip is not None and clip.fx:
            clip.fx = {}
            self._fill_clip_fx()
            self._fx_timer.start()
            self.preview.refresh_effects(self._segments())
            self._record()

    def _fx_pick_lut(self) -> None:
        path = self.host.pick_file(self.t("Colour look file"), ("Documents", "Downloads"),
                                   self.t("Colour look (*.cube)"))
        if path:
            self._fx_set("lut", path)

    def _fx_pick_bg(self) -> None:
        path = self.host.pick_file(self.t("Background picture"), ("Pictures", "Downloads"),
                                   self.t("Pictures (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if path:
            self._fx_set("key_bg", path)

    def _fill_clip_fx(self) -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        fx = {**effects.DEFAULT_FX, **effects.sanitize(clip.fx)}
        self._fx_busy = True
        try:
            for key, slider in self.fx_sliders.items():
                slider.setValue(round(fx[key] * 100))
            self.fx_look_btns[fx["look"]].setChecked(True)
            self.fx_stab.setChecked(fx["stabilize"])
            self.fx_smooth.setChecked(fx["smooth"])
            self.fx_key.setChecked(bool(fx["key"]))
            self.fx_cutout.setChecked(bool(fx["cutout"]))
            for value, b in self.fx_key_btns.items():
                b.setAutoExclusive(False)
                b.setChecked(value == fx["key"])
                b.setAutoExclusive(True)
        finally:
            self._fx_busy = False
        on = bool(fx["key"])
        for w in (self.fx_key_box, self.fx_sliders["key_similarity"]):
            w.setEnabled(on)
        for w in (self.fx_bg_btn, self.fx_bg_clear):  # the picture behind works for both kinds of cut-out
            w.setEnabled(on or bool(fx["cutout"]))
        self.fx_lut_clear.setVisible(bool(fx["lut"]))
        self.fx_lut_btn.setText(Path(fx["lut"]).name if fx["lut"] else self.t("Colour look file…"))
        self.fx_bg_clear.setVisible(bool(fx["key_bg"]))
        self.fx_bg_btn.setText(Path(fx["key_bg"]).name if fx["key_bg"] else self.t("Background picture…"))

    def _fx_request(self) -> None:
        clip = self._sel_clip()
        if clip is None or not clip.has_video:
            return
        hit = self._clip_at(self.preview.position())
        start, end = clip.span()
        at = hit[1] if hit and hit[0] == self._sel[1] else start + (end - start) / 3
        self._fx_gen += 1
        self.fx_pool.start(_FxTask(self._fx_relay, self._fx_gen, clip.path, at, dict(clip.fx)))

    def _fx_frames(self, gen: int, before: bytes, after: bytes) -> None:
        if gen != self._fx_gen:
            return
        for shot, data in zip(self.fx_shots, (before, after)):
            img = QImage.fromData(data) if data else QImage()
            shot.setPixmap(QPixmap.fromImage(img).scaled(
                max(shot.width(), 80), shot.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if not img.isNull() else QPixmap())

    def _sel_clip(self) -> _MediaClip | None:
        if self._sel and self._sel[0] == "clip" and 0 <= self._sel[1] < len(self._clips):
            return self._clips[self._sel[1]]
        return None

    def _fill_clip_inspector(self) -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        i = self._sel[1]
        self.clip_name.setText(QFontMetricsF(self.clip_name.font()).elidedText(
            clip.name, Qt.ElideMiddle, max(80, self.insp.width() - 170)))
        self.clip_name.setToolTip(clip.name)
        self.clip_info.setText(self.t("{used} of {total} used", used=fmt_time(clip.part()),
                                      total=fmt_time(clip.length)))
        for edge, value in zip(("start", "end"), clip.span()):
            if not self.trim_fields[edge].hasFocus():
                self.trim_fields[edge].setText(_fmt_precise(value))
        self.clip_speed.blockSignals(True)
        self.clip_speed.setValue(clip.speed)
        self.clip_speed.blockSignals(False)
        for value, b in self.speed_btns.items():  # none lit for other speeds
            b.setAutoExclusive(False)
            b.setChecked(abs(clip.speed - value) < 1e-6)
            b.setAutoExclusive(True)
        first = i == 0
        for w in (self.trans_box, self.trans_len_lbl, self.trans_len, self.trans_all):
            w.setVisible(not first)
        self.trans_first.setVisible(first)
        self.trans_btns.get(clip.transition, self.trans_btns["none"]).setChecked(True)
        self.trans_len.blockSignals(True)
        self.trans_len.setValue(clip.transition_d)
        self.trans_len.blockSignals(False)
        self.trans_len.setEnabled(clip.transition != "none")
        for w in (self.framing_cap, self.fit_box, self.zoom_row, self.framing_hint, self.keys_cap,
                  self.keys_list, self.key_add_btn, self.key_del_btn, self.keys_hint):
            w.setVisible(clip.has_video)
        self._fill_keys()
        for w in (self.sound_cap, self.sound_row, self.clip_denoise):
            w.setVisible(clip.has_audio)
        for w in (self.clip_mute, self.clip_vol, self.clip_denoise):
            w.blockSignals(True)
        self.clip_denoise.setChecked(clip.denoise)
        self.clip_mute.setChecked(clip.muted)
        self.clip_vol.setValue(round(clip.volume * 100))
        for w in (self.clip_mute, self.clip_vol, self.clip_denoise):
            w.blockSignals(False)
        self.clip_vol.setEnabled(not clip.muted)
        self.clip_denoise.setEnabled(not clip.muted)
        self.clip_vol_lbl.setText(f"{round(clip.volume * 100)}%")
        self.fit_btns[clip.fit].setChecked(True)
        self.follow_btn.setText(self.t("Stop following") if clip.fx.get("follow")
                                else self.t("Follow the face"))
        self.clip_zoom.blockSignals(True)
        self.clip_zoom.setValue(round(clip.zoom * 100))
        self.clip_zoom.blockSignals(False)
        self.clip_zoom_lbl.setText(f"{round(clip.zoom * 100)}%")
        self.clip_tab_btns[3].setVisible(clip.has_video and self.is_video())
        if not self.clip_tab_btns[3].isVisible() and self.clip_tabs.currentIndex() == 3:
            self.clip_tabs.setCurrentIndex(0)
            self.clip_tab_btns[0].setChecked(True)
        self._fill_clip_fx()
        self._fx_timer.start()

    def _transitions_changed(self, kind: str = "") -> None:
        pos = self.preview.position()
        self._refresh_track()
        self._reload_preview(min(pos, self.track.total()))
        self.track.set_selection(self._sel)
        self._fill_clip_inspector()
        self._record(kind)

    def _set_clip_speed(self, value: float) -> None:
        clip = self._sel_clip()
        if clip is None or abs(clip.speed - value) < 1e-6:
            return
        # keep the same moment under the playhead where possible
        hit = self._clip_at(self.preview.position())
        clip.speed = round(min(max(value, SPEED_RANGE[0]), SPEED_RANGE[1]), 2)
        self._transitions_changed("speed")
        if hit is not None and hit[0] == self._sel[1]:
            self.preview.seek(self.track.offsets()[hit[0]]
                              + (hit[1] - clip.span()[0]) / clip.speed)

    def _set_transition(self, kind: str) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.transition = kind
            self._transitions_changed()

    def _set_transition_length(self, value: float) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.transition_d = round(value, 2)
            self._transitions_changed("trans_len")

    def _transition_for_all(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            for other in self._clips[1:]:
                other.transition, other.transition_d = clip.transition, clip.transition_d
            self._transitions_changed()

    def _frame_len(self, clip: _MediaClip) -> float:
        fps = float(clip.info.get("fps") or 0)
        return 1 / fps if fps else FRAME

    def _nudge(self, edge: str, delta: float) -> None:
        """Move the selected clip's start or end by *delta* (±1 frame / ±1 s)."""
        clip = self._sel_clip()
        if clip is None:
            return
        if abs(delta) < 0.5:
            delta = self._frame_len(clip) * (1 if delta > 0 else -1)
        s, e = clip.span()
        self._set_clip_span(edge, s + delta if edge == "start" else s,
                            e + delta if edge == "end" else e, f"nudge_{edge}")

    def _trim_typed(self, edge: str) -> None:
        clip = self._sel_clip()
        value = parse_timecode(self.trim_fields[edge].text())
        if clip is None or value is None:
            self._fill_clip_inspector()
            return
        s, e = clip.span()
        self._set_clip_span(edge, value if edge == "start" else s,
                            value if edge == "end" else e)

    def _set_clip_span(self, edge: str, s: float, e: float, kind: str = "") -> None:
        i = self._sel[1]
        self._on_clip_trimmed(i, s, e, kind)
        # show the frame at the edge that moved
        seg = self._segments()[i]
        offset = sum(x.duration for x in self._segments()[:i])
        self.preview.seek(offset if edge == "start" else offset + max(0.0, seg.duration - 0.02))

    def zoom_to_clip(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            off = self.track.offsets()[self._sel[1]]
            self.track.zoom_to(off, off + clip.kept())

    def _sound_changed(self, i: int, kind: str = "") -> None:
        self.preview.set_segment_volume(i, self._clips[i].gain())
        self.track.update()
        if self._sel == ("clip", i) and self.insp.currentIndex() == self.INSP_CLIP:
            self._fill_clip_inspector()
        self._record(kind)

    def _mute_selected(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            self.toggle_mute(self._sel[1])

    def toggle_mute(self, i: int) -> None:
        if 0 <= i < len(self._clips) and self._clips[i].has_audio:
            self._clips[i].muted = not self._clips[i].muted
            self._sound_changed(i)

    def _set_muted(self, on: bool) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.muted = on
            self._sound_changed(self._sel[1])

    def _set_denoise(self, on: bool) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.denoise = on
            self._sound_changed(self._sel[1])

    def _set_clip_volume(self, value: int) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.volume = round(value / 100, 2)
            self._sound_changed(self._sel[1], "clip_volume")

    def _framing_changed(self, kind: str = "") -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        self.preview.set_segment_framing(self._sel[1], clip.fit, clip.zoom, clip.pan_x, clip.pan_y)
        self._update_pan_target()
        self._fill_clip_inspector()
        self._record(kind)

    def _set_fit(self, fit: str) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.fit = fit
            self._framing_changed()

    def _set_clip_zoom(self, value: int) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.zoom = round(value / 100, 2)
            self._framing_changed("zoom")

    def _clip_keys(self) -> list[list[float]]:
        clip = self._sel_clip()
        return [list(k) for k in clip.fx.get("keys", [])] if clip is not None else []

    def _fill_keys(self) -> None:
        keys = self._clip_keys()
        clip = self._sel_clip()
        start = clip.span()[0] if clip is not None else 0.0
        row = self.keys_list.currentRow()
        self.keys_list.blockSignals(True)
        self.keys_list.clear()
        for k in keys:
            self.keys_list.addItem(f"{fmt_time(max(k[0] - start, 0.0))}  ·  {round(k[3] * 100)}%")
        if keys:
            self.keys_list.setCurrentRow(min(max(row, 0), len(keys) - 1))
        self.keys_list.blockSignals(False)
        self.key_del_btn.setEnabled(bool(keys))
        self.key_form.setVisible(bool(keys) and clip is not None and clip.has_video)
        self._fill_key_fields()

    def _fill_key_fields(self) -> None:
        keys, row = self._clip_keys(), self.keys_list.currentRow()
        clip = self._sel_clip()
        if clip is None or not 0 <= row < len(keys):
            return
        k = keys[row]
        for w, v in ((self.key_time, max(k[0] - clip.span()[0], 0.0)), (self.key_zoom, round(k[3] * 100)),
                     (self.key_x, round(k[1] * 100)), (self.key_y, round(k[2] * 100))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    def _set_keys(self, keys: list[list[float]], kind: str = "") -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        clip.fx = effects.sanitize({**clip.fx, "keys": keys})
        clip.fit = "fill" if clip.fx.get("keys") else clip.fit  # a crop is what zooms
        self._follow_changed()
        if kind:
            self._record(kind)

    def _add_key(self) -> None:
        clip = self._sel_clip()
        if clip is None or not clip.has_video:
            return
        i = self._sel[1]
        offset = self.track.offsets()[i]
        local = min(max(self.preview.position() - offset, 0.0), clip.kept())
        src = round(clip.span()[0] + local * clip.speed, 3)
        keys = self._clip_keys()
        zoom = keys[-1][3] if keys and keys[-1][3] > 1.0 else 1.6  # a first push in; later ones repeat the last
        if any(abs(k[0] - src) < 0.05 for k in keys):
            self.status.setText(self.t("There is a keyframe here already."))
            return
        if not keys:  # a move needs somewhere to start from: the picture as it is now
            keys.append([clip.span()[0], 0.5, 0.5, 1.0])
        keys.append([src, 0.5, 0.5, zoom])
        keys.sort(key=lambda k: k[0])
        self._set_keys(keys, "keys")
        self.keys_list.setCurrentRow(next(n for n, k in enumerate(self._clip_keys()) if abs(k[0] - src) < 1e-3))

    def _remove_key(self) -> None:
        keys, row = self._clip_keys(), self.keys_list.currentRow()
        if 0 <= row < len(keys):
            del keys[row]
            if len(keys) == 1 and keys[0][3] <= 1.0:  # only the start frame is left: no move at all
                keys = []
            self._set_keys(keys, "keys")

    def _edit_key(self) -> None:
        keys, row = self._clip_keys(), self.keys_list.currentRow()
        clip = self._sel_clip()
        if clip is None or not 0 <= row < len(keys):
            return
        keys[row] = [round(clip.span()[0] + self.key_time.value(), 3), self.key_x.value() / 100,
                     self.key_y.value() / 100, self.key_zoom.value() / 100]
        keys.sort(key=lambda k: k[0])
        self._set_keys(keys, "keys")

    def _follow_face(self) -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        if clip.fx.get("follow"):  # on already: this button turns it off
            clip.fx = effects.sanitize({k: v for k, v in clip.fx.items() if k != "follow"})
            self._follow_changed()
            return
        if not reframe.available():
            QMessageBox.information(self, self.t("Follow the face"), self.t(
                "Following a face needs the speech add-on, which this installation doesn't "
                "have. Install it with:\n\npip install \"vidgrab-studio[captions]\""))
            return
        if not self.host.ffmpeg_ok():
            return
        models = self.host.models_dir() if hasattr(self.host, "models_dir") else None
        if models is None:
            return
        if not reframe.model_ready(models) and QMessageBox.question(
                self, self.t("Follow the face"),
                self.t("Finding faces uses a small model ({size}), downloaded once. "
                       "Continue?", size=reframe.MODEL_SIZE_LABEL)) != QMessageBox.Yes:
            return
        start, end = clip.span()
        self._follow_gen += 1
        self._follow_clip = clip
        self.follow_btn.setEnabled(False)
        self.status.setText(self.t("Looking for the face…"))
        self._follow_pool.start(_FollowTask(
            self._follow_relay, self._follow_gen, clip.path, start, end, str(models),
            self._follow_cancel, self.t))

    def _follow_progress(self, gen: int, text: str, pct: int) -> None:
        if gen == self._follow_gen:
            self.status.setText(f"{text} {pct}%")

    def _follow_done(self, gen: int, keys, error: str) -> None:
        if gen != self._follow_gen:
            return
        self.follow_btn.setEnabled(True)
        clip = self._follow_clip
        if error:
            self.status.setText(error)
            QMessageBox.warning(self, self.t("Follow the face"), error)
            return
        if not keys or clip not in self._clips:
            self.status.setText(self.t("No face was found in this clip."))
            return
        clip.fit = "fill"  # a crop is what follows
        clip.fx = effects.sanitize({**clip.fx, "follow": keys})
        self._follow_changed()
        self.status.setText(self.t("Following the face."))
        if (self.res.currentData() or "auto") not in ("vertical", "square") and QMessageBox.question(
                self, self.t("Follow the face"),
                self.t("Make the video vertical (9:16, for Shorts and Reels) so the crop has "
                       "something to follow?")) == QMessageBox.Yes:
            self._set_export("shorts")

    def _follow_changed(self) -> None:
        self._framing_changed()  # (fills the inspector and records the edit)
        self.preview.refresh_effects(self._segments())

    def _center_clip(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.pan_x = clip.pan_y = 0.5
            self._framing_changed()

    def _on_pan_dragged(self, seg: int, x: float, y: float) -> None:
        if 0 <= seg < len(self._clips):
            clip = self._clips[seg]
            clip.pan_x, clip.pan_y = x, y
            self.preview.set_segment_framing(seg, clip.fit, clip.zoom, x, y)
            self._record("pan")

    def _update_pan_target(self) -> None:
        clip = self._sel_clip()
        pannable = clip is not None and self.is_video() and clip.has_video \
            and (clip.fit == "fill" or clip.zoom > 1.0)
        self.preview.set_pan_segment(self._sel[1] if pannable else None)
