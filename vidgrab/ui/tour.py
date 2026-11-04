"""First-run tour: a small card beside the sidebar that walks through the main pages, one
step at a time. It rings the page's button, shows the page, says what it is for, and can
be skipped at any moment. (Also started by the command palette: "Take the tour".)"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

Step = tuple[int, str, str]  # page index, title, text (already translated)


class _Ring(QFrame):
    """An accent outline drawn over the sidebar button of the current step."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def apply_theme(self, p: dict[str, str]) -> None:
        self.setStyleSheet(f"QFrame {{ border:2px solid {p['ACCENT_HI']}; border-radius:12px; background:transparent; }}")


class Tour(QObject):
    def __init__(self, window: QWidget, steps: Callable[[], list[Step]], labels: Callable[[], dict[str, str]],
                 go_to: Callable[[int], None], target: Callable[[int], QWidget | None],
                 palette: dict[str, str], done: Callable[[], None]) -> None:
        super().__init__(window)
        self._window, self._steps_fn, self._labels_fn = window, steps, labels
        self._go_to, self._target, self._done = go_to, target, done
        self._palette = palette
        self._steps: list[Step] = []
        self._i = 0
        self.card = QFrame(window)
        self.card.setObjectName("tour_card")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.card.setFixedWidth(340)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        self.count = QLabel()
        self.count.setObjectName("tour_count")
        self.title = QLabel()
        self.title.setObjectName("tour_title")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        for w in (self.count, self.title, self.text):
            lay.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.skip_btn = QPushButton()
        self.skip_btn.setObjectName("tour_skip")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(self.finish)
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("primary")
        self.next_btn.setProperty("compact", True)
        self.next_btn.setMinimumHeight(34)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self.next)
        row.addWidget(self.skip_btn)
        row.addStretch()
        row.addWidget(self.next_btn)
        lay.addLayout(row)
        self.ring = _Ring(window)
        self.card.hide()
        window.installEventFilter(self)
        self.apply_theme(palette)

    def apply_theme(self, p: dict[str, str]) -> None:
        self._palette = p
        self.ring.apply_theme(p)
        self.card.setStyleSheet(
            f"QFrame#tour_card {{ background:{p['POPUP']}; border:1px solid {p['EDGE']}; border-radius:14px; }}"
            f"QFrame#tour_card QLabel {{ color:{p['TEXT_DIM']}; background:transparent; font-size:13px; }}"
            f"QLabel#tour_title {{ color:{p['TEXT']}; font-size:17px; font-weight:800; }}"
            f"QLabel#tour_count {{ color:{p['TEXT_MUTED']}; font-size:11px; font-weight:700; letter-spacing:1px; }}"
            f"QPushButton#tour_skip {{ background:transparent; border:none; color:{p['TEXT_MUTED']}; padding:6px 4px; }}"
            f"QPushButton#tour_skip:hover {{ color:{p['TEXT']}; }}")

    def active(self) -> bool:
        return self.card.isVisible()

    def start(self) -> None:
        self._steps = self._steps_fn()
        self._i = 0
        if self._steps:
            self._show_step()

    def next(self) -> None:
        if self._i + 1 >= len(self._steps):
            self.finish()
            return
        self._i += 1
        self._show_step()

    def finish(self) -> None:
        self.card.hide()
        self.ring.hide()
        self._done()

    def _show_step(self) -> None:
        page, title, text = self._steps[self._i]
        labels = self._labels_fn()
        self._go_to(page)
        self.count.setText(f"{self._i + 1} / {len(self._steps)}")
        self.title.setText(title)
        self.text.setText(text)
        last = self._i + 1 == len(self._steps)
        self.next_btn.setText(labels["done"] if last else labels["next"])
        self.skip_btn.setText(labels["skip"])
        self.card.show()
        self.card.raise_()
        self._place()

    def _place(self) -> None:
        if not self.card.isVisible():
            return
        target = self._target(self._steps[self._i][0])
        lay = self.card.layout()
        lay.activate()
        self.card.setFixedHeight(lay.totalHeightForWidth(self.card.width()))  # wrapped lines need their room
        if target is None:
            return
        tl = target.mapTo(self._window, target.rect().topLeft())
        self.ring.setGeometry(tl.x() - 3, tl.y() - 3, target.width() + 6, target.height() + 6)
        self.ring.show()
        self.ring.raise_()
        x = tl.x() + target.width() + 16
        y = min(max(tl.y() - 10, 8), max(self._window.height() - self.card.height() - 40, 8))
        self.card.move(x, y)
        self.card.raise_()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() == QEvent.Resize:
            self._place()
        return False
