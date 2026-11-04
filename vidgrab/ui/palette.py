"""Command palette (Ctrl+K): type a few letters, press Enter, and go there or do it."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vidgrab.core.fuzzy import FuzzyIndex

Command = tuple[str, Callable[[], None]]  # label shown, what to run


class CommandPalette(QDialog):
    """A small pop-up over the top middle of the window. Esc or a click elsewhere closes it."""

    def __init__(self, parent: QWidget, commands: list[Command], placeholder: str) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("palette")
        self._commands = commands
        self._index = FuzzyIndex()
        for n, (label, _run) in enumerate(commands):
            self._index.add(n, label, (label, 1.0))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.box = QLineEdit()
        self.box.setPlaceholderText(placeholder)
        self.box.setMinimumHeight(40)
        self.box.textChanged.connect(self._fill)
        self.box.installEventFilter(self)
        lay.addWidget(self.box)
        self.list = QListWidget()
        self.list.setObjectName("pal_list")
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemClicked.connect(lambda it: self._run(it))
        lay.addWidget(self.list)
        self.setFixedWidth(520)
        self._fill("")

    def _fill(self, text: str) -> None:
        self.list.clear()
        if text.strip():
            hits = [k for k, _score in self._index.search(text, limit=9)]
        else:
            hits = list(range(min(len(self._commands), 9)))
        for n in hits:
            item = QListWidgetItem(self._commands[n][0])
            item.setData(Qt.UserRole, n)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setFixedHeight(min(max(self.list.count(), 1), 9) * 36 + 8)
        self.adjustSize()

    def popup(self) -> None:
        w = self.parentWidget()
        if w is not None:
            self.move(w.mapToGlobal(w.rect().topLeft()).x() + (w.width() - self.width()) // 2,
                      w.mapToGlobal(w.rect().topLeft()).y() + 90)
        self.show()
        self.box.setFocus()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.box and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
                step = 1 if key == Qt.Key_Down else -1
                self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem() is not None:
                    self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, event)

    def _run(self, item: QListWidgetItem) -> None:
        run = self._commands[item.data(Qt.UserRole)][1]
        self.close()
        run()
