"""The Project inspector page."""
from __future__ import annotations

from PySide6.QtGui import (
    QCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from vidgrab.ui.preview import (
    fmt_time,
)
from vidgrab.ui.studio.common import _HAND, EXPORT_PRESETS


class ProjectInspectorMixin:
    """The Project inspector page."""

    def _build_project_inspector(self) -> QWidget:
        w, lay = self._page()
        # what to make: each preset sets the frame size and the file type
        self.export_cap = self._label("EXPORT AS", "field_cap")
        lay.addWidget(self.export_cap)
        self.export_btns: dict[str, QPushButton] = {}
        self.export_box = self._choice_grid(
            [(k, EXPORT_PRESETS[k][0]) for k in EXPORT_PRESETS], 2, self._set_export,
            self.export_btns)
        lay.addWidget(self.export_box)
        self.export_hint = QLabel()
        self.export_hint.setObjectName("hint")
        self.export_hint.setWordWrap(True)
        lay.addWidget(self.export_hint)
        form = QFormLayout()
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.res = QComboBox()
        self.res.currentIndexChanged.connect(lambda _i: (self._refresh_aspect(),
                                                         self._sync_export()))
        self.res_lbl = self._label("Resolution:")
        form.addRow(self.res_lbl, self.res)
        self.xfade = QDoubleSpinBox()
        self.xfade.setRange(0.0, 10.0)
        self.xfade.setSingleStep(0.5)
        self.xfade.setValue(2.0)
        self.xfade.setSuffix(" s")
        self.afmt = QComboBox()
        for label, ext in (("MP3", ".mp3"), ("M4A (AAC)", ".m4a"), ("WAV", ".wav")):
            self.afmt.addItem(label, ext)
        self.abr = QComboBox()
        for br in ("320", "256", "192", "128"):
            self.abr.addItem(f"{br} kbps", br)
        self.abr.setCurrentIndex(2)
        self.afmt.currentIndexChanged.connect(
            lambda _i: self.abr.setEnabled(self.afmt.currentData() != ".wav"))
        self.xfade_lbl = self._label("Crossfade:")
        self.afmt_lbl = self._label("Format:")
        self.abr_lbl = self._label("Quality:")
        form.addRow(self.xfade_lbl, self.xfade)
        form.addRow(self.afmt_lbl, self.afmt)
        form.addRow(self.abr_lbl, self.abr)
        self.name = QLineEdit()
        form.addRow(self._label("File name:"), self.name)
        lay.addLayout(form)
        self.loud_cb = QCheckBox()
        self.loud_cb.setCursor(QCursor(_HAND))
        self._tr(self.loud_cb, "Even out the loudness")
        self._tr(self.loud_cb, "Brings the whole video to the loudness YouTube and Shorts aim for "
                 "(-14 LUFS), so it is neither too quiet nor too loud. Applied when you render.",
                 "setToolTip")
        self.loud_cb.toggled.connect(lambda _on: self._record())
        lay.addWidget(self.loud_cb)
        lay.addWidget(self._label("Save to:"))
        row = QHBoxLayout()
        self.out_dir = QLineEdit(str(self.host.default_output_dir()))
        row.addWidget(self.out_dir, stretch=1)
        b = self._btn("…", self._browse_out, "Browse…")
        b.setFixedWidth(40)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _set_export(self, preset: str) -> None:
        self._export = preset
        res = EXPORT_PRESETS[preset][1]
        if res is not None:
            self.res.blockSignals(True)
            self.res.setCurrentIndex(max(0, self.res.findData(res)))
            self.res.blockSignals(False)
            self._refresh_aspect()
        self._sync_export()
        self._record()

    def _sync_export(self) -> None:
        """Highlight the preset that matches; say what to watch out for."""
        if not hasattr(self, "export_btns"):
            return
        preset = getattr(self, "_export", "youtube")
        res = self.res.currentData() or "auto"
        if EXPORT_PRESETS[preset][1] not in (None, res):  # resolution changed by hand
            preset = next((k for k, v in EXPORT_PRESETS.items()
                           if v[1] == res and v[2] == ".mp4"), "youtube")
            self._export = preset
        self.export_btns[preset].setChecked(True)
        total = self.track.total()
        hint = ""
        if preset == "shorts" and total > 60:
            hint = self.t("Shorts, Reels and TikTok videos are at most 60 s; this one is {d}.",
                          d=fmt_time(total))
        elif preset == "gif":
            hint = self.t("A GIF has no sound and gets large quickly: best for a few seconds "
                          "({d} now).", d=fmt_time(total))
        elif preset == "audio":
            hint = self.t("Only the sound: clips, music and their levels, as an MP3.")
        self.export_hint.setText(hint)
        self.export_hint.setVisible(bool(hint))
