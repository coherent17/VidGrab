"""Shared constants and small helpers of the Studio screen."""
from __future__ import annotations

from PySide6.QtCore import (
    QPointF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

_HAND = Qt.PointingHandCursor
MIN_CLIP = 0.2  # shortest a clip can be trimmed to (s)
BEST_LENGTHS = (15, 30, 60)  # "Best moment" choices (s)
MIN_MUSIC = 0.5  # shortest part of a song that can be kept (s)
PROJECT_EXT = ".vgproj"
AUTOSAVE_MS = 60_000  # how often unsaved Studio work is copied for recovery
PROJECT_VERSION = 1
HISTORY_LIMIT = 200
COALESCE_S = 1.0  # edits of the same kind this close together undo as one step
FRAME = 1 / 30  # ← / → step

# (keys, description) for the shortcuts dialog, in display order
SHORTCUTS = (
    ("Space / K", "Play / pause"),
    ("J / L", "Back / forward 1 second"),
    ("← / →", "Back / forward one frame"),
    ("Home / End", "Go to the start / end"),
    ("I / O", "Trim the clip under the playhead to start / end here"),
    ("S", "Split the clip under the playhead"),
    ("M", "Mute / unmute the selected clip"),
    ("Delete", "Delete the selected clip or subtitle"),
    ("Ctrl+click / drag a box", "Select several items"),
    ("Ctrl+C / Ctrl+V / Ctrl+D", "Copy / paste at the playhead / duplicate"),
    ("Ctrl+A", "Select everything"),
    ("Esc", "Back to the project settings"),
    ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
    ("Ctrl+wheel, Ctrl++ / Ctrl+−", "Zoom the timeline"),
    ("Ctrl+0", "Fit the whole project"),
    ("Z", "Zoom to the selected clip"),
    ("Shift (while trimming)", "Move the handle ten times more finely"),
    ("Shift+wheel", "Scroll the zoomed timeline"),
    ("Alt (while dragging)", "Drag without snapping"),
    ("Ctrl+N / Ctrl+O", "New / open project"),
    ("Ctrl+S / Ctrl+Shift+S", "Save project / save as"),
)


def _arrow_icon(color: str, redo: bool) -> QIcon:
    """Curved undo / redo arrow (no emoji font needed)."""
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if redo:
        p.translate(18, 0)
        p.scale(-1, 1)
    pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(4, 7))
    path.cubicTo(QPointF(8, 3.5), QPointF(15, 4), QPointF(15, 10))
    path.cubicTo(QPointF(15, 13), QPointF(12.5, 15), QPointF(9, 15))
    p.drawPath(path)
    p.drawLine(QPointF(4, 7), QPointF(4.5, 2.5))
    p.drawLine(QPointF(4, 7), QPointF(8.5, 7.5))
    p.end()
    return QIcon(pm)


# (label key, colour) presets for subtitle text and its background box
TEXT_COLORS = [("White", "#FFFFFF"), ("Yellow", "#FFE500"), ("Cyan", "#00FFFF"),
               ("Pink", "#FF69B4"), ("Red", "#FF4D4D"), ("Green", "#3EE07A"),
               ("Black", "#000000")]
BG_COLORS = [("Black", "#000000"), ("Dark gray", "#333333"), ("White", "#FFFFFF"),
             ("Yellow", "#FFE500")]
CUSTOM = "custom"

# label keys for studio.TRANSITIONS
TRANSITION_LABELS = {
    "none": "Cut", "fade": "Crossfade", "fadeblack": "Dip to black",
    "fadewhite": "Dip to white", "dissolve": "Dissolve", "wipeleft": "Wipe",
    "slideleft": "Slide", "circleopen": "Circle", "zoomin": "Zoom in",
}
# label keys for studio.ANIMATIONS
# export presets: label key, frame size (None = keep), file type
EXPORT_PRESETS = {
    "youtube": ("YouTube (1080p)", "1080p", ".mp4"),
    "shorts": ("Shorts / Reels / TikTok", "vertical", ".mp4"),
    "square": ("Square (1:1)", "square", ".mp4"),
    "auto": ("Same as the clips", "auto", ".mp4"),
    "gif": ("GIF", None, ".gif"),
    "audio": ("Audio only (MP3)", None, ".mp3"),
}
ANIMATION_LABELS = {"none": "None", "pop": "Pop", "slide": "Slide up",
                    "typewriter": "Typewriter", "karaoke": "Karaoke",
                    "highlight": "Word highlight"}
FILMSTRIP = 4  # frames probed up front (block label + fallback until the cache fills)
# tile spacing in source seconds, chosen from these so cached frames line up
THUMB_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800)
