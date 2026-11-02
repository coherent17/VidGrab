"""Small shared widgets / styles for the newer pages (Library, Tools, Subscriptions, Help)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLineEdit, QPushButton, QWidget


def rgba(color: str, alpha: float) -> str:
    """A stylesheet colour with transparency (Qt reads #RRGGBBAA as #AARRGGBB)."""
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(alpha * 255)})"


def card_css(p: dict[str, str], name: str) -> str:
    return (f"QFrame#{name} {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']}; border-radius:14px; }}")


def chip_css(p: dict[str, str]) -> str:
    return (f"QPushButton#chip {{ background:{p['SURFACE']}; color:{p['TEXT_DIM']}; border:1px solid {p['BORDER']};"
            " border-radius:15px; padding:6px 16px; font-size:13px; }"
            f"QPushButton#chip:hover {{ color:{p['TEXT']}; border-color:{p['ACCENT_HI']}; }}"
            f"QPushButton#chip:checked {{ color:#ffffff; background:{p['ACCENT']}; border-color:{p['ACCENT']}; }}")


class Chips(QWidget):
    """A row of exclusive pill buttons; `changed(key)` when another is picked."""

    changed = Signal(str)

    def __init__(self, keys: list[str]) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.buttons: dict[str, QPushButton] = {}
        for k in keys:
            b = QPushButton()
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, key=k: self.changed.emit(key))
            lay.addWidget(b)
            self.buttons[k] = b
        lay.addStretch()
        self.buttons[keys[0]].setChecked(True)

    def current(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())

    def set_current(self, key: str) -> None:
        self.buttons[key].setChecked(True)


def attach_suggestions(box: QLineEdit, provider: Callable[[str], list[str]], *, min_chars: int = 2) -> QCompleter:
    """Drop-down best matches under a line edit. *provider(text)* returns the
    labels in the order to show (already ranked: the popup does not filter them)."""
    model = QStringListModel(box)
    completer = QCompleter(model, box)
    completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setMaxVisibleItems(8)
    box.setCompleter(completer)
    completer.popup().setStyleSheet("QListView::item { padding: 7px 12px; }")

    def refresh(text: str) -> None:
        items = provider(text) if len(text.strip()) >= min_chars else []
        model.setStringList(items)
        if items and box.hasFocus():
            completer.setCompletionPrefix(text)
            completer.complete()  # open it now, not on the next key
        elif completer.popup() is not None:
            completer.popup().hide()

    box.textEdited.connect(refresh)
    return completer
