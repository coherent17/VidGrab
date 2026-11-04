"""Toast notifications: small messages that slide in at the bottom right, fade out by
themselves and never block the window (a modal box is for decisions, not for "done")."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

KINDS = {"ok": "#10b981", "error": "#ef4444", "info": "#7c5cff"}
MARGIN = 18  # from the window's edge
GAP = 10  # between two toasts
LINGER_MS = {"ok": 6000, "info": 6000, "error": 12000}


class Toast(QFrame):
    """One message: a coloured edge, the text, an optional action button and a close button."""

    def __init__(self, parent: QWidget, text: str, kind: str, action: tuple[str, Callable[[], None]] | None,
                 palette: dict[str, str]) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.kind = kind if kind in KINDS else "info"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 8, 10)
        lay.setSpacing(10)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        width = self.label.fontMetrics().horizontalAdvance(text) + 24  # as wide as the text, up to a limit
        self.label.setFixedWidth(max(200, min(width, 380)))
        lay.addWidget(self.label, 1)
        self.action_btn: QPushButton | None = None
        if action:
            self.action_btn = QPushButton(action[0])
            self.action_btn.setObjectName("toast_action")
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.clicked.connect(lambda: (action[1](), self.close_now()))
            lay.addWidget(self.action_btn)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("toast_close")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.clicked.connect(self.close_now)
        lay.addWidget(self.close_btn)
        self.apply_theme(palette)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close_now)
        self.closed = False

    def apply_theme(self, p: dict[str, str]) -> None:
        edge = KINDS[self.kind]
        self.setStyleSheet(
            f"QFrame#toast {{ background:{p['POPUP']}; border:1px solid {p['EDGE']}; border-left:4px solid {edge};"
            f" border-radius:12px; }}"
            f"QFrame#toast QLabel {{ color:{p['TEXT']}; background:transparent; font-size:13px; }}"
            f"QPushButton#toast_action {{ background:transparent; color:{edge}; border:1px solid {edge};"
            f" border-radius:8px; padding:5px 12px; font-weight:700; }}"
            f"QPushButton#toast_action:hover {{ background:{edge}; color:#ffffff; }}"
            f"QPushButton#toast_close {{ background:transparent; color:{p['TEXT_MUTED']}; border:none;"
            f" border-radius:12px; padding:0; }}"
            f"QPushButton#toast_close:hover {{ background:{p['SURFACE_HI']}; color:{p['TEXT']}; }}")

    def _fade(self, to: float, ms: int, then: Callable[[], None] | None = None) -> None:
        anim = QPropertyAnimation(self._fx, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(self._fx.opacity())
        anim.setEndValue(to)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        if then:
            anim.finished.connect(then)
        self._anim = anim
        anim.start()

    def pop_in(self) -> None:
        self.show()
        self.raise_()
        self._fade(1.0, 180)
        self._timer.start(LINGER_MS[self.kind])

    def enterEvent(self, event) -> None:
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._timer.start(2500)
        super().leaveEvent(event)

    def close_now(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._timer.stop()
        self._fade(0.0, 140, lambda: (self.hide(), self.deleteLater(), self.gone()))

    def gone(self) -> None:  # replaced by the host
        pass


class ToastHost(QObject):
    """Keeps the toasts of one window stacked at its bottom right corner."""

    MAX = 4

    def __init__(self, window: QWidget, palette: dict[str, str]) -> None:
        super().__init__(window)
        self._window = window
        self._palette = palette
        self._toasts: list[Toast] = []
        window.installEventFilter(self)

    def apply_theme(self, palette: dict[str, str]) -> None:
        self._palette = palette
        for t in self._toasts:
            t.apply_theme(palette)

    def show(self, text: str, kind: str = "ok", action: tuple[str, Callable[[], None]] | None = None) -> Toast:
        # the same message twice in a row is one toast, not two
        for t in self._toasts:
            if not t.closed and t.label.text() == text:
                t.pop_in()
                return t
        toast = Toast(self._window, text, kind, action, self._palette)
        toast.gone = lambda t=toast: self._forget(t)  # type: ignore[method-assign]
        self._toasts.append(toast)
        while len([t for t in self._toasts if not t.closed]) > self.MAX:
            next(t for t in self._toasts if not t.closed).close_now()
        toast.adjustSize()
        self.layout_toasts()
        toast.pop_in()
        return toast

    def active(self) -> list[Toast]:
        return [t for t in self._toasts if not t.closed]

    def _forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self.layout_toasts()

    def layout_toasts(self) -> None:
        w = self._window
        bottom = w.height() - MARGIN - (w.statusBar().height() if hasattr(w, "statusBar") else 0)
        for t in reversed([t for t in self._toasts if not t.closed]):
            t.adjustSize()
            t.move(w.width() - t.width() - MARGIN, bottom - t.height())
            t.raise_()
            bottom -= t.height() + GAP

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() == QEvent.Resize:
            self.layout_toasts()
        return False
