"""Small shared widgets / styles for the newer pages (Library, Tools, Subscriptions, Help)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QPushButton, QWidget


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


class Suggestions(QObject):
    """A drop-down list of best matches under a line edit.

    It is a plain child widget of the window, not a pop-up window: a pop-up that was
    hidden could stay painted on WSLg and swallow nothing, and could not be told from
    an open one. Keys: Down / Up move, Enter picks the marked line, Esc closes."""

    ROWS = 8
    dismissed = Signal()  # closed for good (a choice, Enter, Esc, focus left), not just emptied

    def __init__(self, box: QLineEdit, on_pick: Callable[[str], None] | None) -> None:
        super().__init__(box)
        self.box, self._on_pick = box, on_pick
        self.popup = QListWidget(box.window())
        self.popup.setObjectName("suggestPop")
        self.popup.setFocusPolicy(Qt.NoFocus)  # the box keeps the keyboard
        self.popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.popup.setStyleSheet("QListWidget#suggestPop::item { padding: 7px 12px; }")
        self.popup.hide()
        self.popup.itemClicked.connect(lambda it: self.pick(it.text()))
        box.installEventFilter(self)

    def show(self, items: list[str]) -> None:
        if not items or not self.box.hasFocus():
            self.close()
            return
        self.popup.clear()
        self.popup.addItems(items)
        row = self.popup.sizeHintForRow(0) or 30
        win = self.box.window()
        if self.popup.parent() is not win:
            self.popup.setParent(win)
        at = self.box.mapTo(win, self.box.rect().bottomLeft())
        self.popup.setGeometry(at.x(), at.y() + 2, self.box.width(), min(len(items), self.ROWS) * row + 6)
        self.popup.raise_()
        self.popup.show()

    def close(self) -> None:
        self.popup.hide()

    def dismiss(self) -> None:
        self.close()
        self.dismissed.emit()

    def pick(self, text: str) -> None:
        self.dismiss()
        self.box.setText(text)
        if self._on_pick is not None:
            self._on_pick(text)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.box:
            kind = event.type()
            if kind == QEvent.FocusOut or kind == QEvent.Hide:
                self.dismiss()
            elif kind == QEvent.KeyPress and self.popup.isVisible():
                key = event.key()
                n, row = self.popup.count(), self.popup.currentRow()
                if key in (Qt.Key_Down, Qt.Key_Up):
                    step = 1 if key == Qt.Key_Down else -1
                    self.popup.setCurrentRow((row + step) % n if row >= 0 else (0 if step > 0 else n - 1))
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter) and row >= 0:
                    self.pick(self.popup.item(row).text())
                    return True  # the choice is the search: Enter must not start a second one
                if key == Qt.Key_Escape:
                    self.dismiss()
                    return True
        return False


def attach_suggestions(box: QLineEdit, provider: Callable[[str], list[str]], *, min_chars: int = 2,
                       remote: Callable[[str], list[str]] | None = None,
                       on_pick: Callable[[str], None] | None = None,
                       merge: Callable[[list[str], list[str]], list[str]] | None = None,
                       delay_ms: int = 250) -> Suggestions:
    """Drop-down best matches under a line edit, open while typing (`box.suggestions`).

    *provider(text)* gives the labels at once, ranked. *remote(text)* — slow, e.g. a
    web request — runs on a worker thread after a pause of *delay_ms* and its answer
    is merged in with *merge(local, remote)* when it still matches what is typed.
    *on_pick(text)* runs when a suggestion is chosen (click, or Enter on a marked one)."""
    sug = Suggestions(box, on_pick)
    box.suggestions = sug  # type: ignore[attr-defined]
    state: dict = {"local": [], "quiet": False}  # quiet: closed, ignore late answers
    timer: QTimer | None = None

    def dismissed() -> None:
        state["quiet"] = True
        if timer is not None:
            timer.stop()

    def refresh(text: str) -> None:
        state["quiet"] = False
        wanted = len(text.strip()) >= min_chars
        state["local"] = provider(text) if wanted else []
        sug.show(state["local"])
        if timer is not None:
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
            if text == box.text() and items and not state["quiet"]:  # still what is typed
                sug.show((merge or (lambda a, b: [*a, *b]))(state["local"], items))

        relay.done.connect(arrived)
    sug.dismissed.connect(dismissed)
    box.returnPressed.connect(sug.dismiss)
    box.editingFinished.connect(sug.dismiss)  # Enter or the focus leaving
    return sug
