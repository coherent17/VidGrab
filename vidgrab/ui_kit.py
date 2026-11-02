"""Small shared widgets / styles for the newer pages (Library, Tools, Subscriptions, Help)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QStringListModel,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
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


class _Relay(QObject):
    done = Signal(str, list)  # the text it was asked for, the suggestions


class _Fetch(QRunnable):
    def __init__(self, relay: _Relay, text: str, fn: Callable[[str], list[str]]) -> None:
        super().__init__()
        self._relay, self._text, self._fn = relay, text, fn

    def run(self) -> None:
        try:
            self._relay.done.emit(self._text, self._fn(self._text))
        except Exception:  # noqa: BLE001 - suggestions are a nicety, never an error
            self._relay.done.emit(self._text, [])


def attach_suggestions(box: QLineEdit, provider: Callable[[str], list[str]], *, min_chars: int = 2,
                       remote: Callable[[str], list[str]] | None = None,
                       on_pick: Callable[[str], None] | None = None,
                       merge: Callable[[list[str], list[str]], list[str]] | None = None,
                       delay_ms: int = 250) -> QCompleter:
    """Drop-down best matches under a line edit, open while typing.

    *provider(text)* gives the labels at once, ranked (the popup does not filter
    them). *remote(text)* — slow, e.g. a web request — runs on a worker thread after
    a pause of *delay_ms* and its answer is merged in with *merge(local, remote)*
    when it still matches what is typed. *on_pick(text)* runs when a suggestion is
    chosen (click, or Enter on a highlighted one)."""
    model = QStringListModel(box)
    completer = QCompleter(model, box)
    completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setMaxVisibleItems(8)
    box.setCompleter(completer)
    completer.popup().setStyleSheet("QListView::item { padding: 7px 12px; }")
    state: dict = {"local": [], "quiet": False}  # quiet: a choice was made, ignore late answers

    def show(items: list[str]) -> None:
        model.setStringList(items)
        if items and box.hasFocus():
            completer.setCompletionPrefix(box.text())
            completer.complete()  # open it now, not on the next key
        elif completer.popup() is not None:
            completer.popup().hide()

    def close() -> None:
        """The list is done with: hide it, drop answers still on their way."""
        state["quiet"] = True
        if remote is not None:
            timer.stop()
        completer.popup().hide()

    def refresh(text: str) -> None:
        state["quiet"] = False
        wanted = len(text.strip()) >= min_chars
        state["local"] = provider(text) if wanted else []
        show(state["local"])
        if remote is not None:
            timer.stop()
            if wanted:
                timer.start()

    box.textEdited.connect(refresh)
    if remote is not None:
        pool = QThreadPool(box)
        pool.setMaxThreadCount(2)
        relay = _Relay(box)
        timer = QTimer(box)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)
        timer.timeout.connect(lambda: pool.start(_Fetch(relay, box.text(), remote)))

        def arrived(text: str, items: list) -> None:
            if text == box.text() and items and not state["quiet"] and box.hasFocus():  # still what is typed
                show((merge or (lambda a, b: [*a, *b]))(state["local"], items))

        relay.done.connect(arrived)
    completer.activated[str].connect(lambda _t: close())  # before on_pick: it may start a search
    if on_pick is not None:
        completer.activated[str].connect(on_pick)
    box.returnPressed.connect(close)
    box.editingFinished.connect(close)  # Enter or the focus leaving
    return completer
