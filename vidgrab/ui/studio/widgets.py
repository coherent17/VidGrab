"""Small Studio widgets."""
from __future__ import annotations

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from vidgrab.ui.studio.common import _HAND


def _swatch(color: str | None, size: int = 16) -> QIcon:
    """Colour square (checkerboard + red slash for 'none')."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    box = QRectF(1, 1, size - 2, size - 2)
    if color:
        p.setBrush(QColor(color))
        p.setPen(QPen(QColor("#808080"), 1))
        p.drawRoundedRect(box, 4, 4)
    else:
        path = QPainterPath()
        path.addRoundedRect(box, 4, 4)
        p.setClipPath(path)
        cell = size / 4
        for i in range(4):
            for j in range(4):
                p.fillRect(QRectF(i * cell, j * cell, cell, cell),
                           QColor("#cccccc") if (i + j) % 2 else QColor("#ffffff"))
        p.setClipping(False)
        p.setPen(QPen(QColor("#ef4444"), 2))
        p.drawLine(QPointF(3, size - 3), QPointF(size - 3, 3))
    p.end()
    return QIcon(pm)


class ColorSwatches(QWidget):
    """A row of clickable colour squares (+ 'none' and a custom colour picker)
    — every choice visible at once, no dropdown."""

    changed = Signal(str)  # "#RRGGBB", or "" for none

    SIZE = 28

    def __init__(self, colors: list[tuple[str, str]], *, allow_none: bool, t,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._t = t
        self._presets = colors
        self._allow_none = allow_none
        self._custom: str | None = None
        self._value = "" if allow_none else colors[0][1]
        self._buttons: dict[str, QPushButton] = {}
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(5)
        self._accent = "#7c5cff"
        self._rebuild()

    def _make(self, color: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("swatch")
        b.setCheckable(True)
        b.setFixedSize(self.SIZE, self.SIZE)
        b.setIconSize(QSize(self.SIZE - 8, self.SIZE - 8))
        b.setIcon(_swatch(color or None, self.SIZE - 8))
        b.setToolTip(tip)
        b.setCursor(QCursor(_HAND))
        b.clicked.connect(lambda _c=False, v=color: self._pick(v))
        return b

    def _rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons = {}
        entries = ([("", self._t("None (transparent)"))] if self._allow_none else []) + \
            [(c, self._t(k)) for k, c in self._presets]
        if self._custom and all(self._custom != c for c, _k in entries):
            entries.append((self._custom, self._custom))
        for color, tip in entries:
            b = self._make(color, tip)
            self._buttons[color] = b
            self._lay.addWidget(b)
        more = QPushButton("+")
        more.setObjectName("swatch_add")
        more.setFixedSize(self.SIZE, self.SIZE)
        more.setToolTip(self._t("Custom\u2026"))
        more.setCursor(QCursor(_HAND))
        more.clicked.connect(self._pick_custom)
        self._lay.addWidget(more)
        self._lay.addStretch()
        self._sync()

    def retranslate(self) -> None:
        self._rebuild()

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.setStyleSheet(
            f"QPushButton#swatch {{ border: 2px solid transparent; border-radius: 7px;"
            f" padding: 0; background: transparent; }}"
            f"QPushButton#swatch:hover {{ border-color: {color}80; }}"
            f"QPushButton#swatch:checked {{ border-color: {color}; }}"
            f"QPushButton#swatch_add {{ border: 1px dashed {color}; border-radius: 7px;"
            f" padding: 0; background: transparent; color: {color}; font-size: 17px;"
            f" font-weight: 600; }}"
            f"QPushButton#swatch_add:hover {{ background: {color}33; }}")

    def _sync(self) -> None:
        for color, b in self._buttons.items():
            b.setChecked(color == self._value)

    def color(self) -> str:
        return self._value

    def set_color(self, color: str | None) -> None:
        """Select *color* without emitting `changed` (adds it if it's custom)."""
        color = (color or "").upper() if color else ""
        if not color and not self._allow_none:
            color = self._presets[0][1]
        if color not in self._buttons:
            self._custom = color
            self._rebuild()
        self._value = color
        self._sync()

    def _pick(self, color: str) -> None:
        self._value = color
        self._sync()
        self.changed.emit(color)

    def _pick_custom(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._value or "#FFFFFF"), self,
                                       self._t("Custom\u2026"))
        if chosen.isValid():
            self.set_color(chosen.name().upper())
            self.changed.emit(self._value)
        else:
            self._sync()
