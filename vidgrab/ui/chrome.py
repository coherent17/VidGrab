"""Sidebar, page stack, wheel guard and the page list."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCursor,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QLabel,
    QMenu,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__
from vidgrab.ui.drawing import _HAND, _brand_pixmap, _icon
from vidgrab.ui.theme import _PALETTES

_NAV_ITEMS: list[tuple[str, str]] = [
    ("download", "Download"),
    ("film", "Studio"),
    ("folder", "Library"),
    ("tools", "Tools"),
    ("rss", "Channels"),
    ("gear", "Settings"),
    ("help", "Help"),
]


# page index -> (title key, subtitle key) for the header above each page
_PAGE_HEADERS: list[tuple[str, str]] = [
    ("Download", "Grab videos, playlists and music from YouTube and other sites"),
    ("Studio", "Join clips, add subtitles and background music"),
    ("Library", "Everything you have downloaded and made"),
    ("Tools", "Shorts, shrink, convert, GIF, thumbnails and audio in one click"),
    ("Channels", "Follow channels and grab their new videos"),
    ("Settings", "Appearance, language and app info"),
    ("Help", "How to use each feature, and answers to common questions"),
]


(PAGE_DOWNLOAD, PAGE_STUDIO, PAGE_LIBRARY, PAGE_TOOLS, PAGE_SUBS, PAGE_SETTINGS,
 PAGE_HELP) = range(7)


_THUMB_SIZE = QSize(320, 180)


class _Sidebar(QWidget):
    """Compact navigation rail: logo, then icon-over-label page buttons."""

    page_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(84)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 14, 8, 12)
        lay.setSpacing(6)

        icon = QLabel()
        icon.setObjectName("brand_icon")
        icon.setAlignment(Qt.AlignCenter)
        pm = _brand_pixmap(40)
        if pm:
            icon.setPixmap(pm)
        icon.setToolTip(f"VidGrab v{__version__}")
        lay.addWidget(icon)
        divider = QFrame()
        divider.setObjectName("brand_divider")
        divider.setFrameShape(QFrame.NoFrame)
        lay.addWidget(divider)
        lay.addSpacing(6)

        self._buttons: list[QToolButton] = []
        for idx, (_kind, _key) in enumerate(_NAV_ITEMS):
            btn = QToolButton()
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(68, 62)
            btn.setCursor(QCursor(_HAND))
            if idx == 0:
                btn.setChecked(True)
            btn.toggled.connect(
                lambda checked, i=idx: self.page_changed.emit(i) if checked else None
            )
            lay.addWidget(btn, alignment=Qt.AlignHCenter)
            self._buttons.append(btn)

        lay.addStretch()
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("sidebar_foot")
        ver.setAlignment(Qt.AlignCenter)
        lay.addWidget(ver)

    def retranslate(self, t, theme: str = "dark") -> None:
        pal = _PALETTES[theme]
        for btn, (kind, key) in zip(self._buttons, _NAV_ITEMS):
            if btn.isChecked():
                color = pal["ACCENT_HI"] if theme == "dark" else pal["ACCENT"]
            else:
                color = pal["TEXT_MUTED"]
            btn.setIcon(_icon(kind, color, 24))
            btn.setText(t(key))
            btn.setToolTip(
                t(
                    {
                        "download": "tooltip_page_download",
                        "film": "tooltip_page_studio",
                        "folder": "tooltip_page_library",
                        "tools": "tooltip_page_tools",
                        "rss": "tooltip_page_subscriptions",
                        "gear": "tooltip_page_settings",
                        "help": "tooltip_page_help",
                    }[kind]
                )
            )

    def select(self, idx: int) -> None:
        self._buttons[idx].setChecked(True)


class _FadeStack(QStackedWidget):
    """QStackedWidget for the main pages: the new page slides up a few pixels as it appears.

    Only the page's *position* is animated. A per-page opacity fade was removed on purpose:
    a QGraphicsOpacityEffect over the stack forces a software compositing pass that can draw
    all pages on top of one another (and destroy performance) on systems with broken GL."""

    SLIDE_PX = 14
    SLIDE_MS = 170

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # not under test / scripts (offscreen), where a page should simply be where it is
        self.slide_enabled = QApplication.platformName() != "offscreen"
        self._anim: QPropertyAnimation | None = None

    def setCurrentIndex(self, idx: int) -> None:
        before = self.currentIndex()
        super().setCurrentIndex(idx)
        page = self.currentWidget()
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if page is None:
            return
        page.move(0, 0)
        if not self.slide_enabled or idx == before or not self.isVisible() or before < 0:
            return
        anim = QPropertyAnimation(page, b"pos", self)
        anim.setDuration(self.SLIDE_MS)
        anim.setStartValue(QPoint(0, self.SLIDE_PX))
        anim.setEndValue(QPoint(0, 0))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda w=page: w.move(0, 0))  # always end exactly in place
        self._anim = anim
        anim.start()


class _WheelGuard(QObject):
    """The mouse wheel never changes a dropdown, number box or slider — it
    scrolls the panel underneath instead (no accidental edits while scrolling).
    It also repaints the window once a drop-down list or menu has closed: on WSLg a
    closed pop-up can stay drawn over the page."""

    _KINDS = (QComboBox, QAbstractSpinBox, QSlider)

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Wheel and isinstance(obj, self._KINDS):
            event.ignore()  # handled here, but unaccepted: Qt passes it to the parent
            return True
        if kind == QEvent.Hide and isinstance(obj, QWidget) and obj.isWindow() \
                and (isinstance(obj, QMenu) or obj.metaObject().className() == "QComboBoxPrivateContainer"):
            QTimer.singleShot(0, self._repaint)
            QTimer.singleShot(120, self._repaint)
        return False

    @staticmethod
    def _repaint() -> None:
        win = QApplication.activeWindow()
        if win is not None:
            win.update()
            win.repaint()


_wheel_guard: _WheelGuard | None = None


def _install_wheel_guard() -> None:
    global _wheel_guard
    app = QApplication.instance()
    if app is not None and _wheel_guard is None:
        _wheel_guard = _WheelGuard(app)
        app.installEventFilter(_wheel_guard)
