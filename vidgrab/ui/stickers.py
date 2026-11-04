"""A small pack of stickers drawn in code (no image files to ship, nothing to license):
arrow, ring, star, heart, speech bubble, check, cross and sparkle, on transparent
512 px squares. They are ordinary PNGs once written, so the Studio treats them like
any picture the user adds."""
from __future__ import annotations

from math import cos, pi, sin
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

SIZE = 512
NAMES = ("arrow", "ring", "star", "heart", "bubble", "check", "cross", "sparkle")
_LABELS = {"arrow": "Arrow", "ring": "Ring", "star": "Star", "heart": "Heart", "bubble": "Speech bubble",
           "check": "Check mark", "cross": "Cross", "sparkle": "Sparkle"}
_COLORS = {"arrow": "#FF3B30", "ring": "#FFD400", "star": "#FFD400", "heart": "#FF2D55", "bubble": "#FFFFFF",
           "check": "#34C759", "cross": "#FF3B30", "sparkle": "#FFFFFF"}


def label(name: str) -> str:
    return _LABELS[name]


def _outline(p: QPainter, path: QPainterPath, fill: str) -> None:
    p.setPen(QPen(QColor(0, 0, 0, 200), 18, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor(fill))
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.drawPath(path)


def _star(n: int, outer: float, inner: float, cx: float, cy: float) -> QPainterPath:
    pts = QPolygonF()
    for k in range(n * 2):
        r = outer if k % 2 == 0 else inner
        a = -pi / 2 + k * pi / n
        pts.append(QPointF(cx + r * cos(a), cy + r * sin(a)))
    path = QPainterPath()
    path.addPolygon(pts)
    path.closeSubpath()
    return path


def draw(name: str) -> QImage:
    """The sticker *name* as a transparent SIZE x SIZE image."""
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    c, color = SIZE / 2, _COLORS[name]
    path = QPainterPath()
    if name == "arrow":  # pointing right, like "look here"
        path.addPolygon(QPolygonF([QPointF(40, 190), QPointF(280, 190), QPointF(280, 90), QPointF(472, 256),
                                   QPointF(280, 422), QPointF(280, 322), QPointF(40, 322)]))
        path.closeSubpath()
        _outline(p, path, color)
    elif name == "ring":  # a highlight circle: only an edge
        p.setPen(QPen(QColor(0, 0, 0, 200), 50, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(56, 56, SIZE - 112, SIZE - 112))
        p.setPen(QPen(QColor(color), 30, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(QRectF(56, 56, SIZE - 112, SIZE - 112))
    elif name == "star":
        _outline(p, _star(5, 224, 96, c, c + 12), color)
    elif name == "heart":
        path.moveTo(c, 456)
        path.cubicTo(-60, 290, 70, 40, c, 170)
        path.cubicTo(SIZE - 70, 40, SIZE + 60, 290, c, 456)
        path.closeSubpath()
        _outline(p, path, color)
    elif name == "bubble":
        path.addRoundedRect(QRectF(36, 60, SIZE - 72, 304), 70, 70)
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(130, 340), QPointF(110, 460), QPointF(250, 350)]))
        tail.closeSubpath()
        _outline(p, path.united(tail), color)
    elif name == "check":
        p.setPen(QPen(QColor(0, 0, 0, 200), 96, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pts = [QPointF(92, 268), QPointF(206, 382), QPointF(424, 130)]
        p.drawPolyline(QPolygonF(pts))
        p.setPen(QPen(QColor(color), 66, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF(pts))
    elif name == "cross":
        for width, col in ((96, QColor(0, 0, 0, 200)), (66, QColor(color))):
            p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(110, 110), QPointF(402, 402))
            p.drawLine(QPointF(402, 110), QPointF(110, 402))
    else:  # sparkle: a four-pointed shine
        path.moveTo(c, 30)
        path.quadTo(c + 24, c - 24, SIZE - 30, c)
        path.quadTo(c + 24, c + 24, c, SIZE - 30)
        path.quadTo(c - 24, c + 24, 30, c)
        path.quadTo(c - 24, c - 24, c, 30)
        _outline(p, path, color)
    p.end()
    return img


def ensure(folder: str | Path) -> dict[str, str]:
    """Write the pack into *folder* once; {name: png path}."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for name in NAMES:
        target = folder / f"sticker-{name}.png"
        if not target.is_file():
            draw(name).save(str(target), "PNG")
        out[name] = str(target)
    return out
