"""The "Remove silences" dialog: choose how quiet counts as a pause and how long
a pause has to be, and see which parts of the clip would be cut before anything
changes. Qt part only — `studio.detect_silences` / `studio.speech_ranges` do the
finding, and the clip is split by the Studio page from `ranges()`."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import studio

LEVEL_LABELS = {"silence": "Dead silence only", "quiet": "Quiet pauses", "faint": "Anything faint"}
PAUSES = (0.4, 0.6, 1.0, 1.5)


class CutStrip(QWidget):
    """The clip as one bar: what stays is coloured, what goes is struck out."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(46)
        self.start = 0.0
        self.end = 1.0
        self.keeps: list[tuple[float, float]] = []

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 6, -0.5, -6)
        span = max(self.end - self.start, 1e-6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(229, 83, 75, 90))  # the whole bar is "cut" until a part says it stays
        p.drawRoundedRect(r, 6, 6)
        p.setClipRect(r)
        p.setBrush(QColor("#7C5CFF"))
        for a, b in self.keeps:
            x0 = r.left() + (a - self.start) / span * r.width()
            x1 = r.left() + (b - self.start) / span * r.width()
            p.drawRect(QRectF(x0, r.top(), max(x1 - x0, 1.5), r.height()))


class SilenceDialog(QDialog):
    """`ranges()` after accept: the (start, end) parts of the file to keep."""

    def __init__(self, parent: QWidget, t: Callable[..., str], path: str, start: float,
                 end: float) -> None:
        super().__init__(parent)
        self.t = t
        self.path, self.start, self.end = path, start, end
        self._keeps: list[tuple[float, float]] = [(start, end)]
        self._cache: dict[tuple[float, float], list[tuple[float, float]]] = {}
        self.setWindowTitle(t("Remove silences"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        intro = QLabel(t("Cut the quiet pauses out of this clip. It is split into pieces "
                         "that play one after another."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        opts = QHBoxLayout()
        opts.setSpacing(12)
        for attr, cap_text, combo_items in (
            ("level", "COUNTS AS A PAUSE",
             [(t(LEVEL_LABELS[k]), k) for k in studio.SILENCE_LEVELS]),
            ("pause", "AT LEAST",
             [(t("{n} s", n=f"{v:g}"), v) for v in PAUSES]),
        ):
            col = QVBoxLayout()
            cap = QLabel(t(cap_text))
            cap.setObjectName("field_cap")
            col.addWidget(cap)
            combo = QComboBox()
            for label, data in combo_items:
                combo.addItem(label, data)
            combo.activated.connect(self._find)
            setattr(self, attr, combo)
            col.addWidget(combo)
            opts.addLayout(col, 1)
        self.level.setCurrentIndex(self.level.findData("quiet"))
        self.pause.setCurrentIndex(self.pause.findData(0.6))
        lay.addLayout(opts)

        self.strip = CutStrip()
        self.strip.start, self.strip.end = start, end
        lay.addWidget(self.strip)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        hint = QLabel(t("Purple stays, red is cut. A little of each pause is kept so words "
                        "do not start or stop abruptly."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(t("Cancel"))
        cancel.clicked.connect(self.reject)
        self.go = QPushButton(t("Cut them out"))
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.go)
        lay.addLayout(buttons)
        self._find()

    def _find(self, *_a) -> None:
        key = (float(studio.SILENCE_LEVELS[self.level.currentData()]), float(self.pause.currentData()))
        if key not in self._cache:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._cache[key] = studio.detect_silences(
                    self.path, self.start, self.end, noise_db=key[0], min_len=key[1])
            finally:
                QApplication.restoreOverrideCursor()
        silences = self._cache[key]
        self._keeps = studio.speech_ranges(self.start, self.end, silences) if silences else [
            (self.start, self.end)]
        kept = sum(b - a for a, b in self._keeps)
        total = self.end - self.start
        cut = max(0.0, total - kept)
        self.strip.keeps = self._keeps
        self.strip.update()
        if not silences or cut < 0.05:
            self.summary.setText(self.t("No pauses found. Try “Anything faint” or a shorter pause."))
            self.go.setEnabled(False)
        else:
            self.summary.setText(self.t(
                "{n} pauses found: {cut} of {total} will be cut, leaving {left}.",
                n=len(silences), cut=_clock(cut), total=_clock(total), left=_clock(kept)))
            self.go.setEnabled(True)

    def ranges(self) -> list[tuple[float, float]]:
        return list(self._keeps)


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}" if m else f"{s:.1f} s"


