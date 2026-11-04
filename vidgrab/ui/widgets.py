"""Small form widgets used by the pages."""
from __future__ import annotations

from PySide6.QtCore import (
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QWidget,
)

from vidgrab.ui.drawing import _HAND, _checkmark_path


def _colored_check(text: str, color: str) -> QCheckBox:
    """QCheckBox with a custom accent color + white checkmark on check."""
    check = _checkmark_path()
    cb = QCheckBox(text)
    cb.setStyleSheet(
        f"QCheckBox::indicator:checked {{ background-color: {color}; "
        f"border-color: {color}; image: url({check}); }}"
    )
    return cb


_SPEED_MIN = 25


_SPEED_MAX = 400


def _build_speed_row() -> tuple[QSlider, QLabel, QHBoxLayout]:
    """A horizontal speed slider (0.25x..4x) + live value readout.

    Returns (slider, value_label, row_layout) so callers can drop the row
    into a card and keep the reference labels."""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName("speed_slider")
    slider.setRange(_SPEED_MIN, _SPEED_MAX)
    slider.setValue(100)
    slider.setSingleStep(5)
    slider.setPageStep(25)
    slider.setTickPosition(QSlider.TicksBelow)
    slider.setTickInterval(50)
    slider.setCursor(QCursor(_HAND))
    val = QLabel("1\u00d7")
    val.setObjectName("speed_value")
    val.setMinimumWidth(48)
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: val.setText(_format_speed(v)))
    row = QHBoxLayout()
    row.setSpacing(8)
    lo = QLabel("0.25\u00d7")
    lo.setObjectName("speed_marker")
    hi = QLabel("4\u00d7")
    hi.setObjectName("speed_marker")
    row.addWidget(lo)
    row.addWidget(slider, stretch=1)
    row.addWidget(hi)
    row.addWidget(val)
    return slider, val, row


def _format_speed(value: int) -> str:
    """Render a slider value (percent) as e.g. '1.5x'."""
    return f"{value / 100:g}\u00d7"


def _read_speed(slider: QSlider) -> float | None:
    """Read the slider as a speed factor; None when it is 1.0x (no change)."""
    value = slider.value()
    return None if value == 100 else value / 100


class _FitScrollArea(QScrollArea):
    """QScrollArea whose sizeHint tracks its child, so the default window
    fits the page; smaller windows gracefully show a scrollbar instead of
    compressing the cards."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        child = self.widget()
        if child is not None:
            frame = 2 * self.frameWidth()
            return QSize(
                max(hint.width(), child.sizeHint().width() + frame),
                max(hint.height(), child.sizeHint().height() + frame),
            )
        return hint


# subtitle languages offered (key of downloader.SUBTITLE_LANGS, English name)
_SUB_LANGUAGES = (
    ("zh-Hant", "Traditional Chinese"), ("zh-Hans", "Simplified Chinese"), ("en", "English"),
    ("ja", "Japanese"), ("ko", "Korean"), ("es", "Spanish"), ("fr", "French"),
    ("de", "German"), ("pt", "Portuguese"), ("ru", "Russian"), ("id", "Indonesian"),
    ("vi", "Vietnamese"), ("th", "Thai"), ("ar", "Arabic"), ("hi", "Hindi"),
)


def _looks_like_url(text: str) -> bool:
    """A link (with or without http://) rather than words to search for."""
    text = text.strip()
    return bool(text) and " " not in text and ("://" in text or "." in text or "/" in text)


def _pick_summary(f: dict) -> str:
    if f["vcodec"]:
        return f"{f['height']}p {f['vcodec']}" if f["height"] else f["vcodec"]
    return f"{f['acodec'] or 'audio'}" + (f" {int(f['abr'])}k" if f["abr"] else "")


def _wrap_scroll(page: QWidget) -> QScrollArea:
    """Wrap a form page so it scrolls instead of collapsing on small windows."""
    scroll = _FitScrollArea()
    scroll.setObjectName("page_scroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(page)
    return scroll


def _build_filter(hflip: QCheckBox, vflip: QCheckBox) -> str | None:
    parts = []
    if hflip.isChecked():
        parts.append("hflip")
    if vflip.isChecked():
        parts.append("vflip")
    return ",".join(parts) or None
