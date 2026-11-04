"""Icons and pictures drawn in code."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)

from vidgrab.core.downloader import (
    asset_roots,
    get_app_dir,
)
from vidgrab.i18n import FLAGS
from vidgrab.ui.config import _config_dir
from vidgrab.ui.theme import _PALETTES

_HAND = Qt.PointingHandCursor


def _icon(kind: str, color: str = "#8b93ab", size: int = 18) -> QIcon:
    """Draw a simple vector icon for buttons."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)

    m = size  # alias
    if kind == "download":
        cx = m / 2
        p.drawLine(int(cx), 2, int(cx), m - 7)
        p.drawLine(int(cx) - 4, m - 11, int(cx), m - 7)
        p.drawLine(int(cx) + 4, m - 11, int(cx), m - 7)
        p.drawLine(4, m - 3, m - 4, m - 3)
    elif kind == "scissors":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.drawEllipse(int(cx - r - 1), int(cy - r), 6, 6)
        p.drawEllipse(int(cx + r - 5), int(cy - r), 6, 6)
        p.drawLine(int(cx), int(cy - r + 6), int(cx), int(cy + r))
    elif kind == "gear":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + (r - 1) * math.cos(rad)
            y1 = cy + (r - 1) * math.sin(rad)
            x2 = cx + (r + 2) * math.cos(rad)
            y2 = cy + (r + 2) * math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
    elif kind == "tools":  # sliders: two lines with a knob each
        for y, x in ((m // 3, m // 3), (2 * m // 3, 2 * m // 3 + 1)):
            p.drawLine(3, y, m - 3, y)
            p.setBrush(QColor(color))
            p.drawEllipse(x - 2, y - 2, 5, 5)
    elif kind == "rss":  # a feed: dot and two waves
        p.setBrush(QColor(color))
        p.drawEllipse(3, m - 6, 4, 4)
        p.setBrush(Qt.NoBrush)
        p.drawArc(3 - m // 2, m // 2, m, m, 0, 90 * 16)
        p.drawArc(3 - m + 3, 3, m * 2 - 6, m * 2 - 6, 0, 90 * 16)
    elif kind == "help":
        p.drawEllipse(2, 2, m - 4, m - 4)
        f = p.font()
        f.setBold(True)
        f.setPixelSize(int(m * 0.62))
        p.setFont(f)
        p.drawText(QRectF(0, 0, m, m), Qt.AlignCenter, "?")
    elif kind == "film":
        p.drawRoundedRect(3, 3, m - 6, m - 6, 2, 2)
        p.drawLine(7, 3, 7, m - 3)
        p.drawLine(m - 7, 3, m - 7, m - 3)
        p.drawLine(3, m // 2, 7, m // 2)
        p.drawLine(m - 7, m // 2, m - 3, m // 2)
    elif kind == "music":
        p.drawLine(7, m - 5, 7, 4)
        p.drawLine(7, 4, m - 3, 2)
        p.drawLine(m - 3, 2, m - 3, m - 7)
        p.setBrush(QColor(color))
        p.drawEllipse(2, m - 7, 5, 4)
        p.drawEllipse(m - 8, m - 9, 5, 4)
    elif kind == "captions":
        p.drawRoundedRect(2, 4, m - 4, m - 8, 3, 3)
        p.drawLine(5, m // 2 - 1, m // 2 - 1, m // 2 - 1)
        p.drawLine(m // 2 + 2, m // 2 - 1, m - 5, m // 2 - 1)
        p.drawLine(5, m // 2 + 3, m - 8, m // 2 + 3)
    elif kind == "clipboard":
        p.drawLine(6, 4, m - 6, 4)
        p.drawLine(6, m - 3, m - 6, m - 3)
        p.drawLine(6, 4, 6, m - 3)
        p.drawLine(m - 6, 4, m - 6, m - 3)
        p.drawLine(8, 7, m - 8, 7)
        p.drawLine(8, 10, m - 8, 10)
        p.drawLine(8, 13, m - 11, 13)
    elif kind == "folder":
        p.drawLine(3, 6, 3, m - 3)
        p.drawLine(m - 3, 6, m - 3, m - 3)
        p.drawLine(3, m - 3, m - 3, m - 3)
        p.drawLine(3, 6, 8, 6)
        p.drawLine(8, 3, 8, 6)
        p.drawLine(8, 6, m - 3, 6)
    elif kind == "trash":
        p.drawLine(5, 4, m - 5, 4)
        p.drawLine(5, 4, 5, m - 3)
        p.drawLine(m - 5, 4, m - 5, m - 3)
        p.drawLine(3, 4, m - 3, 4)
        p.drawLine(8, 7, 8, m - 5)
        p.drawLine(m // 2, 7, m // 2, m - 5)
        p.drawLine(m - 8, 7, m - 8, m - 5)
        p.drawLine(4, 7, m - 4, 7)
    elif kind == "sun":
        cx, cy = m / 2, m / 2
        r = m // 4
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + (r + 2) * math.cos(rad)
            y1 = cy + (r + 2) * math.sin(rad)
            x2 = cx + (r + 5) * math.cos(rad)
            y2 = cy + (r + 5) * math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
    elif kind == "moon":
        cx, cy = m / 2, m / 2
        r = m // 3
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.setCompositionMode(QPainter.CompositionMode_Source)
        cover = r + 1
        p.drawEllipse(int(cx - r + 3), int(cy - r - 2), cover * 2, cover * 2)

    p.end()
    return QIcon(pm)


def _checkmark_path() -> str:
    """Return (generating if needed) a white checkmark PNG for checkbox tips."""
    d = _config_dir()
    p = d / "check.png"
    if not p.is_file():
        try:
            d.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            qp = QPainter(pix)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setPen(
                QPen(
                    QColor("#ffffff"), 2.4, Qt.SolidLine,
                    Qt.RoundCap, Qt.RoundJoin,
                )
            )
            qp.drawLine(4, 11, 8, 15)
            qp.drawLine(8, 15, 16, 5)
            qp.end()
            pix.save(str(p), "PNG")
        except Exception:  # noqa: BLE001 - fall back to no image
            return ""
    return p.as_posix()


def _qpalette(theme: str) -> QPalette:
    """Qt palette matching *theme*, for widgets the stylesheet doesn't fully
    cover — notably Qt's own file dialog and message boxes."""
    c = {k: QColor(v) for k, v in _PALETTES[theme].items()}
    pal = QPalette()
    for role, key in (
        (QPalette.Window, "SURFACE"),
        (QPalette.WindowText, "TEXT"),
        (QPalette.Base, "FIELD"),
        (QPalette.AlternateBase, "SURFACE"),
        (QPalette.Text, "TEXT"),
        (QPalette.Button, "SURFACE_HI"),
        (QPalette.ButtonText, "TEXT"),
        (QPalette.ToolTipBase, "SURFACE_HI"),
        (QPalette.ToolTipText, "TEXT"),
        (QPalette.PlaceholderText, "TEXT_MUTED"),
        (QPalette.Highlight, "ACCENT"),
        (QPalette.Link, "ACCENT2"),
        (QPalette.Mid, "BORDER"),
        (QPalette.Midlight, "BORDER_HI"),
    ):
        pal.setColor(role, c[key])
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c["DISABLED_TEXT"])
    return pal


def _chevron_path(color: str, *, down: bool) -> str:
    """Return (generating if needed) a small chevron PNG for combo/spin arrows."""
    d = _config_dir()
    p = d / f"chevron_{'down' if down else 'up'}_{color.lstrip('#')}.png"
    if not p.is_file():
        try:
            d.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(12, 8)
            pix.fill(Qt.transparent)
            qp = QPainter(pix)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setPen(QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if down:
                qp.drawLine(2, 2, 6, 6)
                qp.drawLine(6, 6, 10, 2)
            else:
                qp.drawLine(2, 6, 6, 2)
                qp.drawLine(6, 2, 10, 6)
            qp.end()
            pix.save(str(p), "PNG")
        except Exception:  # noqa: BLE001 - fall back to no image
            return ""
    return p.as_posix()


def _asset(*parts: str) -> Path:
    """An asset file: in the bundle, the checkout or the installed package."""
    for root in asset_roots():
        p = root.joinpath("assets", *parts)
        if p.is_file():
            return p
    return get_app_dir().joinpath("assets", *parts)


def _icon_path() -> Path:
    return _asset("icon.png")


def _flag_icon(lang_code: str) -> QIcon:
    """Bundled color flag icon for a language code (PNG, not emoji)."""
    cc = FLAGS.get(lang_code, "us")
    p = _asset("flags", f"{cc}.png")
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _app_icon() -> QIcon:
    p = _icon_path()
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _brand_pixmap(size: int = 30) -> QPixmap | None:
    """Sidebar logo at a fixed render size (None if the asset is missing)."""
    pm = QPixmap(str(_icon_path()))
    if pm.isNull():
        return None
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
