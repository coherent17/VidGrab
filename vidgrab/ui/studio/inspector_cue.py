"""Subtitle lines: the inspector and the edits it makes."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab.media import effects
from vidgrab.media.studio import (
    ANIMATIONS,
    SUBTITLE_FONT_NAME,
    SubtitleCue,
    cue_style,
    format_srt,
    format_transcript,
    format_vtt,
    parse_srt,
    parse_timecode,
    system_fonts,
)
from vidgrab.ui.preview import (
    fmt_time,
)
from vidgrab.ui.studio.common import _HAND, ANIMATION_LABELS, BG_COLORS, TEXT_COLORS
from vidgrab.ui.studio.widgets import ColorSwatches


class CueInspectorMixin:
    """Subtitle lines: the inspector and the edits it makes."""

    def _build_cue_inspector(self) -> QWidget:
        """Two tabs, so nothing needs scrolling: *Line* (the selected line's
        text, timing, position, split / duplicate) and *Style* (shared by
        every line). Colours are swatches, the default position two buttons."""
        page, outer = self._page()
        tabs = QWidget()
        tabs.setObjectName("segmented")
        tabs.setAttribute(Qt.WA_StyledBackground, True)
        tl = QHBoxLayout(tabs)
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(4)
        self.cue_tabs = QStackedWidget()
        self.cue_tab_btns: list[QPushButton] = []
        for i, key in enumerate(("Line", "Effects", "All lines")):
            b = QPushButton()
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, k=i: self.cue_tabs.setCurrentIndex(k))
            self._tr(b, key)
            tl.addWidget(b, stretch=1)
            self.cue_tab_btns.append(b)
        self.cue_tab_btns[0].setChecked(True)
        outer.addWidget(tabs)
        self.cue_tabs.addWidget(self._build_line_tab())
        self.cue_tabs.addWidget(self._build_effects_tab())
        self.cue_tabs.addWidget(self._build_style_tab())
        outer.addWidget(self.cue_tabs, stretch=1)
        return page

    def _scroll(self, inner: QWidget) -> QScrollArea:
        """Fallback scrolling for very short windows."""
        scroll = QScrollArea()
        scroll.setObjectName("page_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _build_line_tab(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        head = QHBoxLayout()
        head.addWidget(self._label("Text:"), stretch=1)
        head.addWidget(self._btn("Paste", self._paste_text, "Paste text from the clipboard"))
        lay.addLayout(head)
        self.cue_text = QPlainTextEdit()
        self.cue_text.setFixedHeight(64)
        self.cue_text.textChanged.connect(self._edit_cue_text)
        lay.addWidget(self.cue_text)
        times = QHBoxLayout()
        times.setSpacing(8)
        self.cue_start = QLineEdit()
        self.cue_end = QLineEdit()
        self.cue_start.editingFinished.connect(lambda: self._edit_cue_time("start"))
        self.cue_end.editingFinished.connect(lambda: self._edit_cue_time("end"))
        times.addWidget(self._label("Start:"))
        times.addWidget(self.cue_start, stretch=1)
        times.addWidget(self._label("End:"))
        times.addWidget(self.cue_end, stretch=1)
        lay.addLayout(times)

        # position: 3×3 quick grid (same numbering as ASS \an), or drag in preview
        lay.addWidget(self._label("POSITION", "field_cap"))
        pos_row = QHBoxLayout()
        pos_row.setSpacing(12)
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._anchor_btns: dict[int, QPushButton] = {}
        for r, row_anchors in enumerate(((7, 8, 9), (4, 5, 6), (1, 2, 3))):
            for c, anchor in enumerate(row_anchors):
                b = QPushButton()
                b.setObjectName("anchor_btn")
                b.setCheckable(True)
                b.setFixedSize(34, 24)
                b.setIconSize(QSize(18, 12))
                b.setCursor(QCursor(_HAND))
                b.clicked.connect(lambda _c=False, a=anchor: self._set_anchor(a))
                grid.addWidget(b, r, c)
                self._anchor_btns[anchor] = b
        pos_row.addWidget(grid_box)
        pos_col = QVBoxLayout()
        pos_col.setSpacing(6)
        self.cue_pos = QLabel()
        self.cue_pos.setObjectName("hint")
        self.cue_pos.setWordWrap(True)
        pos_col.addWidget(self.cue_pos)
        pos_col.addWidget(self._btn("Reset position", self._reset_cue_pos))
        pos_col.addWidget(self._btn("Use for all", self._apply_pos_all,
                                    "Use this position for all lines"))
        pos_col.addStretch()
        pos_row.addLayout(pos_col, stretch=1)
        lay.addLayout(pos_row)
        lay.addWidget(self._label("Or drag the text in the preview.", "hint"))
        lay.addWidget(self._label("EDIT", "field_cap"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._btn("✂ Split at playhead", self._split_cue,
                                "Cut this line in two at the playhead"))
        row.addWidget(self._btn("Duplicate", self._duplicate_cue,
                                "Copy this line right after itself"))
        lay.addLayout(row)
        lay.addStretch()
        return self._scroll(inner)

    def _build_effects_tab(self) -> QWidget:
        """This line only: how it comes on screen, and (optionally) its own
        colours / size over the shared style."""
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        lay.addWidget(self._label("TEXT STYLES", "field_cap"))
        styles = QGridLayout()
        styles.setSpacing(6)
        for n, (key, label) in enumerate((("title", "Big title"), ("lower_third", "Name tag"),
                                          ("quote", "Quote"), ("caption_box", "Caption box"))):
            b = self._btn(label, lambda _c=False, k=key: self._apply_text_style(k),
                          "Set this line's look, animation and place in one click")
            styles.addWidget(b, n // 2, n % 2)
        lay.addLayout(styles)
        lay.addSpacing(4)
        lay.addWidget(self._label("ANIMATION", "field_cap"))
        self.cue_anim_btns: dict[str, QPushButton] = {}
        lay.addWidget(self._choice_grid(
            [(k, ANIMATION_LABELS[k]) for k in ANIMATIONS], 3, self._set_cue_animation,
            self.cue_anim_btns))
        lay.addWidget(self._btn("Use this animation for every line", self._animation_for_all))
        lay.addSpacing(4)
        lay.addWidget(self._label("OWN LOOK", "field_cap"))
        self.own_look = QCheckBox()
        self.own_look.setCursor(QCursor(_HAND))
        self._tr(self.own_look, "Give this line its own look")
        self.own_look.toggled.connect(self._own_look_toggled)
        lay.addWidget(self.own_look)
        self.own_box = QWidget()
        ob = QVBoxLayout(self.own_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(5)
        self.own_color = ColorSwatches(TEXT_COLORS, allow_none=False, t=self.t)
        self.own_color.changed.connect(lambda c: self._set_own("color", c))
        ob.addWidget(self._label("Text color:"))
        ob.addWidget(self.own_color)
        self.own_bg = ColorSwatches(BG_COLORS, allow_none=True, t=self.t)
        self.own_bg.changed.connect(lambda c: self._set_own("background", c or None))
        ob.addWidget(self._label("Background:"))
        ob.addWidget(self.own_bg)
        size_row = QHBoxLayout()
        size_row.addWidget(self._label("Size:"))
        self.own_size = QSpinBox()
        self.own_size.setRange(10, 72)
        self.own_size.valueChanged.connect(lambda v: self._set_own("size", v, "own_size"))
        self.own_bold = QCheckBox()
        self.own_bold.setCursor(QCursor(_HAND))
        self._tr(self.own_bold, "Bold")
        self.own_bold.toggled.connect(lambda on: self._set_own("bold", on))
        size_row.addWidget(self.own_size, stretch=1)
        size_row.addWidget(self.own_bold)
        ob.addLayout(size_row)
        lay.addWidget(self.own_box)
        lay.addWidget(self._label(
            "Lines without their own look follow All lines.", "hint"))
        lay.addStretch()
        return self._scroll(inner)

    def _cur_cue(self) -> SubtitleCue | None:
        if self._sel and self._sel[0] == "cue" and 0 <= self._sel[1] < len(self._cues):
            return self._cues[self._sel[1]]
        return None

    def _cue_look_changed(self, kind: str = "") -> None:
        self.preview.set_cues(self._preview_cues(), self._sel[1] if self._cur_cue() else None)
        self._refresh_track()
        self.track.set_selection(self._sel)
        self._fill_effects()
        self._record(kind)

    def _apply_text_style(self, key: str) -> None:
        """One-click title / name tag / quote: look, animation and place together."""
        cue = self._cur_cue()
        if cue is None:
            return
        spec = effects.TEXT_TEMPLATES[key]
        if cue.text.strip() in ("", self.t("New subtitle")):
            cue.text = self.t(spec["text"])
        cue.look = dict(spec["look"])
        cue.animation = spec["animation"]
        cue.anchor, cue.x, cue.y = spec["anchor"], spec["x"], spec["y"]
        self._cue_look_changed()
        self._fill_cue_inspector()
        self.preview.seek(cue.start + 0.01)

    def _set_cue_animation(self, kind: str) -> None:
        cue = self._cur_cue()
        if cue is not None:
            cue.animation = kind
            self._cue_look_changed()
            self.preview.seek(cue.start + 0.01)  # play it from the start of the line

    def _animation_for_all(self) -> None:
        cue = self._cur_cue()
        if cue is not None:
            for other in self._cues:
                other.animation = cue.animation
            self._cue_look_changed()

    def _own_look_toggled(self, on: bool) -> None:
        cue = self._cur_cue()
        if cue is None or on == bool(cue.look):
            return
        st = self._style()
        cue.look = ({"color": st.color, "background": st.background, "size": st.size,
                     "bold": st.bold} if on else None)
        self._cue_look_changed()

    def _set_own(self, key: str, value, kind: str = "") -> None:
        cue = self._cur_cue()
        if cue is None or not cue.look:
            return
        cue.look = {**cue.look, key: value}
        self._cue_look_changed(kind)

    def _fill_effects(self) -> None:
        cue = self._cur_cue()
        if cue is None:
            return
        self.cue_anim_btns.get(cue.animation, self.cue_anim_btns["none"]).setChecked(True)
        own = bool(cue.look)
        look = cue_style(cue, self._style())
        for w in (self.own_look, self.own_size, self.own_bold):
            w.blockSignals(True)
        self.own_look.setChecked(own)
        self.own_size.setValue(int(look.size))
        self.own_bold.setChecked(bool(look.bold))
        for w in (self.own_look, self.own_size, self.own_bold):
            w.blockSignals(False)
        self.own_color.set_color(look.color)
        self.own_bg.set_color(look.background)
        self.own_box.setEnabled(own)

    def _build_style_tab(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.preset_combo = QComboBox()
        self.preset_combo.setCursor(QCursor(_HAND))
        self.preset_combo.activated.connect(
            lambda _i: self.apply_preset(self.preset_combo.currentData() or ""))
        preset_row.addWidget(self.preset_combo, stretch=1)
        preset_row.addWidget(self._btn("Save\u2026", self._save_preset, "Save as preset\u2026"))
        self.preset_del = self._btn("\u2715", self._delete_preset, "Delete preset")
        self.preset_del.setFixedWidth(40)
        preset_row.addWidget(self.preset_del)
        lay.addLayout(preset_row)

        form = QFormLayout()
        form.setSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sub_font = QComboBox()
        self.sub_font.setCursor(QCursor(_HAND))
        self.sub_font.setMaxVisibleItems(18)
        self.sub_font.currentIndexChanged.connect(lambda _i: self._push_style())
        self.sub_bold = QCheckBox()
        self.sub_bold.setCursor(QCursor(_HAND))
        self.sub_bold.toggled.connect(lambda _c: self._push_style())
        self._tr(self.sub_bold, "Bold")
        self.sub_size = QSpinBox()
        self.sub_size.setRange(10, 72)
        self.sub_size.setValue(24)
        self.sub_size.valueChanged.connect(lambda _v: self._push_style())
        size_row = QHBoxLayout()
        size_row.addWidget(self.sub_size, stretch=1)
        size_row.addWidget(self.sub_bold)
        form.addRow(self._label("Font:"), self.sub_font)
        form.addRow(self._label("Size:"), size_row)
        lay.addLayout(form)

        lay.addWidget(self._label("Text color:"))
        self.sub_color = ColorSwatches(TEXT_COLORS, allow_none=False, t=self.t)
        self.sub_color.changed.connect(lambda _c: self._push_style())
        lay.addWidget(self.sub_color)
        lay.addWidget(self._label("Background:"))
        self.sub_bg = ColorSwatches(BG_COLORS, allow_none=True, t=self.t)
        self.sub_bg.set_color("#000000")
        self.sub_bg.changed.connect(lambda _c: self._push_style())
        lay.addWidget(self.sub_bg)
        self.sub_bg_opacity, op_row = self._level(60)
        self.sub_bg_opacity.setRange(10, 100)
        self.sub_bg_opacity.valueChanged.connect(lambda _v: self._push_style())
        op = QHBoxLayout()
        op.addWidget(self._label("Opacity:"))
        op.addLayout(op_row, stretch=1)
        lay.addLayout(op)

        form2 = QFormLayout()
        form2.setSpacing(9)
        form2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sub_fade = QDoubleSpinBox()
        self.sub_fade.setRange(0.0, 2.0)
        self.sub_fade.setSingleStep(0.1)
        self.sub_fade.setDecimals(1)
        self.sub_fade.setSuffix(" s")
        self.sub_fade.valueChanged.connect(lambda _v: self._push_style())
        form2.addRow(self._label("Fade in / out:"), self.sub_fade)
        pos = QWidget()
        pos.setObjectName("segmented")
        pos.setAttribute(Qt.WA_StyledBackground, True)
        pl = QHBoxLayout(pos)
        pl.setContentsMargins(3, 3, 3, 3)
        pl.setSpacing(3)
        self.sub_pos_btns: dict[str, QPushButton] = {}
        for value, key in (("bottom", "Bottom"), ("top", "Top")):
            b = QPushButton()
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False: self._push_style())
            self._tr(b, key)
            pl.addWidget(b, stretch=1)
            self.sub_pos_btns[value] = b
        self.sub_pos_btns["bottom"].setChecked(True)
        form2.addRow(self._label("Default position:"), pos)
        lay.addLayout(form2)
        lay.addStretch()
        self._fill_fonts()
        return self._scroll(inner)

    def _fill_fonts(self) -> None:
        self.sub_font.blockSignals(True)
        self.sub_font.clear()
        self.sub_font.addItem(f"{SUBTITLE_FONT_NAME} ★", SUBTITLE_FONT_NAME)
        for family in system_fonts():
            if family != SUBTITLE_FONT_NAME:
                self.sub_font.addItem(family, family)
        self.sub_font.setCurrentIndex(0)
        self.sub_font.blockSignals(False)

    def _anchor_icons(self, color: str) -> None:
        for anchor, b in [*self._anchor_btns.items(), *self._image_anchor_btns.items()]:
            pm = QPixmap(18, 12)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(color), 1))
            p.drawRoundedRect(QRectF(0.5, 0.5, 17, 11), 2, 2)
            col, row = (anchor - 1) % 3, (anchor - 1) // 3
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(2 + col * 5, 8 - row * 3.2, 4, 2.4), 1, 1)
            p.end()
            b.setIcon(QIcon(pm))

    def _tab_bar(self, keys: tuple[str, ...]) -> tuple[QWidget, QStackedWidget, list[QPushButton]]:
        """Segmented tabs over a stack of pages (add the pages in the same order)."""
        bar = QWidget()
        bar.setObjectName("segmented")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 4, 4, 4)
        bl.setSpacing(4)
        stack = QStackedWidget()
        buttons = []
        for i, key in enumerate(keys):
            b = QPushButton()
            b.setObjectName("segment")
            b.setProperty("compact", True)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumHeight(32)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, k=i: stack.setCurrentIndex(k))
            self._tr(b, key)
            bl.addWidget(b, stretch=1)
            buttons.append(b)
        buttons[0].setChecked(True)
        self._tab_bars = getattr(self, "_tab_bars", [])
        self._tab_bars.append((bl, buttons))
        self._balance_tabs()
        return bar, stack, buttons

    def _balance_tabs(self) -> None:
        """Give each tab a width in proportion to its label, so a long label (in any
        language or font) is not cut off while a short one leaves room."""
        for lay, buttons in getattr(self, "_tab_bars", []):
            for i, b in enumerate(buttons):
                font = QFont(b.font())
                font.setBold(True)
                lay.setStretch(i, QFontMetrics(font).horizontalAdvance(b.text()) + 20)

    def _choice_grid(self, items: list[tuple[str, str]], columns: int, slot,
                     store: dict[str, QPushButton]) -> QWidget:
        """Every option visible as a button (no dropdown); one is checked."""
        box = QWidget()
        box.setObjectName("segmented")
        box.setAttribute(Qt.WA_StyledBackground, True)
        grid = QGridLayout(box)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(4)
        for n, (value, key) in enumerate(items):
            b = QPushButton()
            b.setObjectName("segment")
            b.setProperty("compact", True)
            # share the row equally whatever the label length (the panel is narrow)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumHeight(30)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, v=value: slot(v))
            self._tr(b, key)
            grid.addWidget(b, n // columns, n % columns)
            store[value] = b
        return box

    def _add_cue(self) -> None:
        self._add_cue_at(self.preview.position())

    def _add_cue_at(self, t: float) -> None:
        total = self.track.total()
        if total <= 0:
            self.status.setText(self.t("Add at least one clip first."))
            return
        start = round(min(t, max(0.0, total - 0.5)), 2)
        cue = SubtitleCue(start, round(min(start + 3.0, total), 2), self.t("New subtitle"))
        self._cues.append(cue)
        self._sel = ("cue", len(self._cues) - 1)
        self._cues_changed()
        self.select_cue(self._cues.index(cue))
        self._record()
        self.cue_text.setFocus()
        self.cue_text.selectAll()

    def _cue_edited(self) -> None:
        self._cues_changed()
        if self._sel and self._sel[0] == "cue":
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._fill_cue_inspector()

    def _fill_cue_inspector(self) -> None:
        cue = self._cues[self._sel[1]]
        if self.cue_text.toPlainText() != cue.text:
            self.cue_text.blockSignals(True)
            self.cue_text.setPlainText(cue.text)
            self.cue_text.blockSignals(False)
        self.cue_start.setText(fmt_time(cue.start))
        self.cue_end.setText(fmt_time(cue.end))
        if cue.x is None:
            where = self.sub_pos_btns[self._sub_position()].text()
            self.cue_pos.setText(self.t("Default ({where})", where=where))
        else:
            self.cue_pos.setText(self.t("Custom ({x}%, {y}%)",
                                        x=round(cue.x * 100), y=round(cue.y * 100)))
        self._fill_effects()
        snapped = cue.anchor if cue.x is not None and cue.x in (0.05, 0.5, 0.95) \
            and cue.y in (0.05, 0.5, 0.95) else None
        for anchor, b in self._anchor_btns.items():
            b.setChecked(anchor == snapped)

    def _edit_cue_text(self) -> None:
        if not self._sel or self._sel[0] != "cue":
            return
        cue = self._cues[self._sel[1]]
        if cue.text != self.cue_text.toPlainText():
            cue.words = None  # the timings belong to the old text
        cue.text = self.cue_text.toPlainText()
        self._refresh_track()
        self.preview.set_cues(self._preview_cues(), self._sel[1])
        self._record(f"text{self._sel[1]}")

    def _paste_text(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.cue_text.insertPlainText(text)
            self.cue_text.setFocus()

    def _edit_cue_time(self, which: str) -> None:
        if not self._sel or self._sel[0] != "cue":
            return
        cue = self._cues[self._sel[1]]
        value = parse_timecode((self.cue_start if which == "start" else self.cue_end).text())
        if value is not None:
            if which == "start" and value < cue.end - 0.1:
                cue.start = round(max(0.0, value), 2)
            elif which == "end" and value > cue.start + 0.1:
                cue.end = round(value, 2)
            self._cue_edited()
            self._record()
        self._fill_cue_inspector()

    def _on_cue_moved(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].x, self._cues[row].y = x, y
            self._cues[row].anchor = 5  # dragging places the text's centre
            if self._sel != ("cue", row):
                self.select_cue(row)
            self.preview.set_cues(self._preview_cues(), row)
            self._fill_cue_inspector()
            self._record()

    def _on_cue_dragged(self, row: int, start: float, end: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].start, self._cues[row].end = start, end
            self._sel = ("cue", row)
            self._cue_edited()
            self._record()

    def _set_anchor(self, anchor: int) -> None:
        """Snap the selected line to one of the 9 grid positions."""
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        col, row = (anchor - 1) % 3, (anchor - 1) // 3
        margin = 0.05
        cue.x = (margin, 0.5, 1 - margin)[col]
        cue.y = (1 - margin, 0.5, margin)[row]
        cue.anchor = anchor
        self.preview.set_cues(self._preview_cues(), self._sel[1])
        self._fill_cue_inspector()
        self._record()

    def _split_cue(self) -> None:
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        t = round(self.preview.position(), 2)
        if not cue.start + 0.2 <= t <= cue.end - 0.2:
            self.status.setText(self.t("Move the playhead inside this line to split it."))
            return
        second = replace(cue, start=t, words=None)  # (word times don't follow a split)
        cue.end, cue.words = t, None
        self._cues.append(second)
        self._sel = ("cue", self._cues.index(second))
        self._cues_changed()
        self.select_cue(self._cues.index(second))
        self._record()

    def _duplicate_cue(self) -> None:
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        length = cue.end - cue.start
        total = self.track.total()
        start = min(cue.end, max(0.0, total - 0.3))
        copy = replace(cue, start=round(start, 2), end=round(min(start + length, total), 2))
        self._cues.append(copy)
        self._sel = ("cue", self._cues.index(copy))
        self._cues_changed()
        self.select_cue(self._cues.index(copy))
        self.preview.seek(copy.start + 0.01)
        self._record()

    def refresh_presets(self) -> None:
        names = sorted(self.host.subtitle_presets()) if hasattr(self.host, "subtitle_presets") else []
        current = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(self.t("Choose a preset…"), "")
        for name in names:
            self.preset_combo.addItem(name, name)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(current)))
        self.preset_combo.blockSignals(False)
        self.preset_del.setEnabled(bool(self.preset_combo.currentData()))

    def _style_dict(self) -> dict:
        st = self._style()
        return {"font": st.font, "size": st.size, "bold": st.bold, "color": st.color,
                "background": st.background, "bg_opacity": st.bg_opacity,
                "fade": st.fade, "position": st.position}

    def _apply_style_dict(self, style: dict) -> None:
        widgets = (self.sub_font, self.sub_size, self.sub_bold, self.sub_bg_opacity, self.sub_fade)
        for w in widgets:
            w.blockSignals(True)
        font_idx = self.sub_font.findData(style.get("font", SUBTITLE_FONT_NAME))
        self.sub_font.setCurrentIndex(max(font_idx, 0))
        self.sub_size.setValue(int(style.get("size", 24)))
        self.sub_bold.setChecked(bool(style.get("bold")))
        self.sub_color.set_color(style.get("color", "#FFFFFF"))
        self.sub_bg.set_color(style.get("background"))
        self.sub_bg_opacity.setValue(round(float(style.get("bg_opacity", 0.6)) * 100))
        self.sub_fade.setValue(float(style.get("fade", 0.0)))
        position = style.get("position", "bottom")
        self.sub_pos_btns.get(position, self.sub_pos_btns["bottom"]).setChecked(True)
        for w in widgets:
            w.blockSignals(False)
        self._push_style()

    def apply_preset(self, name: str) -> None:
        preset = self.host.subtitle_presets().get(name)
        if not preset:
            self.preset_del.setEnabled(False)
            return
        self._apply_style_dict(preset)
        self.preset_del.setEnabled(True)

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, self.t("Save as preset…"),
                                        self.t("Preset name:"))
        name = name.strip()
        if ok and name:
            self.host.save_subtitle_preset(name, self._style_dict())
            self.preset_combo.setCurrentIndex(self.preset_combo.findData(name))
            self.preset_del.setEnabled(True)

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentData()
        if name:
            self.host.delete_subtitle_preset(name)

    def set_default_resolution(self, value: str | None) -> None:
        idx = self.res.findData(value or "auto")
        if idx >= 0:
            self.res.setCurrentIndex(idx)

    def _reset_cue_pos(self) -> None:
        if self._sel and self._sel[0] == "cue":
            cue = self._cues[self._sel[1]]
            cue.x = cue.y = None
            cue.anchor = 5
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._fill_cue_inspector()
            self._record()

    def _apply_pos_all(self) -> None:
        if self._sel and self._sel[0] == "cue":
            src = self._cues[self._sel[1]]
            for cue in self._cues:
                cue.x, cue.y, cue.anchor = src.x, src.y, src.anchor
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._record()

    def load_srt(self, path: str) -> bool:
        """Replace the subtitle lines with those in an .srt file (the YouTube
        captions that come with "Send to Studio")."""
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return False
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("big5", errors="replace")
        cues = parse_srt(text)
        if not cues:
            return False
        self._cues = cues
        self.deselect()
        self._cues_changed()
        self._record()
        return True

    def cues(self) -> list[SubtitleCue]:
        return [replace(c) for c in self._cues if c.text.strip()]

    def import_subtitles(self) -> None:
        """Read the lines of an .srt / .vtt file onto the Subtitles row (one undo step)."""
        path = self.host.pick_file(self.t("Import subtitles"), ("Videos", "Downloads"),
                                   "Subtitles (*.srt *.vtt);;All files (*)")
        if not path:
            return
        if self._cues and QMessageBox.question(
                self, self.t("Import subtitles"),
                self.t("Replace the current subtitle lines with the ones in this file?")
        ) != QMessageBox.Yes:
            return
        if self.load_srt(path):
            self.status.setText(self.t("Added {n} subtitle lines", n=len(self._cues)))
        else:
            QMessageBox.warning(self, self.t("Import subtitles"),
                                self.t("No subtitle lines were found in that file."))

    def export_subtitles(self) -> None:
        """Save the lines as .srt, .vtt or plain text (the file's ending chooses)."""
        cues = self.cues()
        if not cues:
            return
        default = (self.name.text().strip() or "subtitles") + ".srt"
        path = self.host.pick_save(self.t("Export subtitles"), default,
                                   "SubRip (*.srt);;WebVTT (*.vtt);;Text (*.txt)")
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in (".srt", ".vtt", ".txt"):
            path, suffix = path + ".srt", ".srt"
        text = (format_vtt(cues) if suffix == ".vtt"
                else format_transcript(cues) if suffix == ".txt" else format_srt(cues))
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, self.t("Export subtitles"), str(exc))
            return
        self.status.setText(self.t("Saved: {name}", name=Path(path).name))

    def copy_transcript(self) -> None:
        text = format_transcript(self.cues())
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText(self.t("Transcript copied"))
