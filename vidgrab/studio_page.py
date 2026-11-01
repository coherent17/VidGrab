"""The Studio page: an editor workspace for joining clips.

Layout (no scrolling)::

    ┌ Video montage | Music medley ······················ progress · Render ┐
    ├ preview (large, plays the whole result) ─────────────┬ Inspector ─────┤
    │                       ▶  0:12.0 / 1:05.0             │ (project /     │
    │                                                      │  subtitle /    │
    ├ + Media  + Subtitle  ♪ Music  .srt ············ ▲ ▼ ✕  music)        │
    ├ ruler ─────────────────────────────────────────────────────────────────┤
    │ 1 a.mp4    ▕▌▓▓▓▓▓▓▓▓▐▏                                                │
    │ 2 b.mp4               ░░▕▌▓▓▓▓▓▓▓▓▓▓▓▐▏░░░░                            │
    │ 3 song.mp3                               ▕▌∿∿∿∿∿∿∿∿∿∿∿▐▏               │
    │ Subtitles      [你好]       [Second line]                              │
    └ Music      [∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿ ↻ bgm.mp3 ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿]          ┘

Every clip has its own row. The bright block is the part that is kept;
the faint part around it is the rest of the source. Drag the block's left
handle to choose where the clip starts and the right handle to choose where
it ends — the preview shows the frame under the handle while dragging.
Drag a block up or down to change the order.

Ctrl+wheel zooms the timeline (Shift+wheel pans); while dragging, handles and
subtitle blocks snap to the playhead, clip boundaries and other subtitles
(hold Alt to drag freely).
"""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from dataclasses import asdict, astuple, dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab import cuda_runtime
from vidgrab.captions import DEFAULT_MODEL as DEFAULT_CAPTION_MODEL
from vidgrab.captions import LANGUAGES as CAPTION_LANGUAGES
from vidgrab.captions import MODELS as CAPTION_MODELS
from vidgrab.captions import (
    CaptionSource,
    detect_gpus,
    model_info,
    model_ready,
    speech_engines,
)
from vidgrab.captions import (
    installed as captions_installed,
)
from vidgrab.preview import MusicBed, Segment, StudioPreview, TransitionMark, fmt_time
from vidgrab.split_dialog import SplitDialog
from vidgrab.studio import (
    ANIMATIONS,
    IMAGE_EXTS,
    SPEED_RANGE,
    SUBTITLE_FONT_NAME,
    TRANSITIONS,
    BackgroundMusic,
    Clip,
    ImageOverlay,
    SubtitleCue,
    SubtitleStyle,
    canvas_size,
    cue_style,
    parse_srt,
    parse_timecode,
    probe_media,
    system_fonts,
    thumbnail_png,
    transition_overlaps,
    waveform,
)

_HAND = Qt.PointingHandCursor
MIN_CLIP = 0.2  # shortest a clip can be trimmed to (s)
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
                    "typewriter": "Typewriter", "karaoke": "Karaoke"}
FILMSTRIP = 4  # frames probed up front (block label + fallback until the cache fills)
# tile spacing in source seconds, chosen from these so cached frames line up
THUMB_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800)


class _ThumbRelay(QObject):
    done = Signal(str, float, QImage)


class _ThumbTask(QRunnable):
    def __init__(self, relay: _ThumbRelay, path: str, at: float) -> None:
        super().__init__()
        self._relay, self._path, self._at = relay, path, at

    def run(self) -> None:
        png = thumbnail_png(self._path, self._at)
        self._relay.done.emit(self._path, self._at, QImage.fromData(png) if png else QImage())


class ThumbCache(QObject):
    """Timeline frames, extracted on demand in the background so every tile
    shows the frame at its own time (and zooming in shows finer detail)."""

    updated = Signal()
    LIMIT = 1200  # frames kept (~10 KB each)
    MAX_PENDING = 48

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._relay = _ThumbRelay(self)
        self._relay.done.connect(self._done)
        self._images: OrderedDict[tuple[str, float], QImage] = OrderedDict()
        self._by_path: dict[str, dict[float, QImage]] = {}
        self._pending: set[tuple[str, float]] = set()

    def frame(self, path: str, at: float, step: float) -> QImage | None:
        """The frame for *at* rounded to *step*; queued (None) if not ready."""
        key = (path, round(round(at / step) * step, 3))
        img = self._images.get(key)
        if img is not None:
            self._images.move_to_end(key)
            return img
        if key not in self._pending and len(self._pending) < self.MAX_PENDING:
            self._pending.add(key)
            self._pool.start(_ThumbTask(self._relay, path, key[1]))
        return None

    def nearest(self, path: str, at: float) -> QImage | None:
        frames = self._by_path.get(path)
        if not frames:
            return None
        return frames[min(frames, key=lambda t: abs(t - at))]

    def _done(self, path: str, at: float, img: QImage) -> None:
        self._pending.discard((path, at))
        if img.isNull():
            return
        self._images[(path, at)] = img
        self._by_path.setdefault(path, {})[at] = img
        while len(self._images) > self.LIMIT:
            (old_path, old_at), _img = self._images.popitem(last=False)
            self._by_path.get(old_path, {}).pop(old_at, None)
        self.updated.emit()

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(3000)


def _swatch(color: str | None, size: int = 16) -> QIcon:
    """Colour square (checkerboard + red slash for 'none')."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    box = QRectF(1, 1, size - 2, size - 2)
    if color:
        p.setBrush(QColor(color))
        p.setPen(QPen(QColor("#808080"), 1))
        p.drawRoundedRect(box, 4, 4)
    else:
        path = QPainterPath()
        path.addRoundedRect(box, 4, 4)
        p.setClipPath(path)
        cell = size / 4
        for i in range(4):
            for j in range(4):
                p.fillRect(QRectF(i * cell, j * cell, cell, cell),
                           QColor("#cccccc") if (i + j) % 2 else QColor("#ffffff"))
        p.setClipping(False)
        p.setPen(QPen(QColor("#ef4444"), 2))
        p.drawLine(QPointF(3, size - 3), QPointF(size - 3, 3))
    p.end()
    return QIcon(pm)


class ColorSwatches(QWidget):
    """A row of clickable colour squares (+ 'none' and a custom colour picker)
    — every choice visible at once, no dropdown."""

    changed = Signal(str)  # "#RRGGBB", or "" for none

    SIZE = 28

    def __init__(self, colors: list[tuple[str, str]], *, allow_none: bool, t,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._t = t
        self._presets = colors
        self._allow_none = allow_none
        self._custom: str | None = None
        self._value = "" if allow_none else colors[0][1]
        self._buttons: dict[str, QPushButton] = {}
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(5)
        self._accent = "#7c5cff"
        self._rebuild()

    def _make(self, color: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("swatch")
        b.setCheckable(True)
        b.setFixedSize(self.SIZE, self.SIZE)
        b.setIconSize(QSize(self.SIZE - 8, self.SIZE - 8))
        b.setIcon(_swatch(color or None, self.SIZE - 8))
        b.setToolTip(tip)
        b.setCursor(QCursor(_HAND))
        b.clicked.connect(lambda _c=False, v=color: self._pick(v))
        return b

    def _rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons = {}
        entries = ([("", self._t("None (transparent)"))] if self._allow_none else []) + \
            [(c, self._t(k)) for k, c in self._presets]
        if self._custom and all(self._custom != c for c, _k in entries):
            entries.append((self._custom, self._custom))
        for color, tip in entries:
            b = self._make(color, tip)
            self._buttons[color] = b
            self._lay.addWidget(b)
        more = QPushButton("+")
        more.setObjectName("swatch_add")
        more.setFixedSize(self.SIZE, self.SIZE)
        more.setToolTip(self._t("Custom\u2026"))
        more.setCursor(QCursor(_HAND))
        more.clicked.connect(self._pick_custom)
        self._lay.addWidget(more)
        self._lay.addStretch()
        self._sync()

    def retranslate(self) -> None:
        self._rebuild()

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.setStyleSheet(
            f"QPushButton#swatch {{ border: 2px solid transparent; border-radius: 7px;"
            f" padding: 0; background: transparent; }}"
            f"QPushButton#swatch:hover {{ border-color: {color}80; }}"
            f"QPushButton#swatch:checked {{ border-color: {color}; }}"
            f"QPushButton#swatch_add {{ border: 1px dashed {color}; border-radius: 7px;"
            f" padding: 0; background: transparent; color: {color}; font-size: 17px;"
            f" font-weight: 600; }}"
            f"QPushButton#swatch_add:hover {{ background: {color}33; }}")

    def _sync(self) -> None:
        for color, b in self._buttons.items():
            b.setChecked(color == self._value)

    def color(self) -> str:
        return self._value

    def set_color(self, color: str | None) -> None:
        """Select *color* without emitting `changed` (adds it if it's custom)."""
        color = (color or "").upper() if color else ""
        if not color and not self._allow_none:
            color = self._presets[0][1]
        if color not in self._buttons:
            self._custom = color
            self._rebuild()
        self._value = color
        self._sync()

    def _pick(self, color: str) -> None:
        self._value = color
        self._sync()
        self.changed.emit(color)

    def _pick_custom(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._value or "#FFFFFF"), self,
                                       self._t("Custom\u2026"))
        if chosen.isValid():
            self.set_color(chosen.name().upper())
            self.changed.emit(self._value)
        else:
            self._sync()


@dataclass
class _MediaClip:
    path: str
    info: dict
    start: float | None = None
    end: float | None = None
    thumb: QImage | None = None
    wave: list[float] = field(default_factory=list)
    # (source time, frame) samples drawn along the block — a filmstrip
    thumbs: list[tuple[float, QImage]] = field(default_factory=list)
    transition: str = "none"  # into this clip from the previous one
    transition_d: float = 1.0
    fit: str = "fit"
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    volume: float = 1.0  # the clip's own sound, 0..2
    muted: bool = False
    speed: float = 1.0  # 0.25 .. 4
    denoise: bool = False  # reduce steady background noise when rendering

    @property
    def has_audio(self) -> bool:
        return bool(self.info.get("has_audio"))

    def gain(self) -> float:
        return 0.0 if self.muted else self.volume

    def edit(self) -> tuple:
        """The user-editable part, as plain comparable data (undo / projects)."""
        return (self.start, self.end, self.transition, self.transition_d, self.fit,
                self.zoom, self.pan_x, self.pan_y, self.volume, self.muted, self.speed,
                self.denoise)

    def with_edit(self, edit: tuple) -> _MediaClip:
        (start, end, transition, transition_d, fit, zoom, pan_x, pan_y, volume,
         muted, *rest) = edit
        return replace(self, start=start, end=end, transition=transition,
                       transition_d=transition_d, fit=fit, zoom=zoom, pan_x=pan_x, pan_y=pan_y,
                       volume=volume, muted=muted, speed=rest[0] if rest else 1.0,
                       denoise=bool(rest[1]) if len(rest) > 1 else False)

    def frame_at(self, t: float) -> QImage | None:
        if not self.thumbs:
            return self.thumb
        return min(self.thumbs, key=lambda item: abs(item[0] - t))[1]

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def length(self) -> float:
        return float(self.info.get("duration") or 0.0)

    @property
    def has_video(self) -> bool:
        return bool(self.info.get("has_video"))

    def span(self) -> tuple[float, float]:
        s = self.start or 0.0
        e = self.end if self.end is not None else self.length
        return s, min(e, self.length) if self.length else e

    def part(self) -> float:
        """Length of the part of the source that is used (source seconds)."""
        s, e = self.span()
        return max(0.0, e - s)

    def kept(self) -> float:
        """How long the clip lasts in the montage (its part / speed)."""
        return self.part() / self.speed


def _fmt_precise(seconds: float) -> str:
    """M:SS.ss — hundredths, so one-frame nudges show."""
    m, sec = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{sec:05.2f}"


def _brightness(img: QImage) -> float:
    """Mean brightness (0-255) of a downscaled copy of *img*."""
    small = img.scaled(16, 9).convertToFormat(QImage.Format_Grayscale8)
    values = [small.pixelColor(x, y).value() for y in range(small.height())
              for x in range(small.width())]
    return sum(values) / max(1, len(values))


@dataclass
class _Song:
    """One background song: the part that plays, when it comes in, its level."""

    path: str
    info: dict
    wave: list[float] = field(default_factory=list)
    start: float = 0.0
    end: float | None = None  # None = to the end of the song
    offset: float = 0.0  # where it comes in on the montage timeline
    volume: int = 35  # percent
    fade: float = 0.0  # fade in / out at its own edges (s)

    @property
    def length(self) -> float:
        return float(self.info.get("duration") or 0.0)

    def span(self) -> tuple[float, float]:
        return self.start, (self.end if self.end is not None else self.length)

    def edit(self) -> tuple:
        return (self.path, self.start, self.end, self.offset, self.volume, self.fade)


def clip_overlaps(clips: list[_MediaClip]) -> list[float]:
    return transition_overlaps([c.kept() for c in clips],
                               [(c.transition, c.transition_d) for c in clips])


# ── multi-track timeline ──────────────────────────────────────────────────


class TrackTimeline(QWidget):
    """One row per clip, then Subtitles and Music, under a time ruler."""

    seek_requested = Signal(float)
    clip_selected = Signal(int)
    clip_trimming = Signal(int, float, float, str)  # row, start, end, "start"|"end"
    clip_trimmed = Signal(int, float, float)
    clip_moved = Signal(int, int)  # from, to
    clip_mute_toggled = Signal(int)
    cue_selected = Signal(int)
    cue_changed = Signal(int, float, float)
    cue_add_requested = Signal(float)
    image_selected = Signal(int)
    image_timing = Signal(int, float, float)  # picture, start, end
    image_add_requested = Signal(float)
    music_selected = Signal(int)  # song index
    item_toggled = Signal(str, int)  # Ctrl+click: kind, index
    box_selected = Signal(list)  # [(kind, index), ...] inside a dragged box
    group_moved = Signal(float)  # the other picked subtitles / pictures move this much
    item_clicked = Signal(str, int)  # pressed and released without moving
    music_changed = Signal(int, float, float, float)  # song, its start / end, offset on the timeline
    add_media_requested = Signal()
    music_requested = Signal()
    view_changed = Signal()  # zoom or horizontal scroll changed

    HEADER_W, RULER_H, GAP = 168, 24, 5
    CLIP_H, SUBS_H, MUSIC_H = 46, 30, 36
    LANE_H = 26  # one lane of overlapping subtitle lines
    EDGE = 10  # px around a block edge that grabs its trim handle
    HEADROOM = 1.12  # spare width on the right so clips can be lengthened
    MAX_ZOOM = 200.0
    SNAP_PX = 8  # how close (px) an edge must come to a target to snap to it

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._clips: list[_MediaClip] = []
        self._cues: list[tuple[float, float, str]] = []
        self._music: list[dict] = []  # one entry per background song
        self._images: list[tuple[float, float, str, QImage | None]] = []  # start, end, name, thumb
        self._labels = {"subs": "Subtitles", "music": "Music", "empty": "",
                        "empty_subs": "", "empty_music": "", "mute": "", "unmute": "",
                        "images": "Images", "empty_images": ""}
        self._show_subs = True
        self._show_music = True
        self._playhead = 0.0
        self._selection: tuple[str, int] | None = None
        self._hover: tuple[str, int, str] | None = None
        self._drag: dict | None = None
        self._icons: dict[str, QImage] = {}
        self._picked: set[tuple[str, int]] = set()
        self._zoom = 1.0  # 1 = the whole project fits the width
        self._view = 0.0  # time (s) at the left edge of the track area
        self._thumbs: ThumbCache | None = None
        # dragging a trim handle past the edge keeps extending the clip
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(30)
        self._edge_timer.timeout.connect(self._edge_tick)
        self._colors = {
            "bg": "#0e0f22", "track": "#14152b", "line": "#262a4d", "text": "#eceeff",
            "muted": "#7b80aa", "clip": "#f472b6", "clip2": "#a78bfa", "audio": "#34d399",
            "cue": "#facc15", "music": "#22d3ee", "sel": "#ffffff", "head": "#ff4d6d",
            "accent": "#7c5cff", "hdr_sel": "#2a2160",
        }
        self._update_height()

    # data ----------------------------------------------------------------

    def set_colors(self, **colors: str) -> None:
        self._colors.update(colors)
        self.update()

    def set_icons(self, icons: dict[str, QImage]) -> None:
        self._icons = icons
        self.update()

    def set_thumb_cache(self, cache: ThumbCache) -> None:
        self._thumbs = cache
        cache.updated.connect(self.update)

    def _tile_frame(self, clip: _MediaClip, at: float, step: float) -> QImage | None:
        if self._thumbs is not None:
            img = self._thumbs.frame(clip.path, at, step) or self._thumbs.nearest(clip.path, at)
            if img is not None:
                return img
        return clip.frame_at(at)

    def zoom_to(self, start: float, end: float) -> None:
        """Zoom so the time range start..end fills most of the view."""
        span = max(end - start, 0.2)
        self._zoom = min(max(self.content_span() / (span * 1.3), 1.0), self.MAX_ZOOM)
        self._view = start - span * 0.15
        self._clamp_view()

    def set_labels(self, **labels: str) -> None:
        self._labels.update(labels)
        self.update()

    def set_tracks(self, *, subs: bool, music: bool) -> None:
        # subtitles / music rows = video montage, where transitions apply too
        self._show_subs, self._show_music = subs, music
        self._update_height()

    def set_data(self, clips: list[_MediaClip], cues, music: list[dict] | None,
                 images: list | None = None) -> None:
        if self._drag is not None:
            return
        self._clips, self._cues, self._music = clips, cues, list(music or [])
        self._images = list(images or [])
        self._update_height()
        self._clamp_view()

    def set_playhead(self, t: float) -> None:
        self._playhead = t
        if self._zoom > 1.0 and self._drag is None:  # keep the playhead in view
            visible = self.visible_span()
            if not self._view <= t <= self._view + visible:
                self.set_view(t - visible * 0.1)
        self.update()

    def set_picked(self, picked: set[tuple[str, int]]) -> None:
        """Items selected together with the main selection (multi-select)."""
        self._picked = set(picked)
        self.update()

    def _is_sel(self, kind: str, i: int) -> bool:
        return self._selection == (kind, i) or (kind, i) in self._picked

    def set_selection(self, sel: tuple[str, int] | None) -> None:
        self._selection = sel
        self.update()

    def overlaps(self) -> list[float]:
        """How far each clip overlaps the previous one (its transition)."""
        if not self._show_subs:  # music medley: one crossfade setting for all
            return [0.0] * len(self._clips)
        return clip_overlaps(self._clips)

    def total(self) -> float:
        return sum(c.kept() for c in self._clips) - sum(self.overlaps())

    def offsets(self) -> list[float]:
        out, t = [], 0.0
        for c, ov in zip(self._clips, self.overlaps()):
            t -= ov
            out.append(t)
            t += c.kept()
        return out

    # zoom / horizontal view ------------------------------------------------

    def zoom(self) -> float:
        return self._zoom

    def view_start(self) -> float:
        return self._view

    def content_span(self) -> float:
        return max(self.total() * self.HEADROOM, 1.0)

    def visible_span(self) -> float:
        return self._area_w() / self._pps()

    def set_zoom(self, zoom: float, anchor: float | None = None) -> None:
        """Zoom so that time *anchor* (default: the playhead) stays put."""
        zoom = min(max(zoom, 1.0), self.MAX_ZOOM)
        if anchor is None:
            anchor = self._playhead
        x = self._x(anchor)
        self._zoom = zoom
        self._view = anchor - (x - self.HEADER_W) / self._pps()
        self._clamp_view()

    def set_view(self, start: float) -> None:
        self._view = start
        self._clamp_view()

    def _clamp_view(self) -> None:
        if self._zoom <= 1.0:
            self._zoom, view = 1.0, 0.0
        else:
            view = min(max(self._view, 0.0), max(0.0, self.content_span() - self.visible_span()))
        self._view = view
        self.update()
        self.view_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp_view()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        if event.modifiers() & Qt.ControlModifier and delta.y():
            self.set_zoom(self._zoom * 1.25 ** (delta.y() / 120),
                          self._t(event.position().x(), clamp=False))
            event.accept()
            return
        dx = delta.x() or (delta.y() if event.modifiers() & Qt.ShiftModifier else 0)
        if dx and self._zoom > 1.0:
            self.set_view(self._view - dx / 120 * self.visible_span() * 0.1)
            event.accept()
            return
        event.ignore()  # let the scroll area scroll the rows

    # snapping ----------------------------------------------------------------

    def _snap(self, t: float, targets: list[float], *, free: bool) -> tuple[float, float | None]:
        """Pull *t* onto the nearest target within SNAP_PX; returns (t, target)."""
        if free or not targets:
            return t, None
        best = min(targets, key=lambda g: abs(g - t))
        if abs(best - t) * self._pps() <= self.SNAP_PX:
            return best, best
        return t, None

    def _cue_edges(self, skip: int | None = None) -> list[float]:
        return [v for k, (s, e, _t) in enumerate(self._cues) if k != skip for v in (s, e)]

    # geometry ------------------------------------------------------------

    def _area_w(self) -> float:
        return max(1.0, self.width() - self.HEADER_W - 10)

    def _rows(self) -> list[tuple[str, int, int]]:
        """(kind, index, height) for every row, top to bottom."""
        rows = [("clip", i, self.CLIP_H) for i in range(len(self._clips))] or \
            [("empty", 0, self.CLIP_H)]
        if self._show_subs:
            lanes = max(1, max(self._cue_lanes(), default=0) + 1)
            rows.append(("subs", 0, self.SUBS_H + (lanes - 1) * self.LANE_H))
            lanes = max(1, max(self._image_lanes(), default=0) + 1)
            rows.append(("images", 0, self.SUBS_H + (lanes - 1) * self.LANE_H))
        if self._show_music:
            rows.append(("music", 0, self.MUSIC_H))
        return rows

    def _update_height(self) -> None:
        h = sum(r[2] + self.GAP for r in self._rows())
        self.setFixedHeight(self.RULER_H + h + 8)
        self.update()

    def _row_rect(self, kind: str, idx: int = 0) -> QRectF | None:
        """The time area of a row (right of the header)."""
        y = self.RULER_H + 4
        for k, i, h in self._rows():
            if (k, i) == (kind, idx):
                return QRectF(self.HEADER_W, y, self.width() - self.HEADER_W - 10, h)
            y += h + self.GAP
        return None

    def _pps(self) -> float:
        if self._drag is not None and "pps" in self._drag:
            return self._drag["pps"]  # frozen while trimming / reordering
        return self._area_w() / self.content_span() * self._zoom

    def _x(self, t: float) -> float:
        return self.HEADER_W + (t - self._view) * self._pps()

    def _t(self, x: float, clamp: bool = True) -> float:
        t = (x - self.HEADER_W) / self._pps() + self._view
        return min(max(t, 0.0), max(self.total(), 0.0)) if clamp else t

    def _clip_rect(self, i: int) -> QRectF:
        """The kept part of clip *i* (honours an in-progress trim drag)."""
        d = self._drag or {}
        offs = d.get("offsets") or self.offsets()
        row = self._row_rect("clip", i)
        clip = self._clips[i]
        x0 = self._x(offs[i])
        if d.get("kind") in ("trim_start", "trim_end") and d.get("row") == i:
            pps = self._pps() / clip.speed  # pixels per *source* second
            # the source stays put; the handle slides over it
            src_left = x0 - d["s0"] * pps
            return QRectF(src_left + d["s"] * pps, row.top(), (d["e"] - d["s"]) * pps,
                          row.height())
        return QRectF(x0, row.top(), max(4.0, clip.kept() * self._pps()), row.height())

    def _source_rect(self, i: int) -> QRectF:
        """The whole source of clip *i*, aligned so its kept part sits in place."""
        d = self._drag or {}
        offs = d.get("offsets") or self.offsets()
        row = self._row_rect("clip", i)
        clip = self._clips[i]
        s0 = d["s0"] if d.get("row") == i and "s0" in d else clip.span()[0]
        pps = self._pps() / clip.speed  # pixels per source second
        left = self._x(offs[i]) - s0 * pps
        return QRectF(left, row.top(), clip.length * pps, row.height())

    @staticmethod
    def _lanes(spans: list[tuple[float, float]]) -> list[int]:
        """A lane per item so that items overlapping in time sit one under
        another (first free lane, in start order); others share a lane."""
        lanes = [0] * len(spans)
        ends: list[float] = []  # per lane: when its last item ends
        for k in sorted(range(len(spans)), key=lambda k: spans[k][0]):
            s, e = spans[k]
            lane = next((n for n, end in enumerate(ends) if end <= s + 1e-6), len(ends))
            if lane == len(ends):
                ends.append(e)
            else:
                ends[lane] = e
            lanes[k] = lane
        return lanes

    def _cue_lanes(self) -> list[int]:
        """Subtitle lanes (frozen while a line is dragged)."""
        d = self._drag or {}
        if d.get("kind", "").startswith("cue_") and "lanes" in d:
            return d["lanes"]
        return self._lanes([(s, e) for s, e, _t in self._cues])

    def _image_lanes(self) -> list[int]:
        d = self._drag or {}
        if d.get("kind", "").startswith("img_") and "lanes" in d:
            return d["lanes"]
        return self._lanes([(s, e) for s, e, _n, _i in self._images])

    def _image_rects(self) -> list[QRectF]:
        r = self._row_rect("images")
        if r is None:
            return []
        lanes = self._image_lanes()
        return [QRectF(self._x(s), r.top() + 3 + lanes[k] * self.LANE_H,
                       max(4.0, (e - s) * self._pps()), self.SUBS_H - 6)
                for k, (s, e, _n, _i) in enumerate(self._images)]

    def _cue_rects(self) -> list[QRectF]:
        r = self._row_rect("subs")
        if r is None:
            return []
        lanes = self._cue_lanes()
        return [QRectF(self._x(s), r.top() + 3 + lanes[k] * self.LANE_H,
                       max(4.0, (e - s) * self._pps()), self.SUBS_H - 6)
                for k, (s, e, _t) in enumerate(self._cues)]

    # painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        c = {k: QColor(v) for k, v in self._colors.items()}
        p.fillRect(self.rect(), c["bg"])
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        fm = QFontMetricsF(small)
        total = self.total()
        pps = self._pps()

        # ruler
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800)
                     if s * pps >= 70), 3600)
        p.setPen(c["muted"])
        t = int(self._view / step) * step
        while total > 0 and self._x(t) < self.width() - 20:
            x = self._x(t)
            if x >= self.HEADER_W - 1:
                p.drawLine(QPointF(x, self.RULER_H - 7), QPointF(x, self.RULER_H - 1))
                p.drawText(QPointF(x + 3, self.RULER_H - 9), fmt_time(t).rstrip("0").rstrip("."))
            t += step
        p.setPen(c["line"])
        p.drawLine(0, self.RULER_H, self.width(), self.RULER_H)

        # rows
        area_clip = QRectF(self.HEADER_W, 0, self.width() - self.HEADER_W - 10, self.height())
        for kind, i, _h in self._rows():
            r = self._row_rect(kind, i)
            full = QRectF(8, r.top(), self.width() - 18, r.height())
            selected_row = kind == "clip" and self._is_sel("clip", i)
            p.setPen(Qt.NoPen)
            p.setBrush(c["track"])
            p.drawRoundedRect(full, 8, 8)
            if selected_row:
                p.setBrush(c["hdr_sel"])
                p.drawRoundedRect(QRectF(8, r.top(), self.HEADER_W - 14, r.height()), 8, 8)
            self._paint_header(p, c, fm, kind, i, QRectF(14, r.top(), self.HEADER_W - 24, r.height()))

        p.save()
        p.setClipRect(area_clip)
        if not self._clips:
            p.setPen(c["muted"])
            big = QFont(self.font())
            big.setPixelSize(13)
            p.setFont(big)
            p.drawText(self._row_rect("empty"), Qt.AlignCenter, self._labels["empty"])
            p.setFont(small)
        for i in range(len(self._clips)):
            self._paint_clip(p, c, fm, i)
        self._paint_reorder(p, c)
        self._paint_cues(p, c, fm)
        self._paint_images(p, c, fm)
        self._paint_music(p, c, fm, total)
        d = self._drag or {}
        if d.get("kind") == "box" and d.get("active"):
            box = QRectF(QPointF(min(d["x0"], d["x"]), min(d["y0"], d["y"])),
                         QPointF(max(d["x0"], d["x"]), max(d["y0"], d["y"])))
            fill = QColor(c["accent"])
            fill.setAlpha(40)
            p.setPen(QPen(c["accent"], 1.2, Qt.DashLine))
            p.setBrush(fill)
            p.drawRect(box)
        snap = (self._drag or {}).get("snap")
        if snap is not None:  # the line an edge snapped to
            p.setPen(QPen(c["accent"], 1.6, Qt.DashLine))
            p.drawLine(QPointF(self._x(snap), self.RULER_H), QPointF(self._x(snap), self.height()))
        p.restore()

        x = self._x(min(self._playhead, total))
        if total > 0 and x >= self.HEADER_W - 6:  # playhead
            p.setBrush(c["head"])
            p.drawRect(QRectF(x - 1, self.RULER_H - 4, 2, self.height() - self.RULER_H))
            p.drawPolygon([QPointF(x - 6, 2), QPointF(x + 6, 2), QPointF(x, 12)])
        p.end()

    def _paint_header(self, p, c, fm, kind: str, i: int, rect: QRectF) -> None:
        if kind == "clip":
            clip = self._clips[i]
            icon = self._icons.get("film" if clip.has_video else "music")
            num = f"{i + 1}"
            p.setPen(c["muted"])
            p.drawText(QRectF(rect.left(), rect.top(), 16, rect.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, num)
            x = rect.left() + 18
            if icon is not None:
                p.drawImage(QRectF(x, rect.center().y() - 8, 16, 16), icon)
                x += 22
            right = rect.right()
            if clip.has_audio:
                self._paint_speaker(p, c, self._mute_rect(i), clip.muted,
                                    self._hover == ("clip", i, "mute"))
                right -= 26
            p.setPen(c["text"])
            name_rect = QRectF(x, rect.top() + 4, right - x, rect.height() / 2 - 2)
            p.drawText(name_rect, Qt.AlignBottom | Qt.AlignLeft,
                       fm.elidedText(clip.name, Qt.ElideMiddle, name_rect.width()))
            p.setPen(c["muted"])
            p.drawText(QRectF(x, rect.center().y() + 1, right - x, rect.height() / 2 - 4),
                       Qt.AlignTop | Qt.AlignLeft, fmt_time(clip.kept()))
        elif kind in ("subs", "music", "images"):
            p.setPen(c["muted"])
            p.drawText(QRectF(rect.left(), rect.top(), rect.width(), min(rect.height(), self.SUBS_H)),
                       Qt.AlignVCenter | Qt.AlignLeft, self._labels[kind])

    def _mute_rect(self, i: int) -> QRectF:
        row = self._row_rect("clip", i)
        return QRectF(self.HEADER_W - 34, row.center().y() - 12, 24, 24)

    @staticmethod
    def _paint_speaker(p, c, rect: QRectF, muted: bool, hover: bool) -> None:
        """A speaker; red and struck through when the clip is muted."""
        p.save()
        if hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(rect, 6, 6)
        col = QColor("#ff4d6d") if muted else QColor(c["muted"])
        x, y = rect.left() + 5, rect.center().y()
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPolygon([QPointF(x, y - 3), QPointF(x + 3, y - 3), QPointF(x + 7, y - 7),
                       QPointF(x + 7, y + 7), QPointF(x + 3, y + 3), QPointF(x, y + 3)])
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap))
        if muted:
            p.drawLine(QPointF(x + 10, y - 4), QPointF(x + 16, y + 4))
            p.drawLine(QPointF(x + 16, y - 4), QPointF(x + 10, y + 4))
        else:
            p.drawArc(QRectF(x + 5, y - 4, 6, 8), -60 * 16, 120 * 16)
            p.drawArc(QRectF(x + 5, y - 7, 11, 14), -60 * 16, 120 * 16)
        p.restore()

    def _paint_clip(self, p, c, fm, i: int) -> None:
        d = self._drag or {}
        if d.get("kind") == "reorder" and d.get("row") == i and d.get("active"):
            p.setOpacity(0.35)
        clip = self._clips[i]
        base = QColor(c["clip"] if i % 2 == 0 else c["clip2"]) if clip.has_video \
            else QColor(c["audio"])
        selected = self._is_sel("clip", i)
        hover = self._hover is not None and self._hover[:2] == ("clip", i)

        # the rest of the source, faint, so it's clear how far a handle can go
        src = self._source_rect(i).adjusted(0, 6, 0, -6)
        ghost = QColor(base)
        ghost.setAlpha(45)
        p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 90), 1, Qt.DashLine))
        p.setBrush(ghost)
        p.drawRoundedRect(src, 6, 6)

        rect = self._clip_rect(i)
        body = rect.adjusted(0, 1, 0, -1)
        path = QPainterPath()
        path.addRoundedRect(body, 7, 7)
        p.save()
        p.setClipPath(path, Qt.IntersectClip)
        p.fillRect(body, QColor(base).darker(260))
        if clip.thumb is not None and not clip.thumb.isNull():
            # filmstrip: each tile shows the source frame at its own time
            th = body.height()
            tw = clip.thumb.width() * th / max(1, clip.thumb.height())
            src_left, pps = self._source_rect(i).left(), self._pps() / clip.speed
            step = next((v for v in THUMB_STEPS if v * pps >= tw + 2), THUMB_STEPS[-1])
            x = body.left()
            while x < body.right():
                if x + tw >= 0 and x <= self.width():  # only tiles on screen
                    at = min(max((x + tw / 2 - src_left) / pps, 0.0), clip.length)
                    frame = self._tile_frame(clip, at, step)
                    if frame is not None and not frame.isNull():
                        p.drawImage(QRectF(x, body.top(), tw, th), frame)
                x += tw + 2
        elif clip.wave:
            self._wave(p, body.adjusted(10, 4, -10, -4), clip.wave,
                       (d["s"], d["e"]) if d.get("row") == i and "e" in d else clip.span(),
                       clip.length, base)
        grad = QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0.0, QColor(0, 0, 0, 120))
        grad.setColorAt(0.5, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.fillRect(body, grad)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(c["sel"]) if selected else base, 2 if selected else 1.4))
        p.drawRoundedRect(body, 7, 7)

        # transition in: the part that overlaps the previous clip
        overlap = self.overlaps()[i] if d.get("kind") not in ("trim_start", "trim_end") else 0.0
        if overlap > 0:
            zone = QRectF(body.left(), body.top(), overlap * self._pps(), body.height())
            p.save()
            p.setClipPath(path, Qt.IntersectClip)
            p.fillRect(zone, QColor(255, 255, 255, 70))
            p.setPen(QPen(QColor("#ffffff"), 1.6))
            p.drawLine(zone.topLeft(), zone.bottomRight())
            p.drawLine(zone.bottomLeft(), zone.topRight())
            p.restore()

        # start / end handles
        strong = selected or hover or d.get("row") == i
        for x, left in ((body.left(), True), (body.right(), False)):
            grip = QRectF(x if left else x - 9, body.top(), 9, body.height())
            col = QColor(c["sel"]) if strong else QColor(base).lighter(125)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(grip, 3, 3)
            p.setPen(QPen(QColor("#202030"), 1.2))
            cx = grip.center().x()
            for dy in (-5, 0, 5):
                p.drawLine(QPointF(cx - 2, grip.center().y() + dy),
                           QPointF(cx + 2, grip.center().y() + dy))
        # time read-outs while trimming
        if d.get("kind") in ("trim_start", "trim_end") and d.get("row") == i:
            p.setPen(QColor("#ffffff"))
            label = fmt_time(d["s"] if d["kind"] == "trim_start" else d["e"])
            tx = body.left() + 12 if d["kind"] == "trim_start" else body.right() - 70
            p.drawText(QRectF(tx, body.top(), 60, body.height()), Qt.AlignCenter, label)
        p.setOpacity(1.0)

    def _paint_reorder(self, p, c) -> None:
        d = self._drag or {}
        if d.get("kind") != "reorder" or not d.get("active"):
            return
        dest = self._reorder_target(d["y"])
        rows = [self._row_rect("clip", k) for k in range(len(self._clips))]
        if dest <= d["row"]:
            y = rows[dest].top() - self.GAP / 2
        else:
            y = rows[dest].bottom() + self.GAP / 2
        p.setPen(Qt.NoPen)
        p.setBrush(c["accent"])
        p.drawRoundedRect(QRectF(self.HEADER_W, y - 2, self.width() - self.HEADER_W - 10, 4), 2, 2)

    def _reorder_target(self, y: float) -> int:
        for k in range(len(self._clips)):
            r = self._row_rect("clip", k)
            if y < r.bottom() + self.GAP / 2:
                return k
        return len(self._clips) - 1

    @staticmethod
    def _wave(p, rect: QRectF, wave: list[float], span: tuple[float, float], length: float,
              color: QColor) -> None:
        if not wave or length <= 0 or rect.width() <= 2:
            return
        a = int(span[0] / length * len(wave))
        b = max(a + 1, int(span[1] / length * len(wave)))
        part = wave[a:b] or wave[-1:]
        mid = rect.center().y()
        half = rect.height() / 2
        col = QColor(color)
        col.setAlpha(220)
        p.setPen(QPen(col, 1.2))
        n = max(1, int(rect.width() / 2))
        for k in range(n):
            v = part[min(len(part) - 1, int(k / n * len(part)))]
            x = rect.left() + k * 2
            p.drawLine(QPointF(x, mid - v * half), QPointF(x, mid + v * half))

    def _paint_cues(self, p, c, fm) -> None:
        r = self._row_rect("subs")
        if r is None:
            return
        if not self._cues and self._clips:
            p.setPen(c["muted"])
            p.drawText(r, Qt.AlignCenter, self._labels["empty_subs"])
        for i, (rect, (_s, _e, text)) in enumerate(zip(self._cue_rects(), self._cues)):
            sel = self._is_sel("cue", i)
            fill = QColor(c["cue"])
            fill.setAlpha(235 if sel else 170)
            p.setPen(QPen(QColor(c["sel"]), 2) if sel else Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, 5, 5)
            if rect.width() > 18:
                p.setPen(QColor("#141414"))
                inner = rect.adjusted(6, 0, -4, 0)
                p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft,
                           fm.elidedText(text.replace("\n", " "), Qt.ElideRight, inner.width()))

    def _paint_images(self, p, c, fm) -> None:
        r = self._row_rect("images")
        if r is None:
            return
        if not self._images and self._clips:
            p.setPen(c["muted"])
            p.drawText(r, Qt.AlignCenter, self._labels["empty_images"])
        for i, (rect, (_s, _e, name, thumb)) in enumerate(zip(self._image_rects(), self._images)):
            sel = self._is_sel("image", i)
            fill = QColor(c["clip2"])
            fill.setAlpha(235 if sel else 160)
            p.setPen(QPen(QColor(c["sel"]), 2) if sel else Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, 5, 5)
            x = rect.left() + 4
            if thumb is not None and not thumb.isNull() and rect.width() > 30:
                h = rect.height() - 6
                w = min(thumb.width() * h / max(1, thumb.height()), rect.width() - 8)
                p.drawImage(QRectF(x, rect.top() + 3, w, h), thumb)
                x += w + 5
            if rect.right() - x > 16:
                p.setPen(QColor("#141414"))
                inner = QRectF(x, rect.top(), rect.right() - x - 4, rect.height())
                p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft,
                           fm.elidedText(name, Qt.ElideRight, inner.width()))

    def _music_geom(self, k: int) -> tuple[float, float, float, float]:
        """(offset, song start, song end, timeline end) of song *k*,
        following an in-progress drag."""
        m, d = self._music[k], self._drag or {}
        start, end, offset = m["start"], m["end"], m["offset"]
        if d.get("kind", "").startswith("music_") and d.get("row") == k:
            start, end, offset = d["s"], d["e"], d["o"]
        part = max(end - start, 0.01)
        total = self.total()
        stop = total if m["loop"] else min(offset + part, total)
        return offset, start, end, max(stop, offset)

    def _music_rects(self, k: int = 0) -> tuple[QRectF, QRectF] | None:
        """(whole block, first pass of the song part — the one with handles)."""
        r = self._row_rect("music")
        if r is None or not 0 <= k < len(self._music):
            return None
        offset, start, end, stop = self._music_geom(k)
        d = self._drag or {}
        left = offset
        if d.get("kind") == "music_start" and d.get("row") == k:  # the song stays, the handle slides
            left = offset + (start - d["s0"])
        block = QRectF(self._x(left), r.top() + 3, max(4.0, (stop - offset) * self._pps()),
                       r.height() - 6)
        first = QRectF(block.left(), block.top(),
                       min(block.width(), max(4.0, (end - start) * self._pps())), block.height())
        return block, first

    def _paint_music(self, p, c, fm, total: float) -> None:
        r = self._row_rect("music")
        if r is None:
            return
        if not self._music:
            if self._clips:
                p.setPen(c["muted"])
                p.drawText(r, Qt.AlignCenter, self._labels["empty_music"])
            return
        if total <= 0:
            return
        selected = self._selection[1] if self._selection and self._selection[0] == "music" \
            else None
        # the selected song last, so it sits on top where songs overlap
        order = [k for k in range(len(self._music)) if k != selected]
        if selected is not None and selected < len(self._music):
            order.append(selected)
        for k in order:
            self._paint_song(p, c, fm, k, k == selected or ("music", k) in self._picked)

    def _paint_song(self, p, c, fm, k: int, sel: bool) -> None:
        block, first = self._music_rects(k)
        offset, start, end, _stop = self._music_geom(k)
        m, d = self._music[k], self._drag or {}
        dur, loop = m["dur"], m["loop"]
        dragging = d.get("kind", "").startswith("music_") and d.get("row") == k
        base = QColor(c["music"] if k % 2 == 0 else c["accent"])
        # the whole song, faint, so it's clear how far the handles can go
        if dur and (sel or dragging):
            ghost_left = self._x(offset - d["s0"]) if dragging and d["kind"] == "music_start" \
                else self._x(offset - start)
            ghost = QColor(base)
            ghost.setAlpha(40)
            p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 90), 1, Qt.DashLine))
            p.setBrush(ghost)
            p.drawRoundedRect(QRectF(ghost_left, block.top() + 3, dur * self._pps(),
                                     block.height() - 6), 5, 5)
        p.setPen(QPen(QColor(c["sel"]), 2) if sel else QPen(QColor(base).lighter(130), 1))
        p.setBrush(QColor(base).darker(250))
        p.drawRoundedRect(block, 6, 6)
        wave = m.get("wave") or []
        part = max(end - start, 0.01)
        if wave and dur:
            p.save()
            p.setClipRect(block, Qt.IntersectClip)
            x0, seg_w = block.left(), part * self._pps()
            while x0 < block.right():  # the kept part repeats where the song loops
                self._wave(p, QRectF(x0, block.top() + 2, seg_w, block.height() - 4),
                           wave, (start, end), dur, base)
                x0 += seg_w
                if loop and x0 < block.right():
                    p.setPen(QPen(QColor(255, 255, 255, 110), 1, Qt.DashLine))
                    p.drawLine(QPointF(x0, block.top() + 2), QPointF(x0, block.bottom() - 2))
                if not loop:
                    break
            p.restore()
        fade = m.get("fade", 0.0)
        if fade > 0:  # fade ramps at the song's edges
            p.save()
            p.setClipRect(block, Qt.IntersectClip)
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
            fw = fade * self._pps()
            p.drawLine(QPointF(first.left(), first.bottom() - 2),
                       QPointF(first.left() + fw, first.top() + 2))
            if not loop:
                p.drawLine(QPointF(first.right() - fw, first.top() + 2),
                           QPointF(first.right(), first.bottom() - 2))
            p.restore()
        # in / out handles on the first pass of the song part
        hover = self._hover is not None and self._hover[:2] == ("music", k)
        if sel or hover or dragging:
            for x, left_edge in ((first.left(), True), (first.right(), False)):
                grip = QRectF(x if left_edge else x - 8, first.top(), 8, first.height())
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["sel"]))
                p.drawRoundedRect(grip, 3, 3)
        p.setPen(QColor("#ffffff"))
        label = ("↻ " if loop else "") + m["name"]
        if dragging:
            label = f"{fmt_time(start)} – {fmt_time(end)}  @ {fmt_time(offset)}"
        inner = block.adjusted(12, 0, -10, 0)
        p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(label, Qt.ElideRight, inner.width()))

    # hit testing -----------------------------------------------------------

    def _hit(self, pos: QPointF) -> tuple[str, int, str] | None:
        for i in range(len(self._clips)):
            row = self._row_rect("clip", i)
            if not row.adjusted(-self.HEADER_W, 0, 0, 0).contains(pos):
                continue
            if pos.x() < self.HEADER_W:
                if self._clips[i].has_audio and self._mute_rect(i).contains(pos):
                    return "clip", i, "mute"
                return "clip", i, "header"
            rect = self._clip_rect(i)
            if abs(pos.x() - rect.left()) <= self.EDGE:
                return "clip", i, "start"
            if abs(pos.x() - rect.right()) <= self.EDGE:
                return "clip", i, "end"
            if rect.contains(pos):
                return "clip", i, "body"
            return "clip", i, "row"
        for i, rect in enumerate(self._cue_rects()):
            if rect.adjusted(-6, 0, 6, 0).contains(pos):
                if abs(pos.x() - rect.left()) <= 6:
                    return "cue", i, "start"
                if abs(pos.x() - rect.right()) <= 6:
                    return "cue", i, "end"
                return "cue", i, "body"
        for i, rect in enumerate(self._image_rects()):
            if rect.adjusted(-6, 0, 6, 0).contains(pos):
                if abs(pos.x() - rect.left()) <= 6:
                    return "image", i, "start"
                if abs(pos.x() - rect.right()) <= 6:
                    return "image", i, "end"
                return "image", i, "body"
        songs = [(k, self._music_rects(k)) for k in reversed(range(len(self._music)))]
        songs = [(k, rects) for k, rects in songs if rects is not None]
        sel = self._selection[1] if self._selection and self._selection[0] == "music" else None
        songs.sort(key=lambda item: item[0] != sel)  # the selected (top-most) song first
        for k, (block, first) in songs:  # handles win over the bodies of other songs
            if block.adjusted(-6, 0, 6, 0).contains(pos):
                if abs(pos.x() - first.left()) <= self.EDGE:
                    return "music", k, "start"
                if abs(pos.x() - first.right()) <= self.EDGE:
                    return "music", k, "end"
        for k, (block, _first) in songs:
            if block.contains(pos):
                return "music", k, "body"
        return None

    # mouse -------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        hit = self._hit(pos) if pos.y() > self.RULER_H else None
        if hit is not None and hit[2] not in ("row", "mute") \
                and event.modifiers() & Qt.ControlModifier:
            self.item_toggled.emit(hit[0], hit[1])  # add to / remove from the selection
            return
        if hit is None or hit[2] == "row":
            if pos.y() > self.RULER_H and pos.x() > self.HEADER_W:
                # empty track space: a drag draws a selection box, a click seeks
                self._drag = {"kind": "box", "x0": pos.x(), "y0": pos.y(), "x": pos.x(),
                              "y": pos.y(), "row": hit[1] if hit else None, "active": False}
                return
            if hit is not None:
                self.clip_selected.emit(hit[1])
            self._drag = {"kind": "seek"}
            self.seek_requested.emit(self._t(pos.x()))
            return
        kind, i, part = hit
        if part == "mute":
            self.clip_mute_toggled.emit(i)
            return
        # selecting moves the playhead into the item; snap to where it was
        head = self._playhead
        if kind == "clip":
            s, e = self._clips[i].span()
            base = {"row": i, "pps": self._pps(), "offsets": self.offsets(), "head": head,
                    "s0": s, "e0": e, "s": s, "e": e, "x0": pos.x(), "y": pos.y()}
            if part in ("start", "end"):
                self._drag = {**base, "kind": f"trim_{part}", "last_x": pos.x(),
                              "raw": s if part == "start" else e, "overshoot": 0.0}
            else:
                self._drag = {**base, "kind": "reorder", "active": False}
            self.clip_selected.emit(i)
        elif kind == "cue":
            s, e, _txt = self._cues[i]
            self._drag = {"kind": f"cue_{part}", "row": i, "x0": pos.x(), "s": s, "e": e,
                          "s0": s, "e0": e, "head": head}
            self._drag["lanes"] = self._cue_lanes()  # lines keep their lane while dragging
            self._drag["group"] = self._group_of("cue", i, part)
            self.cue_selected.emit(i)
        elif kind == "image":
            s, e, _n, _t = self._images[i]
            self._drag = {"kind": f"img_{part}", "row": i, "x0": pos.x(), "s": s, "e": e,
                          "s0": s, "e0": e, "head": head}
            self._drag["lanes"] = self._image_lanes()
            self._drag["group"] = self._group_of("image", i, part)
            self.image_selected.emit(i)
        else:
            m = self._music[i]
            self._drag = {"kind": f"music_{part}", "row": i, "x0": pos.x(), "pps": self._pps(),
                          "s0": m["start"], "e0": m["end"], "o0": m["offset"],
                          "s": m["start"], "e": m["end"], "o": m["offset"], "head": head}
            self.music_selected.emit(i)
        self.update()

    def _group_of(self, kind: str, i: int, part: str) -> list[tuple[str, int, float, float]]:
        """Other picked subtitles / pictures that move along with this one."""
        if part != "body" or (kind, i) not in self._picked and self._selection != (kind, i):
            return []
        out = []
        for k, j in self._picked:
            if (k, j) == (kind, i):
                continue
            if k == "cue" and j < len(self._cues):
                out.append((k, j, self._cues[j][0], self._cues[j][1]))
            elif k == "image" and j < len(self._images):
                out.append((k, j, self._images[j][0], self._images[j][1]))
        return out

    def _items_in(self, box: QRectF) -> list[tuple[str, int]]:
        items = [("clip", i) for i in range(len(self._clips)) if self._clip_rect(i).intersects(box)]
        items += [("cue", i) for i, r in enumerate(self._cue_rects()) if r.intersects(box)]
        items += [("image", i) for i, r in enumerate(self._image_rects()) if r.intersects(box)]
        for k in range(len(self._music)):
            rects = self._music_rects(k)
            if rects is not None and rects[0].intersects(box):
                items.append(("music", k))
        return items

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position()
        hit = self._hit(pos)
        if (hit is not None and hit[2] != "row") or pos.y() <= self.RULER_H:
            return
        for kind, i, _h in self._rows():
            r = self._row_rect(kind, i)
            if r is not None and r.adjusted(-self.HEADER_W, 0, 0, 0).contains(pos):
                if kind in ("empty", "clip"):
                    self.add_media_requested.emit()
                elif kind == "images" and self.total() > 0:
                    self.image_add_requested.emit(self._t(pos.x()))
                elif kind == "subs" and self.total() > 0:
                    self.cue_add_requested.emit(self._t(pos.x()))
                elif kind == "music":
                    self.music_requested.emit()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        d = self._drag
        if d is None:
            hit = self._hit(pos) if pos.y() > self.RULER_H else None
            if hit != self._hover:
                self._hover = hit
                self.update()
            self.setToolTip(self._tooltip(hit))
            if hit and hit[2] == "mute":
                self.setCursor(QCursor(_HAND))
            elif hit and hit[2] in ("start", "end"):
                self.setCursor(QCursor(Qt.SizeHorCursor))
            elif hit and hit[0] == "clip" and hit[2] == "body":
                self.setCursor(QCursor(Qt.SizeVerCursor if len(self._clips) > 1
                                       else Qt.ArrowCursor))
            elif hit and hit[0] in ("cue", "music", "image"):
                self.setCursor(QCursor(Qt.OpenHandCursor))
            else:
                self.setCursor(QCursor(_HAND))
            return
        kind = d["kind"]
        if kind == "seek":
            self.seek_requested.emit(self._t(pos.x()))
            return
        if kind == "box":
            d["x"], d["y"] = pos.x(), pos.y()
            d["active"] = d["active"] or abs(d["x"] - d["x0"]) + abs(d["y"] - d["y0"]) > 6
            self.update()
            return
        if kind == "reorder":
            if not d["active"] and abs(pos.y() - d["y"]) > 8 and len(self._clips) > 1:
                d["active"] = True
            d["y"] = pos.y() if d["active"] else d["y"]
            self.update()
            return
        dt = (pos.x() - d["x0"]) / self._pps()
        free = bool(event.modifiers() & Qt.AltModifier)
        if kind in ("trim_start", "trim_end"):
            self._trim_move(pos.x(), event.modifiers())
            return
        if kind.startswith("music_"):
            self._music_move(dt, free)
            return
        total = self.total()  # subtitle / picture move / resize
        image = kind.startswith("img_")
        targets = [0.0, total, d["head"], *self.offsets(),
                   *self._cue_edges(None if image else d["row"]),
                   *(v for k, (s0, e0, _n, _t) in enumerate(self._images)
                     if not (image and k == d["row"]) for v in (s0, e0))]
        kind = "cue_" + kind[4:] if image else kind
        s, e = d["s0"], d["e0"]
        if kind == "cue_body":
            length = e - s
            s = min(max(0.0, s + dt), max(0.0, total - length))
            s1, g1 = self._snap(s, targets, free=free)
            e2, g2 = self._snap(s + length, targets, free=free)
            if g2 is not None and (g1 is None or abs(e2 - s - length) < abs(s1 - s)):
                s, d["snap"] = e2 - length, g2
            else:
                s, d["snap"] = s1, g1
            s = min(max(0.0, s), max(0.0, total - length))
            e = s + length
        elif kind == "cue_start":
            s, d["snap"] = self._snap(s + dt, targets, free=free)
            s = min(max(0.0, s), e - 0.3)
        else:
            e, d["snap"] = self._snap(e + dt, targets, free=free)
            e = max(min(total, e), s + 0.3)
        d["s"], d["e"] = round(s, 2), round(e, 2)
        row = d["row"]
        if image:
            self._images[row] = (d["s"], d["e"], *self._images[row][2:])
        else:
            self._cues[row] = (d["s"], d["e"], self._cues[row][2])
        if d.get("group"):  # the rest of the selection moves by as much
            delta = d["s"] - d["s0"]
            low = min(g[2] for g in d["group"])
            delta = max(delta, -low)  # nothing goes before 0:00
            d["delta"] = delta
            for k, j, s0, e0 in d["group"]:
                if k == "cue":
                    self._cues[j] = (round(s0 + delta, 2), round(e0 + delta, 2), self._cues[j][2])
                else:
                    self._images[j] = (round(s0 + delta, 2), round(e0 + delta, 2),
                                       *self._images[j][2:])
        self.update()

    def _tooltip(self, hit: tuple[str, int, str] | None) -> str:
        """Full file name over a clip's row header or block (names are elided)."""
        if not hit or hit[0] != "clip":
            return ""
        clip = self._clips[hit[1]]
        if hit[2] == "mute":
            return self._labels["unmute" if clip.muted else "mute"]
        if hit[2] in ("header", "body"):
            speed = f"  ·  {clip.speed:g}×" if clip.speed != 1.0 else ""
            return f"{clip.name}\n{fmt_time(clip.kept())} / {fmt_time(clip.length)}{speed}"
        return ""

    def _music_move(self, dt: float, free: bool) -> None:
        """Music drags: the handles choose the part of the song (in / out),
        the body moves when it comes in on the timeline."""
        d = self._drag
        dur = self._music[d["row"]]["dur"] or 1e9
        if d["kind"] == "music_start":
            d["s"] = round(min(max(0.0, d["s0"] + dt), d["e0"] - MIN_MUSIC), 2)
        elif d["kind"] == "music_end":
            d["e"] = round(max(min(dur, d["e0"] + dt), d["s0"] + MIN_MUSIC), 2)
        else:
            total = self.total()
            targets = [0.0, d["head"], *self.offsets(), *self._cue_edges()]
            o, d["snap"] = self._snap(max(0.0, d["o0"] + dt), targets, free=free)
            d["o"] = round(min(max(0.0, o), max(0.0, total - MIN_MUSIC)), 2)
        self.update()

    # trimming ----------------------------------------------------------------

    def _trim_move(self, x: float, mods) -> None:
        """Move the dragged handle by the mouse's movement — a tenth as far
        with Shift. Past either edge of the track area the edge timer takes
        over and keeps the clip growing (or shrinking)."""
        d = self._drag
        d["fine"] = bool(mods & Qt.ShiftModifier)
        d["free"] = bool(mods & Qt.AltModifier)
        left, right = self.HEADER_W, self.HEADER_W + self._area_w()
        if left <= x <= right:
            speed = self._clips[d["row"]].speed
            d["raw"] += (x - d["last_x"]) / self._pps() * speed * (0.1 if d["fine"] else 1.0)
            d["overshoot"] = 0.0
            self._edge_timer.stop()
        else:
            d["overshoot"] = x - right if x > right else x - left
            if not self._edge_timer.isActive():
                self._edge_timer.start()
        d["last_x"] = min(max(x, left), right)
        self._apply_trim()

    def _edge_tick(self) -> None:
        d = self._drag
        if not d or d.get("kind") not in ("trim_start", "trim_end") or not d["overshoot"]:
            self._edge_timer.stop()
            return
        over = d["overshoot"]
        px = (abs(over) / 6 + 2) * (1 if over > 0 else -1)  # faster the further out
        speed = self._clips[d["row"]].speed
        d["raw"] += px / self._pps() * speed * (0.1 if d.get("fine") else 1.0)
        self._apply_trim()

    def _apply_trim(self) -> None:
        d = self._drag
        clip = self._clips[d["row"]]
        sp = clip.speed
        # while dragging, source time v sits at timeline time off + v / speed
        off = d["offsets"][d["row"]] - d["s0"] / sp
        targets = [d["head"], *self._cue_edges()]
        start = d["kind"] == "trim_start"
        lo, hi = (0.0, d["e0"] - MIN_CLIP) if start else (d["s0"] + MIN_CLIP, clip.length)
        d["raw"] = min(max(d["raw"], lo), hi)
        at, d["snap"] = self._snap(off + d["raw"] / sp, targets, free=d.get("free", False))
        value = round(min(max((at - off) * sp, lo), hi), 2)
        d["s" if start else "e"] = value
        # keep the moving handle on screen: squeeze the scale (end) or slide
        # the view (start) instead of letting it run off the edge
        right = self.HEADER_W + self._area_w() - 8
        at_t = off + value / sp
        if self._x(at_t) > right and at_t - self._view > 0:
            d["pps"] = (right - self.HEADER_W) / (at_t - self._view)
        if self._x(at_t) < self.HEADER_W + 8:
            self._view = at_t - 8 / self._pps()
        self.update()
        self.clip_trimming.emit(d["row"], d["s"], d["e"], d["kind"][5:])

    def mouseReleaseEvent(self, _event) -> None:
        self._edge_timer.stop()
        d, self._drag = self._drag, None
        if not d:
            return
        kind = d["kind"]
        if kind == "box":
            if d["active"]:
                box = QRectF(QPointF(min(d["x0"], d["x"]), min(d["y0"], d["y"])),
                             QPointF(max(d["x0"], d["x"]), max(d["y0"], d["y"])))
                self.box_selected.emit(self._items_in(box))
            else:  # just a click: as before, select the row's clip and seek
                if d["row"] is not None:
                    self.clip_selected.emit(d["row"])
                self.seek_requested.emit(self._t(d["x0"]))
            self.update()
            return
        if d.get("group") and d.get("delta"):
            self.group_moved.emit(d["delta"])
        moved = d.get("active") if kind == "reorder" else (
            (d.get("s"), d.get("e"), d.get("o")) != (d.get("s0"), d.get("e0"), d.get("o0")))
        if not moved and "row" in d:
            item = ("clip" if kind in ("reorder", "trim_start", "trim_end") else
                    "cue" if kind.startswith("cue_") else
                    "image" if kind.startswith("img_") else "music")
            self.item_clicked.emit(item, d["row"])
        if kind == "reorder" and d["active"]:
            dest = self._reorder_target(d["y"])
            if dest != d["row"]:
                self.clip_moved.emit(d["row"], dest)
        elif kind in ("trim_start", "trim_end"):
            self.clip_trimmed.emit(d["row"], d["s"], d["e"])
        elif kind.startswith("music_") and (d["s"], d["e"], d["o"]) != (d["s0"], d["e0"], d["o0"]):
            self.music_changed.emit(d["row"], d["s"], d["e"], d["o"])
        elif kind.startswith("img_") and (d["s"], d["e"]) != (d["s0"], d["e0"]):
            self.image_timing.emit(d["row"], d["s"], d["e"])
        elif kind.startswith("cue_") and (d["s"], d["e"]) != (d["s0"], d["e0"]):
            self.cue_changed.emit(d["row"], d["s"], d["e"])
        self.setCursor(QCursor(_HAND))
        self.update()


# ── the page ──────────────────────────────────────────────────────────────


class StudioPage(QWidget):
    """Editor workspace. Talks to the main window through *host*:
    ``host.t``, ``host.icon``, ``host.log``, ``host.pick_*``, ``host.ffmpeg_ok``,
    ``host.default_output_dir``."""

    render_requested = Signal(str, dict)  # worker task name, kwargs
    cancel_requested = Signal()  # stop the running job (auto captions)

    INSP_PROJECT, INSP_CUE, INSP_MUSIC, INSP_CLIP, INSP_IMAGE = range(5)

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self._clips: list[_MediaClip] = []
        self._cues: list[SubtitleCue] = []
        self._songs: list[_Song] = []  # background music, in timeline order of adding
        self._images: list[ImageOverlay] = []  # pictures over the video
        # multi-select: everything picked together with the main selection
        # (empty when only one thing is selected); Ctrl+C keeps copies here
        self._picked: set[tuple[str, int]] = set()
        self._keep_picked = False
        self._clipboard: dict | None = None
        self._sel: tuple[str, int] | None = None
        self._export = "auto"  # key of EXPORT_PRESETS
        self._busy = False
        self._busy_job = "render"  # or "captions"
        self._i18n: list[tuple[object, str, str]] = []
        # probed media by path, so undo / redo / open never re-probe a file
        self._media: dict[str, _MediaClip] = {}
        self._music_media: dict[str, tuple[dict, list[float]]] = {}
        self._history: list[dict] = []
        self._hist_pos = -1
        self._last_edit = ("", 0.0)  # (kind, time) of the last recorded edit
        self._restoring = False
        self._project_path = ""
        self._saved_state: dict | None = None
        # a recovery copy of unsaved work, written now and then (see autosave())
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()
        self._build()
        self._wire_shortcuts()
        self._on_mode()  # show the controls for the starting mode
        self._reset_history()

    # helpers -------------------------------------------------------------

    def t(self, key: str, **kw) -> str:
        return self.host.t(key, **kw)

    def _tr(self, widget, key: str, method: str = "setText"):
        self._i18n.append((widget, key, method))
        getattr(widget, method)(self.t(key))
        return widget

    def _btn(self, key: str, slot, tip: str | None = None, obj: str = "secondary") -> QPushButton:
        b = QPushButton()
        b.setObjectName(obj)
        b.setCursor(QCursor(_HAND))
        b.clicked.connect(slot)
        self._tr(b, key)
        if tip:
            self._tr(b, tip, "setToolTip")
        return b

    def _label(self, key: str, obj: str | None = None) -> QLabel:
        lbl = QLabel()
        if obj:
            lbl.setObjectName(obj)
        lbl.setWordWrap(obj == "hint")
        return self._tr(lbl, key)

    @staticmethod
    def _panel() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("panel")
        w.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        return w, lay

    def is_video(self) -> bool:
        return self.mode_video.isChecked()

    # construction --------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(self._build_toolbar())
        top = QSplitter(Qt.Horizontal)
        top.setChildrenCollapsible(False)
        top.setHandleWidth(8)
        viewer, vl = self._panel()
        self.preview = StudioPreview()
        self.preview.cue_moved.connect(self._on_cue_moved)
        self.preview.cue_clicked.connect(self.select_cue)
        self.preview.pan_dragged.connect(self._on_pan_dragged)
        self.preview.image_clicked.connect(self.select_image)
        self.preview.image_changed.connect(self._on_image_placed)
        self.preview.position_changed.connect(self.track_playhead)
        vl.addWidget(self.preview)
        top.addWidget(viewer)
        top.addWidget(self._build_inspector())
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 0)
        top.setSizes([880, 350])
        root.addWidget(top, stretch=1)
        root.addWidget(self._build_timeline())

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(10)
        seg = QWidget()
        seg.setObjectName("segmented")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(4)
        self.mode_video = QPushButton()
        self.mode_audio = QPushButton()
        for b, key in ((self.mode_video, "Video montage"), (self.mode_audio, "Music medley")):
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.setIconSize(QSize(16, 16))
            self._tr(b, key)
            sl.addWidget(b)
        self.mode_video.setChecked(True)
        self.mode_video.toggled.connect(lambda _c: self._on_mode())
        lay.addWidget(seg)
        self.project_btn = QPushButton()
        self.project_btn.setObjectName("secondary")
        self.project_btn.setCursor(QCursor(_HAND))
        self._tr(self.project_btn, "Project")
        self.project_menu = QMenu(self)
        self.project_menu.aboutToShow.connect(self._fill_project_menu)
        self.project_btn.setMenu(self.project_menu)
        lay.addWidget(self.project_btn)
        self.undo_btn = self._btn("", self.undo, "Undo (Ctrl+Z)")
        self.redo_btn = self._btn("", self.redo, "Redo (Ctrl+Y)")
        for b in (self.undo_btn, self.redo_btn):
            b.setFixedWidth(40)
            b.setIconSize(QSize(18, 18))
            lay.addWidget(b)
        self.project_lbl = QLabel()
        self.project_lbl.setObjectName("status")
        lay.addWidget(self.project_lbl)
        lay.addStretch()
        self.status = QLabel()
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(170)
        lay.addWidget(self.progress)
        self.render_btn = QPushButton()
        self.render_btn.setObjectName("primary")
        self.render_btn.setProperty("compact", True)
        self.render_btn.setFixedHeight(42)
        self.render_btn.setMinimumWidth(170)
        self.render_btn.setCursor(QCursor(_HAND))
        self.render_btn.clicked.connect(self.render)
        self._tr(self.render_btn, "tooltip_action_studio", "setToolTip")
        lay.addWidget(self.render_btn)
        return bar

    def _build_timeline(self) -> QWidget:
        panel, lay = self._panel()
        lay.setContentsMargins(8, 8, 8, 6)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self._btn("＋ Media…", self._add_dialog, "Add video or music files"))
        self.split_btn = self._btn("✂ Split", self.split_clip,
                                   "Split the clip under the playhead in two (S)")
        bar.addWidget(self.split_btn)
        self.add_sub_btn = self._btn("＋ Subtitle", self._add_cue,
                                     "Add a subtitle line at the playhead")
        self.captions_btn = self._btn("Auto captions…", self.auto_captions,
                                      "Turn the speech in the clips into subtitle lines")
        self.image_btn = self._btn("＋ Image…", self._browse_images,
                                   "Show a picture over the video from the playhead")
        self.music_btn = self._btn("♪ Music…", self._browse_music, "Add background music")
        self.combine_btn = self._btn("Two videos…", self.combine_videos,
                                     "Play two videos at the same time, for example side by side")
        for b in (self.add_sub_btn, self.captions_btn, self.image_btn, self.music_btn,
                  self.combine_btn):
            bar.addWidget(b)
        bar.addStretch()
        self.total_lbl = QLabel()
        self.total_lbl.setObjectName("total_lbl")
        bar.addWidget(self.total_lbl)
        bar.addSpacing(8)
        for key, slot, tip in (("−", lambda: self.zoom_timeline(1 / 1.5), "Zoom out (Ctrl+−)"),
                               ("+", lambda: self.zoom_timeline(1.5), "Zoom in (Ctrl++)"),
                               ("Fit", self.fit_timeline, "Fit the whole project (Ctrl+0)")):
            b = self._btn(key, slot, tip)
            b.setFixedWidth(40 if key != "Fit" else 52)
            bar.addWidget(b)
        keys = self._btn("?", self.show_shortcuts, "Keyboard shortcuts")
        keys.setFixedWidth(40)
        bar.addWidget(keys)
        bar.addSpacing(8)
        for key, slot, tip in (("▲", lambda: self._move_clip(-1), "Move up"),
                               ("▼", lambda: self._move_clip(1), "Move down"),
                               ("✕", self._delete_selected, "Delete selected (Del)")):
            b = self._btn(key, slot, tip)
            b.setFixedWidth(40)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.track = TrackTimeline()
        self.thumbs = ThumbCache(self)
        self.track.set_thumb_cache(self.thumbs)
        self.track.seek_requested.connect(self._on_track_seek)
        self.track.clip_selected.connect(self.select_clip)
        self.track.clip_trimming.connect(self._on_clip_trimming)
        self.track.clip_trimmed.connect(self._on_clip_trimmed)
        self.track.clip_moved.connect(self._on_clip_moved)
        self.track.clip_mute_toggled.connect(self.toggle_mute)
        self.track.cue_selected.connect(self.select_cue)
        self.track.cue_changed.connect(self._on_cue_dragged)
        self.track.cue_add_requested.connect(self._add_cue_at)
        self.track.image_selected.connect(self.select_image)
        self.track.image_timing.connect(self._on_image_timing)
        self.track.image_add_requested.connect(lambda t: self._browse_images(at=t))
        self.track.music_selected.connect(self.select_music)
        self.track.music_changed.connect(self._on_music_dragged)
        self.track.item_toggled.connect(self._on_item_toggled)
        self.track.box_selected.connect(self._on_box_selected)
        self.track.group_moved.connect(self._on_group_moved)
        self.track.item_clicked.connect(self._on_item_clicked)
        self.track.add_media_requested.connect(self._add_dialog)
        self.track.music_requested.connect(self._browse_music)
        self.track.view_changed.connect(self._sync_hscroll)
        self.track_scroll = QScrollArea()
        self.track_scroll.setObjectName("page_scroll")
        self.track_scroll.setWidgetResizable(True)
        self.track_scroll.setFrameShape(QFrame.NoFrame)
        self.track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.track_scroll.setWidget(self.track)
        lay.addWidget(self.track_scroll)
        self.hscroll = QScrollBar(Qt.Horizontal)
        self.hscroll.valueChanged.connect(lambda v: self.track.set_view(v / 1000))
        lay.addWidget(self.hscroll)
        self._fit_timeline()
        self._sync_hscroll()
        return panel

    def _sync_hscroll(self) -> None:
        """Mirror the timeline's zoomed view on the scrollbar (ms units)."""
        tl = self.track
        zoomed = tl.zoom() > 1.0
        self.hscroll.setVisible(zoomed)
        if not zoomed:
            return
        self.hscroll.blockSignals(True)
        self.hscroll.setRange(0, int(max(0.0, tl.content_span() - tl.visible_span()) * 1000))
        self.hscroll.setPageStep(max(1, int(tl.visible_span() * 1000)))
        self.hscroll.setSingleStep(max(1, int(tl.visible_span() * 100)))
        self.hscroll.setValue(int(tl.view_start() * 1000))
        self.hscroll.blockSignals(False)

    def zoom_timeline(self, factor: float) -> None:
        self.track.set_zoom(self.track.zoom() * factor)

    def fit_timeline(self) -> None:
        self.track.set_zoom(1.0)

    def _fit_timeline(self) -> None:
        """Show every row up to ~6 clips; beyond that the rows scroll."""
        self.track_scroll.setFixedHeight(min(self.track.height(), 340) + 2)

    # inspector -----------------------------------------------------------------

    def _build_inspector(self) -> QWidget:
        panel, lay = self._panel()
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(440)
        self.insp_title = QLabel()
        self.insp_title.setObjectName("panel_title")
        lay.addWidget(self.insp_title)
        self.insp = QStackedWidget()
        for build in (self._build_project_inspector, self._build_cue_inspector,
                      self._build_music_inspector, self._build_clip_inspector,
                      self._build_image_inspector):
            self.insp.addWidget(build())
        lay.addWidget(self.insp, stretch=1)
        return panel

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        return w, lay

    def _build_project_inspector(self) -> QWidget:
        w, lay = self._page()
        # what to make: each preset sets the frame size and the file type
        self.export_cap = self._label("EXPORT AS", "field_cap")
        lay.addWidget(self.export_cap)
        self.export_btns: dict[str, QPushButton] = {}
        self.export_box = self._choice_grid(
            [(k, EXPORT_PRESETS[k][0]) for k in EXPORT_PRESETS], 2, self._set_export,
            self.export_btns)
        lay.addWidget(self.export_box)
        self.export_hint = QLabel()
        self.export_hint.setObjectName("hint")
        self.export_hint.setWordWrap(True)
        lay.addWidget(self.export_hint)
        form = QFormLayout()
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.res = QComboBox()
        self.res.currentIndexChanged.connect(lambda _i: (self._refresh_aspect(),
                                                         self._sync_export()))
        self.res_lbl = self._label("Resolution:")
        form.addRow(self.res_lbl, self.res)
        self.xfade = QDoubleSpinBox()
        self.xfade.setRange(0.0, 10.0)
        self.xfade.setSingleStep(0.5)
        self.xfade.setValue(2.0)
        self.xfade.setSuffix(" s")
        self.afmt = QComboBox()
        for label, ext in (("MP3", ".mp3"), ("M4A (AAC)", ".m4a"), ("WAV", ".wav")):
            self.afmt.addItem(label, ext)
        self.abr = QComboBox()
        for br in ("320", "256", "192", "128"):
            self.abr.addItem(f"{br} kbps", br)
        self.abr.setCurrentIndex(2)
        self.afmt.currentIndexChanged.connect(
            lambda _i: self.abr.setEnabled(self.afmt.currentData() != ".wav"))
        self.xfade_lbl = self._label("Crossfade:")
        self.afmt_lbl = self._label("Format:")
        self.abr_lbl = self._label("Quality:")
        form.addRow(self.xfade_lbl, self.xfade)
        form.addRow(self.afmt_lbl, self.afmt)
        form.addRow(self.abr_lbl, self.abr)
        self.name = QLineEdit()
        form.addRow(self._label("File name:"), self.name)
        lay.addLayout(form)
        self.loud_cb = QCheckBox()
        self.loud_cb.setCursor(QCursor(_HAND))
        self._tr(self.loud_cb, "Even out the loudness")
        self._tr(self.loud_cb, "Brings the whole video to the loudness YouTube and Shorts aim for "
                 "(-14 LUFS), so it is neither too quiet nor too loud. Applied when you render.",
                 "setToolTip")
        self.loud_cb.toggled.connect(lambda _on: self._record())
        lay.addWidget(self.loud_cb)
        lay.addWidget(self._label("Save to:"))
        row = QHBoxLayout()
        self.out_dir = QLineEdit(str(self.host.default_output_dir()))
        row.addWidget(self.out_dir, stretch=1)
        b = self._btn("…", self._browse_out, "Browse…")
        b.setFixedWidth(40)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _set_export(self, preset: str) -> None:
        self._export = preset
        res = EXPORT_PRESETS[preset][1]
        if res is not None:
            self.res.blockSignals(True)
            self.res.setCurrentIndex(max(0, self.res.findData(res)))
            self.res.blockSignals(False)
            self._refresh_aspect()
        self._sync_export()
        self._record()

    def _sync_export(self) -> None:
        """Highlight the preset that matches; say what to watch out for."""
        if not hasattr(self, "export_btns"):
            return
        preset = getattr(self, "_export", "youtube")
        res = self.res.currentData() or "auto"
        if EXPORT_PRESETS[preset][1] not in (None, res):  # resolution changed by hand
            preset = next((k for k, v in EXPORT_PRESETS.items()
                           if v[1] == res and v[2] == ".mp4"), "youtube")
            self._export = preset
        self.export_btns[preset].setChecked(True)
        total = self.track.total()
        hint = ""
        if preset == "shorts" and total > 60:
            hint = self.t("Shorts, Reels and TikTok videos are at most 60 s; this one is {d}.",
                          d=fmt_time(total))
        elif preset == "gif":
            hint = self.t("A GIF has no sound and gets large quickly: best for a few seconds "
                          "({d} now).", d=fmt_time(total))
        elif preset == "audio":
            hint = self.t("Only the sound: clips, music and their levels, as an MP3.")
        self.export_hint.setText(hint)
        self.export_hint.setVisible(bool(hint))

    def _build_cue_inspector(self) -> QWidget:
        """Two tabs, so nothing needs scrolling: *Line* (the selected line's
        text, timing, position, split / duplicate) and *Style* (shared by
        every line). Colours are swatches, the default position two buttons."""
        page, outer = self._page()
        tabs = QWidget()
        tabs.setObjectName("segmented")
        tabs.setAttribute(Qt.WA_StyledBackground, True)
        tl = QHBoxLayout(tabs)
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(4)
        self.cue_tabs = QStackedWidget()
        self.cue_tab_btns: list[QPushButton] = []
        for i, key in enumerate(("Line", "Effects", "All lines")):
            b = QPushButton()
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, k=i: self.cue_tabs.setCurrentIndex(k))
            self._tr(b, key)
            tl.addWidget(b, stretch=1)
            self.cue_tab_btns.append(b)
        self.cue_tab_btns[0].setChecked(True)
        outer.addWidget(tabs)
        self.cue_tabs.addWidget(self._build_line_tab())
        self.cue_tabs.addWidget(self._build_effects_tab())
        self.cue_tabs.addWidget(self._build_style_tab())
        outer.addWidget(self.cue_tabs, stretch=1)
        return page

    def _scroll(self, inner: QWidget) -> QScrollArea:
        """Fallback scrolling for very short windows."""
        scroll = QScrollArea()
        scroll.setObjectName("page_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _build_line_tab(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        head = QHBoxLayout()
        head.addWidget(self._label("Text:"), stretch=1)
        head.addWidget(self._btn("Paste", self._paste_text, "Paste text from the clipboard"))
        lay.addLayout(head)
        self.cue_text = QPlainTextEdit()
        self.cue_text.setFixedHeight(64)
        self.cue_text.textChanged.connect(self._edit_cue_text)
        lay.addWidget(self.cue_text)
        times = QHBoxLayout()
        times.setSpacing(8)
        self.cue_start = QLineEdit()
        self.cue_end = QLineEdit()
        self.cue_start.editingFinished.connect(lambda: self._edit_cue_time("start"))
        self.cue_end.editingFinished.connect(lambda: self._edit_cue_time("end"))
        times.addWidget(self._label("Start:"))
        times.addWidget(self.cue_start, stretch=1)
        times.addWidget(self._label("End:"))
        times.addWidget(self.cue_end, stretch=1)
        lay.addLayout(times)

        # position: 3×3 quick grid (same numbering as ASS \an), or drag in preview
        lay.addWidget(self._label("POSITION", "field_cap"))
        pos_row = QHBoxLayout()
        pos_row.setSpacing(12)
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._anchor_btns: dict[int, QPushButton] = {}
        for r, row_anchors in enumerate(((7, 8, 9), (4, 5, 6), (1, 2, 3))):
            for c, anchor in enumerate(row_anchors):
                b = QPushButton()
                b.setObjectName("anchor_btn")
                b.setCheckable(True)
                b.setFixedSize(34, 24)
                b.setIconSize(QSize(18, 12))
                b.setCursor(QCursor(_HAND))
                b.clicked.connect(lambda _c=False, a=anchor: self._set_anchor(a))
                grid.addWidget(b, r, c)
                self._anchor_btns[anchor] = b
        pos_row.addWidget(grid_box)
        pos_col = QVBoxLayout()
        pos_col.setSpacing(6)
        self.cue_pos = QLabel()
        self.cue_pos.setObjectName("hint")
        self.cue_pos.setWordWrap(True)
        pos_col.addWidget(self.cue_pos)
        pos_col.addWidget(self._btn("Reset position", self._reset_cue_pos))
        pos_col.addWidget(self._btn("Use for all", self._apply_pos_all,
                                    "Use this position for all lines"))
        pos_col.addStretch()
        pos_row.addLayout(pos_col, stretch=1)
        lay.addLayout(pos_row)
        lay.addWidget(self._label("Or drag the text in the preview.", "hint"))
        lay.addWidget(self._label("EDIT", "field_cap"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._btn("✂ Split at playhead", self._split_cue,
                                "Cut this line in two at the playhead"))
        row.addWidget(self._btn("Duplicate", self._duplicate_cue,
                                "Copy this line right after itself"))
        lay.addLayout(row)
        lay.addStretch()
        return self._scroll(inner)

    def _build_effects_tab(self) -> QWidget:
        """This line only: how it comes on screen, and (optionally) its own
        colours / size over the shared style."""
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        lay.addWidget(self._label("ANIMATION", "field_cap"))
        self.cue_anim_btns: dict[str, QPushButton] = {}
        lay.addWidget(self._choice_grid(
            [(k, ANIMATION_LABELS[k]) for k in ANIMATIONS], 3, self._set_cue_animation,
            self.cue_anim_btns))
        lay.addWidget(self._btn("Use this animation for every line", self._animation_for_all))
        lay.addSpacing(4)
        lay.addWidget(self._label("OWN LOOK", "field_cap"))
        self.own_look = QCheckBox()
        self.own_look.setCursor(QCursor(_HAND))
        self._tr(self.own_look, "Give this line its own look")
        self.own_look.toggled.connect(self._own_look_toggled)
        lay.addWidget(self.own_look)
        self.own_box = QWidget()
        ob = QVBoxLayout(self.own_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(5)
        self.own_color = ColorSwatches(TEXT_COLORS, allow_none=False, t=self.t)
        self.own_color.changed.connect(lambda c: self._set_own("color", c))
        ob.addWidget(self._label("Text color:"))
        ob.addWidget(self.own_color)
        self.own_bg = ColorSwatches(BG_COLORS, allow_none=True, t=self.t)
        self.own_bg.changed.connect(lambda c: self._set_own("background", c or None))
        ob.addWidget(self._label("Background:"))
        ob.addWidget(self.own_bg)
        size_row = QHBoxLayout()
        size_row.addWidget(self._label("Size:"))
        self.own_size = QSpinBox()
        self.own_size.setRange(10, 72)
        self.own_size.valueChanged.connect(lambda v: self._set_own("size", v, "own_size"))
        self.own_bold = QCheckBox()
        self.own_bold.setCursor(QCursor(_HAND))
        self._tr(self.own_bold, "Bold")
        self.own_bold.toggled.connect(lambda on: self._set_own("bold", on))
        size_row.addWidget(self.own_size, stretch=1)
        size_row.addWidget(self.own_bold)
        ob.addLayout(size_row)
        lay.addWidget(self.own_box)
        lay.addWidget(self._label(
            "Lines without their own look follow All lines.", "hint"))
        lay.addStretch()
        return self._scroll(inner)

    def _cur_cue(self) -> SubtitleCue | None:
        if self._sel and self._sel[0] == "cue" and 0 <= self._sel[1] < len(self._cues):
            return self._cues[self._sel[1]]
        return None

    def _cue_look_changed(self, kind: str = "") -> None:
        self.preview.set_cues(self._preview_cues(), self._sel[1] if self._cur_cue() else None)
        self._refresh_track()
        self.track.set_selection(self._sel)
        self._fill_effects()
        self._record(kind)

    def _set_cue_animation(self, kind: str) -> None:
        cue = self._cur_cue()
        if cue is not None:
            cue.animation = kind
            self._cue_look_changed()
            self.preview.seek(cue.start + 0.01)  # play it from the start of the line

    def _animation_for_all(self) -> None:
        cue = self._cur_cue()
        if cue is not None:
            for other in self._cues:
                other.animation = cue.animation
            self._cue_look_changed()

    def _own_look_toggled(self, on: bool) -> None:
        cue = self._cur_cue()
        if cue is None or on == bool(cue.look):
            return
        st = self._style()
        cue.look = ({"color": st.color, "background": st.background, "size": st.size,
                     "bold": st.bold} if on else None)
        self._cue_look_changed()

    def _set_own(self, key: str, value, kind: str = "") -> None:
        cue = self._cur_cue()
        if cue is None or not cue.look:
            return
        cue.look = {**cue.look, key: value}
        self._cue_look_changed(kind)

    def _fill_effects(self) -> None:
        cue = self._cur_cue()
        if cue is None:
            return
        self.cue_anim_btns.get(cue.animation, self.cue_anim_btns["none"]).setChecked(True)
        own = bool(cue.look)
        look = cue_style(cue, self._style())
        for w in (self.own_look, self.own_size, self.own_bold):
            w.blockSignals(True)
        self.own_look.setChecked(own)
        self.own_size.setValue(int(look.size))
        self.own_bold.setChecked(bool(look.bold))
        for w in (self.own_look, self.own_size, self.own_bold):
            w.blockSignals(False)
        self.own_color.set_color(look.color)
        self.own_bg.set_color(look.background)
        self.own_box.setEnabled(own)

    def _build_style_tab(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.preset_combo = QComboBox()
        self.preset_combo.setCursor(QCursor(_HAND))
        self.preset_combo.activated.connect(
            lambda _i: self.apply_preset(self.preset_combo.currentData() or ""))
        preset_row.addWidget(self.preset_combo, stretch=1)
        preset_row.addWidget(self._btn("Save\u2026", self._save_preset, "Save as preset\u2026"))
        self.preset_del = self._btn("\u2715", self._delete_preset, "Delete preset")
        self.preset_del.setFixedWidth(40)
        preset_row.addWidget(self.preset_del)
        lay.addLayout(preset_row)

        form = QFormLayout()
        form.setSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sub_font = QComboBox()
        self.sub_font.setCursor(QCursor(_HAND))
        self.sub_font.setMaxVisibleItems(18)
        self.sub_font.currentIndexChanged.connect(lambda _i: self._push_style())
        self.sub_bold = QCheckBox()
        self.sub_bold.setCursor(QCursor(_HAND))
        self.sub_bold.toggled.connect(lambda _c: self._push_style())
        self._tr(self.sub_bold, "Bold")
        self.sub_size = QSpinBox()
        self.sub_size.setRange(10, 72)
        self.sub_size.setValue(24)
        self.sub_size.valueChanged.connect(lambda _v: self._push_style())
        size_row = QHBoxLayout()
        size_row.addWidget(self.sub_size, stretch=1)
        size_row.addWidget(self.sub_bold)
        form.addRow(self._label("Font:"), self.sub_font)
        form.addRow(self._label("Size:"), size_row)
        lay.addLayout(form)

        lay.addWidget(self._label("Text color:"))
        self.sub_color = ColorSwatches(TEXT_COLORS, allow_none=False, t=self.t)
        self.sub_color.changed.connect(lambda _c: self._push_style())
        lay.addWidget(self.sub_color)
        lay.addWidget(self._label("Background:"))
        self.sub_bg = ColorSwatches(BG_COLORS, allow_none=True, t=self.t)
        self.sub_bg.set_color("#000000")
        self.sub_bg.changed.connect(lambda _c: self._push_style())
        lay.addWidget(self.sub_bg)
        self.sub_bg_opacity, op_row = self._level(60)
        self.sub_bg_opacity.setRange(10, 100)
        self.sub_bg_opacity.valueChanged.connect(lambda _v: self._push_style())
        op = QHBoxLayout()
        op.addWidget(self._label("Opacity:"))
        op.addLayout(op_row, stretch=1)
        lay.addLayout(op)

        form2 = QFormLayout()
        form2.setSpacing(9)
        form2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sub_fade = QDoubleSpinBox()
        self.sub_fade.setRange(0.0, 2.0)
        self.sub_fade.setSingleStep(0.1)
        self.sub_fade.setDecimals(1)
        self.sub_fade.setSuffix(" s")
        self.sub_fade.valueChanged.connect(lambda _v: self._push_style())
        form2.addRow(self._label("Fade in / out:"), self.sub_fade)
        pos = QWidget()
        pos.setObjectName("segmented")
        pos.setAttribute(Qt.WA_StyledBackground, True)
        pl = QHBoxLayout(pos)
        pl.setContentsMargins(3, 3, 3, 3)
        pl.setSpacing(3)
        self.sub_pos_btns: dict[str, QPushButton] = {}
        for value, key in (("bottom", "Bottom"), ("top", "Top")):
            b = QPushButton()
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False: self._push_style())
            self._tr(b, key)
            pl.addWidget(b, stretch=1)
            self.sub_pos_btns[value] = b
        self.sub_pos_btns["bottom"].setChecked(True)
        form2.addRow(self._label("Default position:"), pos)
        lay.addLayout(form2)
        lay.addStretch()
        self._fill_fonts()
        return self._scroll(inner)

    def _fill_fonts(self) -> None:
        self.sub_font.blockSignals(True)
        self.sub_font.clear()
        self.sub_font.addItem(f"{SUBTITLE_FONT_NAME} ★", SUBTITLE_FONT_NAME)
        for family in system_fonts():
            if family != SUBTITLE_FONT_NAME:
                self.sub_font.addItem(family, family)
        self.sub_font.setCurrentIndex(0)
        self.sub_font.blockSignals(False)

    def _anchor_icons(self, color: str) -> None:
        for anchor, b in [*self._anchor_btns.items(), *self._image_anchor_btns.items()]:
            pm = QPixmap(18, 12)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(color), 1))
            p.drawRoundedRect(QRectF(0.5, 0.5, 17, 11), 2, 2)
            col, row = (anchor - 1) % 3, (anchor - 1) // 3
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(2 + col * 5, 8 - row * 3.2, 4, 2.4), 1, 1)
            p.end()
            b.setIcon(QIcon(pm))

    def _tab_bar(self, keys: tuple[str, ...]) -> tuple[QWidget, QStackedWidget, list[QPushButton]]:
        """Segmented tabs over a stack of pages (add the pages in the same order)."""
        bar = QWidget()
        bar.setObjectName("segmented")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 4, 4, 4)
        bl.setSpacing(4)
        stack = QStackedWidget()
        buttons = []
        for i, key in enumerate(keys):
            b = QPushButton()
            b.setObjectName("segment")
            b.setProperty("compact", True)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumHeight(32)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, k=i: stack.setCurrentIndex(k))
            self._tr(b, key)
            bl.addWidget(b, stretch=1)
            buttons.append(b)
        buttons[0].setChecked(True)
        return bar, stack, buttons

    def _choice_grid(self, items: list[tuple[str, str]], columns: int, slot,
                     store: dict[str, QPushButton]) -> QWidget:
        """Every option visible as a button (no dropdown); one is checked."""
        box = QWidget()
        box.setObjectName("segmented")
        box.setAttribute(Qt.WA_StyledBackground, True)
        grid = QGridLayout(box)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(4)
        for n, (value, key) in enumerate(items):
            b = QPushButton()
            b.setObjectName("segment")
            b.setProperty("compact", True)
            # share the row equally whatever the label length (the panel is narrow)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumHeight(30)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, v=value: slot(v))
            self._tr(b, key)
            grid.addWidget(b, n // columns, n % columns)
            store[value] = b
        return box

    def _build_clip_inspector(self) -> QWidget:
        """The selected clip: how it comes in (transition) and how it fills
        the output frame (framing)."""
        inner, lay = self._page()
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        back = self._btn("←", self.deselect, "Back to the project settings")
        back.setFixedWidth(36)
        top.addWidget(back)
        self.clip_name = QLabel()
        self.clip_name.setObjectName("info_name")
        self.clip_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.clip_name, stretch=1)
        top.addWidget(self._btn("Zoom to clip", self.zoom_to_clip,
                                "Zoom the timeline to this clip for precise trimming (Z)"))
        lay.addLayout(top)
        outer = lay
        tabs, self.clip_tabs, self.clip_tab_btns = self._tab_bar(
            ("Trim", "Transition", "Picture and sound"))
        outer.addWidget(tabs)
        outer.addWidget(self.clip_tabs, stretch=1)
        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))

        # exact in / out points, nudged by a frame or a second
        cap = QHBoxLayout()
        cap.addWidget(self._label("TRIM", "field_cap"))
        cap.addStretch()
        self.clip_info = QLabel()
        self.clip_info.setObjectName("hint")
        cap.addWidget(self.clip_info)
        lay.addLayout(cap)
        trim = QGridLayout()
        trim.setHorizontalSpacing(4)
        trim.setVerticalSpacing(6)
        self.trim_fields: dict[str, QLineEdit] = {}
        for r, (edge, key) in enumerate((("start", "Start:"), ("end", "End:"))):
            trim.addWidget(self._label(key), r, 0)
            field_ = QLineEdit()
            field_.editingFinished.connect(lambda e=edge: self._trim_typed(e))
            self.trim_fields[edge] = field_
            trim.addWidget(field_, r, 1)
            for c, (text, delta, tip) in enumerate((
                ("−1s", -1.0, "Back 1 second"), ("◀", -FRAME, "Back 1 frame"),
                ("▶", FRAME, "Forward 1 frame"), ("+1s", 1.0, "Forward 1 second"),
            )):
                b = self._btn(text, lambda _c=False, e=edge, dl=delta: self._nudge(e, dl), tip)
                b.setFixedWidth(42 if "s" in text else 32)
                b.setStyleSheet("padding: 0;")
                trim.addWidget(b, r, 2 + c)
        trim.setColumnStretch(1, 1)
        lay.addLayout(trim)
        # speed: the common ones as buttons, any value in the box
        lay.addWidget(self._label("SPEED", "field_cap"))
        speeds = QHBoxLayout()
        speeds.setSpacing(8)
        self.clip_speed = QDoubleSpinBox()
        self.clip_speed.setRange(*SPEED_RANGE)
        self.clip_speed.setSingleStep(0.25)
        self.clip_speed.setDecimals(2)
        self.clip_speed.setSuffix("×")
        self.clip_speed.setFixedWidth(92)
        self.clip_speed.valueChanged.connect(self._set_clip_speed)
        self.speed_btns: dict[float, QPushButton] = {}
        named: dict[str, QPushButton] = {}
        box = self._choice_grid([(f"{v:g}", f"{v:g}×") for v in (0.5, 1.0, 1.5, 2.0)], 4,
                                lambda v: self.clip_speed.setValue(float(v)), named)
        self.speed_btns = {float(k): b for k, b in named.items()}
        speeds.addWidget(box, stretch=1)
        speeds.addWidget(self.clip_speed)
        lay.addLayout(speeds)
        lay.addWidget(self._label(
            "Hold Shift while dragging a handle to trim finely; drag it past the edge to "
            "keep going.", "hint"))
        lay.addStretch()

        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))
        lay.addWidget(self._label("TRANSITION IN", "field_cap"))
        self.trans_btns: dict[str, QPushButton] = {}
        self.trans_box = self._choice_grid(
            [(k, TRANSITION_LABELS[k]) for k in TRANSITIONS], 3, self._set_transition,
            self.trans_btns)
        lay.addWidget(self.trans_box)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.trans_len_lbl = self._label("Duration:")
        row.addWidget(self.trans_len_lbl)
        self.trans_len = QDoubleSpinBox()
        self.trans_len.setRange(0.2, 3.0)
        self.trans_len.setSingleStep(0.1)
        self.trans_len.setDecimals(1)
        self.trans_len.setSuffix(" s")
        self.trans_len.valueChanged.connect(self._set_transition_length)
        row.addWidget(self.trans_len, stretch=1)
        self.trans_all = self._btn("Use for all cuts", self._transition_for_all,
                                   "Use this transition between every pair of clips")
        row.addWidget(self.trans_all)
        lay.addLayout(row)
        self.trans_first = self._label(
            "The first clip opens the video, so it has no transition in.", "hint")
        lay.addWidget(self.trans_first)
        lay.addStretch()

        page, lay = self._page()
        lay.setContentsMargins(0, 6, 4, 0)
        lay.setSpacing(6)
        self.clip_tabs.addWidget(self._scroll(page))
        self.sound_cap = self._label("SOUND", "field_cap")
        lay.addWidget(self.sound_cap)

        self.sound_row = QWidget()
        sr = QHBoxLayout(self.sound_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        self.clip_mute = QCheckBox()
        self.clip_mute.setCursor(QCursor(_HAND))
        self._tr(self.clip_mute, "Mute")
        self.clip_mute.toggled.connect(self._set_muted)
        sr.addWidget(self.clip_mute)
        self.clip_vol = QSlider(Qt.Horizontal)
        self.clip_vol.setObjectName("level_slider")
        self.clip_vol.setRange(0, 200)
        self.clip_vol.setCursor(QCursor(_HAND))
        self.clip_vol_lbl = QLabel("100%")
        self.clip_vol_lbl.setObjectName("level_value")
        self.clip_vol.valueChanged.connect(self._set_clip_volume)
        sr.addWidget(self.clip_vol, stretch=1)
        sr.addWidget(self.clip_vol_lbl)
        lay.addWidget(self.sound_row)
        self.clip_denoise = QCheckBox()
        self.clip_denoise.setCursor(QCursor(_HAND))
        self._tr(self.clip_denoise, "Reduce background noise")
        self._tr(self.clip_denoise, "Takes steady hiss, hum and fan noise out of this clip's sound "
                 "when you render. Speech and music are left alone. The preview does not play it.",
                 "setToolTip")
        self.clip_denoise.toggled.connect(self._set_denoise)
        lay.addWidget(self.clip_denoise)

        self.framing_cap = self._label("FRAMING", "field_cap")
        lay.addWidget(self.framing_cap)
        self.fit_btns: dict[str, QPushButton] = {}
        self.fit_box = self._choice_grid(
            [("fit", "Whole picture"), ("fill", "Fill frame")], 2, self._set_fit, self.fit_btns)
        lay.addWidget(self.fit_box)
        self.zoom_row = QWidget()
        zr = QHBoxLayout(self.zoom_row)
        zr.setContentsMargins(0, 0, 0, 0)
        zr.setSpacing(8)
        zr.addWidget(self._label("Zoom:"))
        self.clip_zoom = QSlider(Qt.Horizontal)
        self.clip_zoom.setObjectName("level_slider")
        self.clip_zoom.setRange(100, 300)
        self.clip_zoom.setCursor(QCursor(_HAND))
        self.clip_zoom_lbl = QLabel("100%")
        self.clip_zoom_lbl.setObjectName("level_value")
        self.clip_zoom.valueChanged.connect(self._set_clip_zoom)
        zr.addWidget(self.clip_zoom, stretch=1)
        zr.addWidget(self.clip_zoom_lbl)
        self.center_btn = self._btn("Center", self._center_clip, "Center the picture again")
        zr.addWidget(self.center_btn)
        lay.addWidget(self.zoom_row)
        self._tr(self.fit_box, "Fill frame crops the picture so there are no black bars. Drag "
                 "the picture in the preview to choose what stays in frame.", "setToolTip")
        self.framing_hint = self._label(
            "Fill frame crops the picture so there are no black bars. Drag the picture "
            "in the preview to choose what stays in frame.", "hint")
        lay.addWidget(self.framing_hint)
        lay.addStretch()
        return inner

    def _sel_clip(self) -> _MediaClip | None:
        if self._sel and self._sel[0] == "clip" and 0 <= self._sel[1] < len(self._clips):
            return self._clips[self._sel[1]]
        return None

    def _fill_clip_inspector(self) -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        i = self._sel[1]
        self.clip_name.setText(QFontMetricsF(self.clip_name.font()).elidedText(
            clip.name, Qt.ElideMiddle, max(80, self.insp.width() - 170)))
        self.clip_name.setToolTip(clip.name)
        self.clip_info.setText(self.t("{used} of {total} used", used=fmt_time(clip.part()),
                                      total=fmt_time(clip.length)))
        for edge, value in zip(("start", "end"), clip.span()):
            if not self.trim_fields[edge].hasFocus():
                self.trim_fields[edge].setText(_fmt_precise(value))
        self.clip_speed.blockSignals(True)
        self.clip_speed.setValue(clip.speed)
        self.clip_speed.blockSignals(False)
        for value, b in self.speed_btns.items():  # none lit for other speeds
            b.setAutoExclusive(False)
            b.setChecked(abs(clip.speed - value) < 1e-6)
            b.setAutoExclusive(True)
        first = i == 0
        for w in (self.trans_box, self.trans_len_lbl, self.trans_len, self.trans_all):
            w.setVisible(not first)
        self.trans_first.setVisible(first)
        self.trans_btns.get(clip.transition, self.trans_btns["none"]).setChecked(True)
        self.trans_len.blockSignals(True)
        self.trans_len.setValue(clip.transition_d)
        self.trans_len.blockSignals(False)
        self.trans_len.setEnabled(clip.transition != "none")
        for w in (self.framing_cap, self.fit_box, self.zoom_row, self.framing_hint):
            w.setVisible(clip.has_video)
        for w in (self.sound_cap, self.sound_row, self.clip_denoise):
            w.setVisible(clip.has_audio)
        for w in (self.clip_mute, self.clip_vol, self.clip_denoise):
            w.blockSignals(True)
        self.clip_denoise.setChecked(clip.denoise)
        self.clip_mute.setChecked(clip.muted)
        self.clip_vol.setValue(round(clip.volume * 100))
        for w in (self.clip_mute, self.clip_vol, self.clip_denoise):
            w.blockSignals(False)
        self.clip_vol.setEnabled(not clip.muted)
        self.clip_denoise.setEnabled(not clip.muted)
        self.clip_vol_lbl.setText(f"{round(clip.volume * 100)}%")
        self.fit_btns[clip.fit].setChecked(True)
        self.clip_zoom.blockSignals(True)
        self.clip_zoom.setValue(round(clip.zoom * 100))
        self.clip_zoom.blockSignals(False)
        self.clip_zoom_lbl.setText(f"{round(clip.zoom * 100)}%")

    def _transitions_changed(self, kind: str = "") -> None:
        pos = self.preview.position()
        self._refresh_track()
        self._reload_preview(min(pos, self.track.total()))
        self.track.set_selection(self._sel)
        self._fill_clip_inspector()
        self._record(kind)

    def _set_clip_speed(self, value: float) -> None:
        clip = self._sel_clip()
        if clip is None or abs(clip.speed - value) < 1e-6:
            return
        # keep the same moment under the playhead where possible
        hit = self._clip_at(self.preview.position())
        clip.speed = round(min(max(value, SPEED_RANGE[0]), SPEED_RANGE[1]), 2)
        self._transitions_changed("speed")
        if hit is not None and hit[0] == self._sel[1]:
            self.preview.seek(self.track.offsets()[hit[0]]
                              + (hit[1] - clip.span()[0]) / clip.speed)

    def _set_transition(self, kind: str) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.transition = kind
            self._transitions_changed()

    def _set_transition_length(self, value: float) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.transition_d = round(value, 2)
            self._transitions_changed("trans_len")

    def _transition_for_all(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            for other in self._clips[1:]:
                other.transition, other.transition_d = clip.transition, clip.transition_d
            self._transitions_changed()

    def _frame_len(self, clip: _MediaClip) -> float:
        fps = float(clip.info.get("fps") or 0)
        return 1 / fps if fps else FRAME

    def _nudge(self, edge: str, delta: float) -> None:
        """Move the selected clip's start or end by *delta* (±1 frame / ±1 s)."""
        clip = self._sel_clip()
        if clip is None:
            return
        if abs(delta) < 0.5:
            delta = self._frame_len(clip) * (1 if delta > 0 else -1)
        s, e = clip.span()
        self._set_clip_span(edge, s + delta if edge == "start" else s,
                            e + delta if edge == "end" else e, f"nudge_{edge}")

    def _trim_typed(self, edge: str) -> None:
        clip = self._sel_clip()
        value = parse_timecode(self.trim_fields[edge].text())
        if clip is None or value is None:
            self._fill_clip_inspector()
            return
        s, e = clip.span()
        self._set_clip_span(edge, value if edge == "start" else s,
                            value if edge == "end" else e)

    def _set_clip_span(self, edge: str, s: float, e: float, kind: str = "") -> None:
        i = self._sel[1]
        self._on_clip_trimmed(i, s, e, kind)
        # show the frame at the edge that moved
        seg = self._segments()[i]
        offset = sum(x.duration for x in self._segments()[:i])
        self.preview.seek(offset if edge == "start" else offset + max(0.0, seg.duration - 0.02))

    def zoom_to_clip(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            off = self.track.offsets()[self._sel[1]]
            self.track.zoom_to(off, off + clip.kept())

    def _sound_changed(self, i: int, kind: str = "") -> None:
        self.preview.set_segment_volume(i, self._clips[i].gain())
        self.track.update()
        if self._sel == ("clip", i) and self.insp.currentIndex() == self.INSP_CLIP:
            self._fill_clip_inspector()
        self._record(kind)

    def _mute_selected(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            self.toggle_mute(self._sel[1])

    def toggle_mute(self, i: int) -> None:
        if 0 <= i < len(self._clips) and self._clips[i].has_audio:
            self._clips[i].muted = not self._clips[i].muted
            self._sound_changed(i)

    def _set_muted(self, on: bool) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.muted = on
            self._sound_changed(self._sel[1])

    def _set_denoise(self, on: bool) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.denoise = on
            self._sound_changed(self._sel[1])

    def _set_clip_volume(self, value: int) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.volume = round(value / 100, 2)
            self._sound_changed(self._sel[1], "clip_volume")

    def _framing_changed(self, kind: str = "") -> None:
        clip = self._sel_clip()
        if clip is None:
            return
        self.preview.set_segment_framing(self._sel[1], clip.fit, clip.zoom, clip.pan_x, clip.pan_y)
        self._update_pan_target()
        self._fill_clip_inspector()
        self._record(kind)

    def _set_fit(self, fit: str) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.fit = fit
            self._framing_changed()

    def _set_clip_zoom(self, value: int) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.zoom = round(value / 100, 2)
            self._framing_changed("zoom")

    def _center_clip(self) -> None:
        clip = self._sel_clip()
        if clip is not None:
            clip.pan_x = clip.pan_y = 0.5
            self._framing_changed()

    def _on_pan_dragged(self, seg: int, x: float, y: float) -> None:
        if 0 <= seg < len(self._clips):
            clip = self._clips[seg]
            clip.pan_x, clip.pan_y = x, y
            self.preview.set_segment_framing(seg, clip.fit, clip.zoom, x, y)
            self._record("pan")

    def _update_pan_target(self) -> None:
        clip = self._sel_clip()
        pannable = clip is not None and self.is_video() and clip.has_video \
            and (clip.fit == "fill" or clip.zoom > 1.0)
        self.preview.set_pan_segment(self._sel[1] if pannable else None)

    def _build_music_inspector(self) -> QWidget:
        """The selected song (part, start time, level, fades), then what
        applies to all background music."""
        inner, lay = self._page()
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)
        self.music_name = QLabel()
        self.music_name.setObjectName("info_name")
        self.music_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.music_name)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._btn("Change…", self._change_song, "Replace this song"))
        row.addWidget(self._btn("Remove", self._remove_song, "Remove this song"))
        row.addWidget(self._btn("＋ Add song…", self._browse_music,
                                "Add another song to the Music row"))
        lay.addLayout(row)

        lay.addWidget(self._label("THIS SONG", "field_cap"))
        cut = QFormLayout()
        cut.setSpacing(7)
        self.music_fields: dict[str, QLineEdit] = {}
        for key, label in (("start", "Song start:"), ("end", "Song end:"),
                           ("offset", "Comes in at:")):
            f = QLineEdit()
            f.editingFinished.connect(lambda k=key: self._music_typed(k))
            self.music_fields[key] = f
            cut.addRow(self._label(label), f)
        self.music_vol, mv = self._level(35)
        self.music_vol.valueChanged.connect(self._set_song_volume)
        cut.addRow(self._label("Volume:"), mv)
        self.song_fade = QDoubleSpinBox()
        self.song_fade.setRange(0.0, 10.0)
        self.song_fade.setSingleStep(0.5)
        self.song_fade.setDecimals(1)
        self.song_fade.setSuffix(" s")
        self.song_fade.valueChanged.connect(self._set_song_fade)
        cut.addRow(self._label("Fade in / out:"), self.song_fade)
        lay.addLayout(cut)

        lay.addWidget(self._label("ALL MUSIC", "field_cap"))
        self.orig_vol, ov = self._level(100)
        self.orig_vol.valueChanged.connect(lambda _v: (self._push_music(), self._record("orig_vol")))
        orow = QHBoxLayout()
        orow.addWidget(self._label("Original audio:"))
        orow.addLayout(ov, stretch=1)
        lay.addLayout(orow)
        self.music_loop = QCheckBox()
        self.music_loop.setChecked(True)
        self.music_loop.toggled.connect(
            lambda _c: (self._refresh_track(), self._push_music(), self._record()))
        self._tr(self.music_loop, "Loop the last song to the end of the video")
        self.music_fade = QCheckBox()
        self.music_fade.setChecked(True)
        self.music_fade.toggled.connect(lambda _c: (self._push_music(), self._record()))
        self._tr(self.music_fade, "Fade out at the end")
        lay.addWidget(self.music_loop)
        lay.addWidget(self.music_fade)
        lay.addWidget(self._label(
            "Drag a song's handles to cut it and the block to move it. Overlap two songs "
            "and give them a fade to crossfade.", "hint"))
        lay.addStretch()
        return self._scroll(inner)

    def _level(self, value: int) -> tuple[QSlider, QHBoxLayout]:
        s = QSlider(Qt.Horizontal)
        s.setObjectName("level_slider")
        s.setRange(0, 100)
        s.setValue(value)
        s.setCursor(QCursor(_HAND))
        lbl = QLabel(f"{value}%")
        lbl.setObjectName("level_value")
        s.setProperty("value_label", lbl)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
        row = QHBoxLayout()
        row.addWidget(s, stretch=1)
        row.addWidget(lbl)
        return s, row


    def _wire_shortcuts(self) -> None:
        for keys, slot in (
            (("Space", "K"), self.preview.toggle_play),
            (("J",), lambda: self.step(-1.0)),
            (("L",), lambda: self.step(1.0)),
            (("Left",), lambda: self.step(-FRAME)),
            (("Right",), lambda: self.step(FRAME)),
            (("Home",), lambda: self.preview.seek(0.0)),
            (("End",), lambda: self.preview.seek(self.track.total())),
            (("I",), lambda: self.trim_at_playhead("start")),
            (("O",), lambda: self.trim_at_playhead("end")),
            (("S",), self.split_clip),
            (("M",), self._mute_selected),
            (("Z",), self.zoom_to_clip),
            (("Delete",), self._delete_selected),
            (("Ctrl+C",), self.copy_selection),
            (("Ctrl+D",), self.duplicate_selection),
            (("Ctrl+A",), self.select_all),
            (("Escape",), self.deselect),
            ((QKeySequence.Undo, "Ctrl+Z"), self.undo),
            ((QKeySequence.Redo, "Ctrl+Y", "Ctrl+Shift+Z"), self.redo),
            (("Ctrl+=", "Ctrl++"), lambda: self.zoom_timeline(1.5)),
            (("Ctrl+-",), lambda: self.zoom_timeline(1 / 1.5)),
            (("Ctrl+0",), self.fit_timeline),
            (("Ctrl+N",), self.new_project),
            (("Ctrl+O",), lambda: self.open_project()),
            (("Ctrl+S",), self.save_project),
            (("Ctrl+Shift+S",), self.save_project_as),
        ):
            seen = set()
            for key in keys:
                seq = QKeySequence(key)
                if seq.isEmpty() or seq.toString() in seen:
                    continue
                seen.add(seq.toString())
                sc = QShortcut(seq, self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)

    def show_shortcuts(self) -> None:
        rows = "".join(
            f"<tr><td style='padding:3px 18px 3px 0'><b>{keys}</b></td><td>{self.t(desc)}</td></tr>"
            for keys, desc in SHORTCUTS)
        box = QMessageBox(self)
        box.setWindowTitle(self.t("Keyboard shortcuts"))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<table>{rows}</table>")
        box.exec()

    # theme / language ---------------------------------------------------------

    def apply_theme(self, theme: str, palette: dict[str, str], accents: dict[str, str]) -> None:
        self._theme = (theme, palette, accents)
        self.preview.set_colors(palette)
        self.track.set_colors(
            bg=palette["FIELD"], track=palette["SURFACE"], line=palette["BORDER"],
            text=palette["TEXT"], muted=palette["TEXT_MUTED"], clip=accents["clips"],
            clip2=accents["medley"], audio=accents["output"], cue=accents["subs"],
            music=accents["music"], sel=palette["TEXT"], head="#ff4d6d",
            accent=palette["ACCENT"], hdr_sel=palette["SEL"],
        )
        self.track.set_icons({
            "film": self.host.icon("film", accents["clips"], 16).pixmap(16, 16).toImage(),
            "music": self.host.icon("music", accents["output"], 16).pixmap(16, 16).toImage(),
        })
        self._style_icons()
        self._anchor_icons(palette["TEXT"])
        for sw in (self.sub_color, self.sub_bg, self.own_color, self.own_bg):
            sw.set_accent(palette["ACCENT"])
        self.undo_btn.setIcon(_arrow_icon(palette["TEXT"], redo=False))
        self.redo_btn.setIcon(_arrow_icon(palette["TEXT"], redo=True))

    def _style_icons(self) -> None:
        if not hasattr(self, "_theme"):
            return
        muted = self._theme[1]["TEXT_MUTED"]
        for b, kind in ((self.mode_video, "film"), (self.mode_audio, "music")):
            b.setIcon(self.host.icon(kind, "#ffffff" if b.isChecked() else muted, 16))

    def retranslate(self) -> None:
        t = self.t
        for widget, key, method in self._i18n:
            getattr(widget, method)(t(key))
        self.track.set_labels(
            subs=t("Subtitles"), music=t("Music"), images=t("Images"),
            empty_images=t("Double-click to add a picture"),
            empty=t("＋ Drop video or music files here (or double-click)"),
            empty_subs=t("Double-click to add a subtitle"),
            empty_music=t("Double-click to add background music"),
            mute=t("Mute this clip"), unmute=t("Unmute this clip"),
        )
        self.preview.set_texts(
            empty=t("Add clips to start"), audio="♪", guides=t("Guides"),
            guides_tip=t("Show the safe area and centre lines (dragged text and pictures "
                         "always snap to them; hold Alt to place freely)"))
        self._fill(self.res, [
            (t("Same as first clip"), "auto"),
            (t("1080p landscape (16:9)"), "1080p"),
            (t("720p landscape (16:9)"), "720p"),
            (t("480p landscape (16:9)"), "480p"),
            (t("Vertical 1080×1920 (9:16)"), "vertical"),
            (t("Square 1080×1080 (1:1)"), "square"),
        ])
        for sw in (self.sub_color, self.sub_bg, self.own_color, self.own_bg):
            sw.retranslate()
        self.refresh_presets()
        self._update_project_ui()
        if not self._busy:
            self.render_btn.setText(t("✦  Render"))
            self.status.setText("")
        self._refresh_all()

    @staticmethod
    def _fill(combo: QComboBox, items: list[tuple[str, str]]) -> None:
        prev = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(combo.findData(prev), 0))
        combo.blockSignals(False)

    # mode -------------------------------------------------------------------------

    def _on_mode(self) -> None:
        video = self.is_video()
        for w in (self.add_sub_btn, self.captions_btn, self.image_btn, self.music_btn,
                  self.combine_btn, self.res_lbl, self.res, self.loud_cb,
                  self.export_cap, self.export_box):
            w.setVisible(video)
        for w in (self.xfade_lbl, self.xfade, self.afmt_lbl, self.afmt, self.abr_lbl, self.abr):
            w.setVisible(not video)
        self.export_hint.setVisible(video and bool(self.export_hint.text()))
        self.track.set_tracks(subs=video, music=video)
        if not video and self._sel and self._sel[0] in ("cue", "music", "image"):
            self.deselect()
        self._style_icons()
        self._refresh_all()
        if self._sel and self._sel[0] == "clip":
            self.select_clip(self._sel[1])  # clip panel only in video mode

    # selection ----------------------------------------------------------------------

    def _show_inspector(self, page: int, title: str) -> None:
        # a plain click elsewhere ends a multi-select; clicking one of the picked
        # items (to drag the group) keeps it
        if not self._keep_picked and self._picked and self._sel not in self._picked:
            self._picked = set()
            self.track.set_picked(self._picked)
        self.insp.setCurrentIndex(page)
        self.insp_title.setText(self.t(title))
        if hasattr(self, "_images"):
            self._push_images()  # the picture's selection box follows the selection

    def deselect(self) -> None:
        self._sel = None
        self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(None)
        self.preview.set_cues(self._preview_cues(), None)
        self.preview.set_pan_segment(None)

    def select_clip(self, i: int) -> None:
        if not 0 <= i < len(self._clips):
            return
        if self._sel != ("clip", i):
            self._sel = ("clip", i)
            # where this clip is on screen (inside a transition: past its middle)
            self.preview.seek(self.track.offsets()[i] + self.track.overlaps()[i] / 2 + 0.01)
        if self.is_video():
            self._fill_clip_inspector()
            self._show_inspector(self.INSP_CLIP, "Clip")
        else:
            self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(self._sel)
        self.preview.set_cues(self._preview_cues(), None)
        self._update_pan_target()

    def select_cue(self, i: int) -> None:
        if not 0 <= i < len(self._cues):
            return
        self._sel = ("cue", i)
        cue = self._cues[i]
        if not cue.start <= self.preview.position() < cue.end:
            self.preview.seek(cue.start + 0.01)
        self.preview.set_cues(self._preview_cues(), i)
        self._fill_cue_inspector()
        self._show_inspector(self.INSP_CUE, "Subtitle")
        self.track.set_selection(self._sel)

    def select_music(self, k: int = 0) -> None:
        if not 0 <= k < len(self._songs):
            return
        self._sel = ("music", k)
        self._fill_music_inspector()
        self._show_inspector(self.INSP_MUSIC, "Background music")
        self.track.set_selection(self._sel)

    def _on_track_seek(self, t: float) -> None:
        if self._sel and self._sel[0] == "music":
            self.deselect()
        self.preview.seek(t)

    def track_playhead(self, t: float) -> None:
        self.track.set_playhead(t)

    # refresh ---------------------------------------------------------------------

    def _segments(self, override: tuple[int, float, float] | None = None) -> list[Segment]:
        """One preview segment per clip. Where a transition overlaps two clips
        the preview switches at its middle, so segment times match the render."""
        spans = [c.span() for c in self._clips]
        if override is not None:
            spans[override[0]] = (override[1], override[2])
        outs = [(e - s) / c.speed for c, (s, e) in zip(self._clips, spans)]
        ov = transition_overlaps(outs, [(c.transition, c.transition_d) for c in self._clips])
        if not self.is_video():
            ov = [0.0] * len(spans)
        ov.append(0.0)
        segs = []
        for i, (c, (s, _e)) in enumerate(zip(self._clips, spans)):
            start = s + ov[i] / 2 * c.speed  # source seconds
            dur = max(0.0, outs[i] - ov[i] / 2 - ov[i + 1] / 2)  # montage seconds
            segs.append(Segment(c.path, start, dur, c.has_video, fit=c.fit, zoom=c.zoom,
                                pan_x=c.pan_x, pan_y=c.pan_y,
                                volume=c.gain() * self._orig_level(), speed=c.speed))
        return segs

    def _transition_marks(self) -> list[TransitionMark]:
        marks = []
        for i, (off, ov) in enumerate(zip(self.track.offsets(), self.track.overlaps())):
            if ov > 0:
                kind = self._clips[i].transition
                marks.append(TransitionMark(off + ov / 2, ov, kind,
                                            self.t(TRANSITION_LABELS.get(kind, kind)), i))
        return marks

    def _reload_preview(self, position: float | None = None) -> None:
        segs = self._segments()
        if segs:
            self.preview.load_timeline(segs, position)
        else:
            self.preview.clear()
        self.preview.set_transitions(self._transition_marks() if self.is_video() else [])
        self._update_pan_target()
        self._push_music()
        self._push_images()
        sel = self._sel[1] if self._sel and self._sel[0] == "cue" else None
        self.preview.set_cues(self._preview_cues(), sel)

    def _refresh_all(self) -> None:
        self._refresh_track()
        self._refresh_aspect()
        self._push_style()
        if self._sel is None:
            self._show_inspector(self.INSP_PROJECT, "Project")
        self._reload_preview()
        self.name.setPlaceholderText("vidgrab-montage" if self.is_video() else "vidgrab-medley")

    def _refresh_track(self) -> None:
        music = None
        if self._songs:
            last = len(self._songs) - 1
            music = [{"name": Path(song.path).name, "dur": song.length, "wave": song.wave,
                      "loop": k == last and self.music_loop.isChecked(),
                      "start": song.span()[0], "end": song.span()[1],
                      "offset": song.offset, "fade": song.fade}
                     for k, song in enumerate(self._songs)]
        self.track.set_data(
            list(self._clips),
            [(c.start, c.end, c.text) for c in self._cues] if self.is_video() else [],
            music if self.is_video() else None,
            [(img.start, img.end, Path(img.path).name, self._image_thumb(img.path))
             for img in self._images] if self.is_video() else [],
        )
        self._fit_timeline()
        total = self.track.total()  # transitions overlap, so not the plain sum
        self._sync_export()
        self.total_lbl.setText(
            self.t("{n} clips · {dur}", n=len(self._clips), dur=fmt_time(total)))

    def _refresh_aspect(self) -> None:
        first = next((c for c in self._clips if c.has_video), None)
        w, h = canvas_size(
            self.res.currentData() or "auto",
            first.info.get("width", 0) if first else 1280,
            first.info.get("height", 0) if first else 720,
        )
        self.preview.set_aspect(w, h)

    def _push_style(self) -> None:
        self.preview.set_style(self._style())
        if self._sel and self._sel[0] == "cue":
            self._fill_cue_inspector()
        self._record("style")

    def _sub_position(self) -> str:
        return next((v for v, b in self.sub_pos_btns.items() if b.isChecked()), "bottom")

    def _style(self) -> SubtitleStyle:
        bg = self.sub_bg.color() or None
        self.sub_bg_opacity.setEnabled(bg is not None)
        return SubtitleStyle(size=self.sub_size.value(),
                             color=self.sub_color.color() or "#FFFFFF",
                             position=self._sub_position(),
                             background=bg,
                             bg_opacity=self.sub_bg_opacity.value() / 100,
                             font=self.sub_font.currentData() or SUBTITLE_FONT_NAME,
                             bold=self.sub_bold.isChecked(),
                             fade=self.sub_fade.value())

    def _preview_cues(self) -> list[tuple[int, SubtitleCue]]:
        if not self.is_video():
            return []
        return [(i, c) for i, c in enumerate(self._cues) if c.text.strip()]

    def _project_changed(self) -> None:
        self._refresh_track()
        self._refresh_aspect()
        self._reload_preview()

    def _cues_changed(self) -> None:
        sel_cue = self._cues[self._sel[1]] if self._sel and self._sel[0] == "cue" else None
        picked = [self._cues[i] for k, i in self._picked if k == "cue" and i < len(self._cues)]
        self._cues.sort(key=lambda c: c.start)
        if sel_cue is not None:
            self._sel = ("cue", self._cues.index(sel_cue))
            self.track.set_selection(self._sel)
        if picked:  # the selection follows the lines, not their old positions
            ids = {id(c) for c in picked}
            self._picked = {(k, i) for k, i in self._picked if k != "cue"} | {
                ("cue", i) for i, c in enumerate(self._cues) if id(c) in ids}
            self.track.set_picked(self._picked)
        self._refresh_track()
        sel = self._sel[1] if self._sel and self._sel[0] == "cue" else None
        self.preview.set_cues(self._preview_cues(), sel)

    # media ------------------------------------------------------------------------

    def _add_dialog(self) -> None:
        paths = self.host.pick_files(
            self.t("Add clips"), ("Videos", "Music", "Downloads"),
            "Media (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.mp3 *.m4a *.wav "
            "*.flac *.ogg *.opus *.aac);;All files (*)",
        )
        self.add_clips(paths)

    def add_clips(self, paths: list[str]) -> None:
        added = 0
        pictures = [p for p in paths if p.lower().endswith(IMAGE_EXTS)]
        if pictures and self.is_video():  # a picture is an overlay, not a clip
            self.add_images(pictures)
        paths = [p for p in paths if not p.lower().endswith(IMAGE_EXTS)]
        for path in paths:
            if path.endswith(PROJECT_EXT):
                self.open_project(path)
                return
            if not self._probe(path):
                self.host.log(self.t("Could not determine the length of {name}.",
                                     name=Path(path).name))
                continue
            self._clips.append(replace(self._media[path]))
            added += 1
        if added:
            self._project_changed()
            self._record()

    def _move_clip(self, delta: int) -> None:
        if self._sel and self._sel[0] == "clip":
            i = self._sel[1]
            self._on_clip_moved(i, i + delta)

    def _on_clip_moved(self, src: int, dest: int) -> None:
        if not (0 <= src < len(self._clips) and 0 <= dest < len(self._clips)) or src == dest:
            return
        clip = self._clips.pop(src)
        self._clips.insert(dest, clip)
        self._sel = ("clip", dest)
        self._project_changed()
        self.track.set_selection(self._sel)
        self.preview.seek(self.track.offsets()[dest] + 0.01)
        self._record()

    def _delete_selected(self) -> None:
        if len(self._picked) > 1:
            self._delete_items(self._picked)
            return
        if not self._sel:
            return
        kind, i = self._sel
        if kind == "clip":
            del self._clips[i]
            self.deselect()
            self._project_changed()
            self._record()
        elif kind == "cue":
            del self._cues[i]
            self.deselect()
            self._cues_changed()
            self._record()
        elif kind == "music":
            self._remove_song()
        elif kind == "image":
            self._remove_image()

    # multi-select, copy / paste -------------------------------------------------

    def selected_items(self) -> list[tuple[str, int]]:
        if self._picked:
            return sorted(self._picked)
        return [self._sel] if self._sel else []

    def _set_picked(self, items: set[tuple[str, int]], primary: tuple[str, int] | None) -> None:
        self._picked = set(items) if len(items) > 1 else set()
        self._keep_picked = True
        try:
            if primary is None:
                self.deselect()
            else:
                {"clip": self.select_clip, "cue": self.select_cue, "image": self.select_image,
                 "music": self.select_music}[primary[0]](primary[1])
        finally:
            self._keep_picked = False
        self.track.set_picked(self._picked)
        n = len(self.selected_items())
        self.status.setText(self.t("{n} items selected", n=n) if n > 1 else "")

    def _on_item_toggled(self, kind: str, i: int) -> None:
        items = set(self.selected_items())
        if (kind, i) in items:
            items.discard((kind, i))
            primary = self._sel if self._sel in items else next(iter(sorted(items)), None)
        else:
            items.add((kind, i))
            primary = (kind, i)
        self._set_picked(items, primary)

    def _on_item_clicked(self, kind: str, i: int) -> None:
        """A plain click (no drag) on one of several picked items: just that one."""
        if self._picked and (kind, i) in self._picked:
            self._set_picked({(kind, i)}, (kind, i))

    def _on_box_selected(self, items: list) -> None:
        items = [tuple(x) for x in items if self.is_video() or x[0] == "clip"]
        self._set_picked(set(items), items[0] if items else None)

    def select_all(self) -> None:
        items = {("clip", i) for i in range(len(self._clips))}
        if self.is_video():
            items |= {("cue", i) for i in range(len(self._cues))}
            items |= {("image", i) for i in range(len(self._images))}
            items |= {("music", i) for i in range(len(self._songs))}
        self._set_picked(items, min(items) if items else None)

    def _on_group_moved(self, delta: float) -> None:
        """The other picked subtitles / pictures follow a dragged one (the
        dragged one itself arrives through its own signal, which records)."""
        for kind, i in self._picked:
            if (kind, i) == self._sel:
                continue
            if kind == "cue" and i < len(self._cues):
                c = self._cues[i]
                c.start, c.end = round(c.start + delta, 2), round(c.end + delta, 2)
            elif kind == "image" and i < len(self._images):
                img = self._images[i]
                img.start, img.end = round(img.start + delta, 2), round(img.end + delta, 2)
        self._push_images()

    def _delete_items(self, items) -> None:
        by_kind: dict[str, list[int]] = {}
        for kind, i in items:
            by_kind.setdefault(kind, []).append(i)
        for kind, store in (("clip", self._clips), ("cue", self._cues),
                            ("image", self._images), ("music", self._songs)):
            for i in sorted(by_kind.get(kind, []), reverse=True):
                if i < len(store):
                    del store[i]
        self._picked = set()
        self.deselect()
        self._project_changed()
        self._cues_changed()
        self._push_music()
        self._record()

    def copy_selection(self) -> bool:
        """Ctrl+C: keep copies of the selected items (timed ones relative to
        the earliest of them)."""
        items = self.selected_items()
        if not items:
            return False
        get = {"clip": self._clips, "cue": self._cues, "image": self._images, "music": self._songs}
        picked = {k: [replace(get[k][i]) for kk, i in items if kk == k and i < len(get[k])]
                  for k in get}
        starts = [c.start for c in picked["cue"]] + [m.start for m in picked["image"]] + \
            [s.offset for s in picked["music"]]
        self._clipboard = {**picked, "base": min(starts, default=0.0)}
        self.status.setText(self.t("Copied {n} items", n=len(items)) if len(items) > 1
                            else self.t("Copied"))
        return True

    def paste(self, at: float | None = None) -> bool:
        """Ctrl+V: the copied items at the playhead (clips go after the clip
        under it), keeping their spacing; they become the selection."""
        cb = self._clipboard
        if not cb:
            return False
        t = self.preview.position() if at is None else at
        total = self.track.total()
        new: set[tuple[str, int]] = set()
        if cb["clip"]:
            hit = self._clip_at(t)
            where = hit[0] + 1 if hit else len(self._clips)
            for n, clip in enumerate(cb["clip"]):
                self._clips.insert(where + n, replace(clip))
            new |= {("clip", where + n) for n in range(len(cb["clip"]))}
            self._project_changed()
            total = self.track.total()
        shift = t - cb["base"]
        for c in cb["cue"]:
            length = c.end - c.start
            start = round(min(max(0.0, c.start + shift), max(0.0, total - length)), 2)
            self._cues.append(replace(c, start=start, end=round(start + length, 2)))
        for img in cb["image"]:
            length = img.end - img.start
            start = round(min(max(0.0, img.start + shift), max(0.0, total - length)), 2)
            self._images.append(replace(img, start=start, end=round(start + length, 2)))
            new.add(("image", len(self._images) - 1))
        for song in cb["music"]:
            self._songs.append(replace(song, offset=round(max(0.0, song.offset + shift), 2)))
            new.add(("music", len(self._songs) - 1))
        pasted_cues = {id(x) for x in self._cues[len(self._cues) - len(cb["cue"]):]}
        self._cues.sort(key=lambda c: c.start)
        new |= {("cue", i) for i, c in enumerate(self._cues) if id(c) in pasted_cues}
        self._refresh_track()
        self._push_music()
        self._push_images()
        self.preview.set_cues(self._preview_cues(), None)
        self._set_picked(new, min(new) if new else None)
        self._record()
        return True

    def duplicate_selection(self) -> None:
        """Ctrl+D: a copy right after the selected items."""
        if not self.copy_selection():
            return
        cb = self._clipboard
        ends = [c.end for c in cb["cue"]] + [m.end for m in cb["image"]] + \
            [s.offset + (s.span()[1] - s.span()[0]) for s in cb["music"]]
        if ends:
            self.paste(max(ends))
        else:  # clips only: right after the (last) selected clip
            last = max(i for k, i in self.selected_items() if k == "clip")
            self.paste(self.track.offsets()[last] + self._clips[last].kept() / 2)

    def clips(self) -> list[_MediaClip]:
        return list(self._clips)

    # trimming -----------------------------------------------------------------------

    def _on_clip_trimming(self, row: int, s: float, e: float, edge: str) -> None:
        """A handle is moving: show the frame right under it in the preview."""
        self._sel = ("clip", row)
        segs = self._segments((row, s, e))
        seg = segs[row]
        offset = sum(x.duration for x in segs[:row])
        at = offset if edge == "start" else offset + max(0.0, seg.duration - 0.04)
        self.preview.load_timeline(segs, at)

    def _on_clip_trimmed(self, row: int, s: float, e: float, kind: str = "") -> None:
        c = self._clips[row]
        if c.length:  # never past the source, never shorter than MIN_CLIP
            s = min(max(0.0, s), max(0.0, c.length - MIN_CLIP))
            e = min(max(e, s + MIN_CLIP), c.length)
        c.start = round(s, 2) if s > 0.05 else None
        c.end = round(e, 2) if e < c.length - 0.05 else None
        self._refresh_track()
        self._reload_preview()  # stays on the frame shown while dragging
        self.track.set_selection(self._sel)
        if self.insp.currentIndex() == self.INSP_CLIP:
            self._fill_clip_inspector()
        self._record(kind)

    def set_trim(self, row: int, start: float, end: float) -> None:
        """Programmatic equivalent of dragging both handles of clip *row*."""
        self._on_clip_trimmed(row, start, end)

    # subtitles -------------------------------------------------------------------------

    def _add_cue(self) -> None:
        self._add_cue_at(self.preview.position())

    def _add_cue_at(self, t: float) -> None:
        total = self.track.total()
        if total <= 0:
            self.status.setText(self.t("Add at least one clip first."))
            return
        start = round(min(t, max(0.0, total - 0.5)), 2)
        cue = SubtitleCue(start, round(min(start + 3.0, total), 2), self.t("New subtitle"))
        self._cues.append(cue)
        self._sel = ("cue", len(self._cues) - 1)
        self._cues_changed()
        self.select_cue(self._cues.index(cue))
        self._record()
        self.cue_text.setFocus()
        self.cue_text.selectAll()

    def _cue_edited(self) -> None:
        self._cues_changed()
        if self._sel and self._sel[0] == "cue":
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._fill_cue_inspector()

    def _fill_cue_inspector(self) -> None:
        cue = self._cues[self._sel[1]]
        if self.cue_text.toPlainText() != cue.text:
            self.cue_text.blockSignals(True)
            self.cue_text.setPlainText(cue.text)
            self.cue_text.blockSignals(False)
        self.cue_start.setText(fmt_time(cue.start))
        self.cue_end.setText(fmt_time(cue.end))
        if cue.x is None:
            where = self.sub_pos_btns[self._sub_position()].text()
            self.cue_pos.setText(self.t("Default ({where})", where=where))
        else:
            self.cue_pos.setText(self.t("Custom ({x}%, {y}%)",
                                        x=round(cue.x * 100), y=round(cue.y * 100)))
        self._fill_effects()
        snapped = cue.anchor if cue.x is not None and cue.x in (0.05, 0.5, 0.95) \
            and cue.y in (0.05, 0.5, 0.95) else None
        for anchor, b in self._anchor_btns.items():
            b.setChecked(anchor == snapped)

    def _edit_cue_text(self) -> None:
        if not self._sel or self._sel[0] != "cue":
            return
        self._cues[self._sel[1]].text = self.cue_text.toPlainText()
        self._refresh_track()
        self.preview.set_cues(self._preview_cues(), self._sel[1])
        self._record(f"text{self._sel[1]}")

    def _paste_text(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.cue_text.insertPlainText(text)
            self.cue_text.setFocus()

    def _edit_cue_time(self, which: str) -> None:
        if not self._sel or self._sel[0] != "cue":
            return
        cue = self._cues[self._sel[1]]
        value = parse_timecode((self.cue_start if which == "start" else self.cue_end).text())
        if value is not None:
            if which == "start" and value < cue.end - 0.1:
                cue.start = round(max(0.0, value), 2)
            elif which == "end" and value > cue.start + 0.1:
                cue.end = round(value, 2)
            self._cue_edited()
            self._record()
        self._fill_cue_inspector()

    def _on_cue_moved(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].x, self._cues[row].y = x, y
            self._cues[row].anchor = 5  # dragging places the text's centre
            if self._sel != ("cue", row):
                self.select_cue(row)
            self.preview.set_cues(self._preview_cues(), row)
            self._fill_cue_inspector()
            self._record()

    def _on_cue_dragged(self, row: int, start: float, end: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].start, self._cues[row].end = start, end
            self._sel = ("cue", row)
            self._cue_edited()
            self._record()

    def _set_anchor(self, anchor: int) -> None:
        """Snap the selected line to one of the 9 grid positions."""
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        col, row = (anchor - 1) % 3, (anchor - 1) // 3
        margin = 0.05
        cue.x = (margin, 0.5, 1 - margin)[col]
        cue.y = (1 - margin, 0.5, margin)[row]
        cue.anchor = anchor
        self.preview.set_cues(self._preview_cues(), self._sel[1])
        self._fill_cue_inspector()
        self._record()

    def _split_cue(self) -> None:
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        t = round(self.preview.position(), 2)
        if not cue.start + 0.2 <= t <= cue.end - 0.2:
            self.status.setText(self.t("Move the playhead inside this line to split it."))
            return
        second = replace(cue, start=t)
        cue.end = t
        self._cues.append(second)
        self._sel = ("cue", self._cues.index(second))
        self._cues_changed()
        self.select_cue(self._cues.index(second))
        self._record()

    def _duplicate_cue(self) -> None:
        if not (self._sel and self._sel[0] == "cue"):
            return
        cue = self._cues[self._sel[1]]
        length = cue.end - cue.start
        total = self.track.total()
        start = min(cue.end, max(0.0, total - 0.3))
        copy = replace(cue, start=round(start, 2), end=round(min(start + length, total), 2))
        self._cues.append(copy)
        self._sel = ("cue", self._cues.index(copy))
        self._cues_changed()
        self.select_cue(self._cues.index(copy))
        self.preview.seek(copy.start + 0.01)
        self._record()

    # subtitle style presets (stored in the app settings) -------------------------

    def refresh_presets(self) -> None:
        names = sorted(self.host.subtitle_presets()) if hasattr(self.host, "subtitle_presets") else []
        current = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(self.t("Choose a preset…"), "")
        for name in names:
            self.preset_combo.addItem(name, name)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(current)))
        self.preset_combo.blockSignals(False)
        self.preset_del.setEnabled(bool(self.preset_combo.currentData()))

    def _style_dict(self) -> dict:
        st = self._style()
        return {"font": st.font, "size": st.size, "bold": st.bold, "color": st.color,
                "background": st.background, "bg_opacity": st.bg_opacity,
                "fade": st.fade, "position": st.position}

    def _apply_style_dict(self, style: dict) -> None:
        widgets = (self.sub_font, self.sub_size, self.sub_bold, self.sub_bg_opacity, self.sub_fade)
        for w in widgets:
            w.blockSignals(True)
        font_idx = self.sub_font.findData(style.get("font", SUBTITLE_FONT_NAME))
        self.sub_font.setCurrentIndex(max(font_idx, 0))
        self.sub_size.setValue(int(style.get("size", 24)))
        self.sub_bold.setChecked(bool(style.get("bold")))
        self.sub_color.set_color(style.get("color", "#FFFFFF"))
        self.sub_bg.set_color(style.get("background"))
        self.sub_bg_opacity.setValue(round(float(style.get("bg_opacity", 0.6)) * 100))
        self.sub_fade.setValue(float(style.get("fade", 0.0)))
        position = style.get("position", "bottom")
        self.sub_pos_btns.get(position, self.sub_pos_btns["bottom"]).setChecked(True)
        for w in widgets:
            w.blockSignals(False)
        self._push_style()

    def apply_preset(self, name: str) -> None:
        preset = self.host.subtitle_presets().get(name)
        if not preset:
            self.preset_del.setEnabled(False)
            return
        self._apply_style_dict(preset)
        self.preset_del.setEnabled(True)

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, self.t("Save as preset…"),
                                        self.t("Preset name:"))
        name = name.strip()
        if ok and name:
            self.host.save_subtitle_preset(name, self._style_dict())
            self.preset_combo.setCurrentIndex(self.preset_combo.findData(name))
            self.preset_del.setEnabled(True)

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentData()
        if name:
            self.host.delete_subtitle_preset(name)

    def set_default_resolution(self, value: str | None) -> None:
        idx = self.res.findData(value or "auto")
        if idx >= 0:
            self.res.setCurrentIndex(idx)

    def _reset_cue_pos(self) -> None:
        if self._sel and self._sel[0] == "cue":
            cue = self._cues[self._sel[1]]
            cue.x = cue.y = None
            cue.anchor = 5
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._fill_cue_inspector()
            self._record()

    def _apply_pos_all(self) -> None:
        if self._sel and self._sel[0] == "cue":
            src = self._cues[self._sel[1]]
            for cue in self._cues:
                cue.x, cue.y, cue.anchor = src.x, src.y, src.anchor
            self.preview.set_cues(self._preview_cues(), self._sel[1])
            self._record()

    def load_srt(self, path: str) -> bool:
        """Replace the subtitle lines with those in an .srt file (the YouTube
        captions that come with "Send to Studio")."""
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return False
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("big5", errors="replace")
        cues = parse_srt(text)
        if not cues:
            return False
        self._cues = cues
        self.deselect()
        self._cues_changed()
        self._record()
        return True

    def cues(self) -> list[SubtitleCue]:
        return [replace(c) for c in self._cues if c.text.strip()]

    # music ---------------------------------------------------------------------------

    def music_path(self) -> str:
        """The selected song's file (else the first song's; "" if none)."""
        song = self._cur_song() or (self._songs[0] if self._songs else None)
        return song.path if song else ""

    def songs(self) -> list[_Song]:
        return list(self._songs)

    def _cur_song(self) -> _Song | None:
        if self._sel and self._sel[0] == "music" and 0 <= self._sel[1] < len(self._songs):
            return self._songs[self._sel[1]]
        return None

    def _pick_song(self) -> str:
        return self.host.pick_file(
            self.t("Choose background music"), ("Music", "Downloads"),
            "Audio (*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.mp4);;All files (*)",
        )

    def _browse_music(self) -> None:
        path = self._pick_song()
        if path:
            self.add_song(path)

    def _load_song(self, path: str) -> _Song | None:
        if path not in self._music_media:
            try:
                info = probe_media(path, translate=self.host.t)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, self.t("Choose background music"), str(exc))
                return None
            self._music_media[path] = (info, waveform(path))
        info, wave = self._music_media[path]
        return _Song(path, info, wave)

    def add_song(self, path: str) -> None:
        """Add a song to the Music row, after the songs already there."""
        song = self._load_song(path)
        if song is None:
            return
        if self._songs:  # straight after the previous song's part
            last = self._songs[-1]
            start, end = last.span()
            song.offset = round(min(last.offset + (end - start),
                                    max(0.0, self.track.total() - MIN_MUSIC)), 2)
        self._songs.append(song)
        self._refresh_track()
        self._push_music()
        self.select_music(len(self._songs) - 1)
        self._record()

    def set_music(self, path: str) -> None:
        """Use *path* as background music: the first song if there is none,
        else it replaces the selected (or first) song, keeping its timing."""
        if not self._songs:
            self.add_song(path)
            return
        k = self._sel[1] if self._cur_song() is not None else 0
        song = self._load_song(path)
        if song is None:
            return
        old = self._songs[k]
        song.offset, song.volume, song.fade = old.offset, old.volume, old.fade
        self._songs[k] = song
        self._refresh_track()
        self._push_music()
        self.select_music(k)
        self._record()

    def _change_song(self) -> None:
        path = self._pick_song()
        if path:
            self.set_music(path)

    def _remove_song(self) -> None:
        if self._cur_song() is None:
            return
        del self._songs[self._sel[1]]
        self.deselect()
        self._refresh_track()
        self._push_music()
        self._record()

    def _clear_music(self) -> None:
        """Remove every song."""
        self._songs = []
        if self._sel and self._sel[0] == "music":
            self.deselect()
        self._refresh_track()
        self._push_music()
        self._record()

    def _set_song_cut(self, k: int, start: float, end: float, offset: float,
                      kind: str = "") -> None:
        song = self._songs[k]
        dur = song.length or max(end, start + MIN_MUSIC)
        start = min(max(0.0, start), max(0.0, dur - MIN_MUSIC))
        end = min(max(end, start + MIN_MUSIC), dur)
        song.start = round(start, 2)
        song.end = None if end >= dur - 0.05 else round(end, 2)
        song.offset = round(max(0.0, offset), 2)
        self._refresh_track()
        self._push_music()
        self.select_music(k)
        self._record(kind)

    def _set_music_cut(self, start: float, end: float, offset: float, kind: str = "") -> None:
        """The selected (or first) song's part and offset."""
        k = self._sel[1] if self._cur_song() is not None else 0
        if self._songs:
            self._set_song_cut(k, start, end, offset, kind)

    @property
    def _music_cut(self) -> tuple[float, float | None, float]:
        """(start, end or None, offset) of the selected (or first) song."""
        song = self._cur_song() or (self._songs[0] if self._songs else None)
        return (song.start, song.end, song.offset) if song else (0.0, None, 0.0)

    def _on_music_dragged(self, k: int, start: float, end: float, offset: float) -> None:
        if 0 <= k < len(self._songs):
            self._set_song_cut(k, start, end, offset)

    def _music_typed(self, key: str) -> None:
        song = self._cur_song()
        value = parse_timecode(self.music_fields[key].text())
        if song is None or value is None:
            self._fill_music_inspector()
            return
        start, end = song.span()
        span = {"start": start, "end": end, "offset": song.offset}
        span[key] = value
        self._set_song_cut(self._sel[1], span["start"], span["end"], span["offset"])

    def _set_song_volume(self, value: int) -> None:
        song = self._cur_song()
        if song is not None and song.volume != value:
            song.volume = value
            self._push_music()
            self._record("song_volume")

    def _set_song_fade(self, value: float) -> None:
        song = self._cur_song()
        if song is not None and song.fade != round(value, 2):
            song.fade = round(value, 2)
            self._refresh_track()
            self._push_music()
            self._record("song_fade")

    def _fill_music_inspector(self) -> None:
        song = self._cur_song()
        if song is None:
            return
        self.music_name.setText(QFontMetricsF(self.music_name.font()).elidedText(
            Path(song.path).name, Qt.ElideMiddle, max(120, self.insp.width() - 16)))
        self.music_name.setToolTip(Path(song.path).name)
        for key, value in zip(("start", "end", "offset"), (*song.span(), song.offset)):
            if not self.music_fields[key].hasFocus():
                self.music_fields[key].setText(_fmt_precise(value))
        for w, v in ((self.music_vol, song.volume), (self.song_fade, song.fade)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self._sync_level_label(self.music_vol)

    @staticmethod
    def _sync_level_label(slider: QSlider) -> None:
        lbl = slider.property("value_label")
        if lbl is not None:
            lbl.setText(f"{slider.value()}%")

    def _music_beds(self) -> list[MusicBed]:
        last = len(self._songs) - 1
        return [MusicBed(song.path, *song.span(), song.offset,
                         loop=k == last and self.music_loop.isChecked(),
                         volume=song.volume / 100, fade_out=self.music_fade.isChecked(),
                         fade=song.fade)
                for k, song in enumerate(self._songs)]

    def _push_music(self) -> None:
        """Hand the preview the music (and the clips' level under it)."""
        self.preview.set_music(self._music_beds() if self.is_video() else [])
        for i, c in enumerate(self._clips):
            self.preview.set_segment_volume(i, c.gain() * self._orig_level())

    def _orig_level(self) -> float:
        """The clips' own sound is turned down under the music (as rendered)."""
        if self._songs and self.is_video():
            return self.orig_vol.value() / 100
        return 1.0

    # images over the video --------------------------------------------------------

    def images(self) -> list[ImageOverlay]:
        return [replace(img) for img in self._images]

    def _image_thumb(self, path: str) -> QImage | None:
        cache = self.__dict__.setdefault("_thumb_cache", {})
        if path not in cache:
            img = QImage(path)
            cache[path] = img.scaledToHeight(48, Qt.SmoothTransformation) if not img.isNull() else None
        return cache[path]

    def _browse_images(self, *, at: float | None = None) -> None:
        exts = " ".join(f"*{e}" for e in IMAGE_EXTS)
        paths = self.host.pick_files(self.t("Add images"), ("Pictures", "Downloads"),
                                     f"Images ({exts});;All files (*)")
        if paths:
            self.add_images(paths, at=at)

    def add_images(self, paths: list[str], *, at: float | None = None) -> None:
        """Add pictures from the playhead (or *at*), placed by what they look
        like: a cut-out with transparency (a logo, a sticker) goes small in a
        corner, a photo large in the middle. Several are shown one after another."""
        total = self.track.total()
        if total <= 0:
            self.status.setText(self.t("Add at least one clip first."))
            return
        t = self.preview.position() if at is None else at
        added = None
        for path in paths:
            pic = QImage(path)
            if pic.isNull():
                self.host.log(self.t("Could not read the image {name}.", name=Path(path).name))
                continue
            length = min(4.0, total)
            start = round(min(max(0.0, t), max(0.0, total - length)), 2)
            img = ImageOverlay(path, start, round(min(start + length, total), 2))
            frame_w, frame_h = canvas_size(self.res.currentData() or "auto",
                                           *self._first_video_size())
            if pic.hasAlphaChannel():  # a logo / sticker: top-right corner
                img.width = 0.22
                h = img.width * frame_w * pic.height() / max(1, pic.width()) / frame_h
                img.x, img.y = round(1 - 0.04 - img.width / 2, 4), round(0.06 + h / 2, 4)
            else:  # a photo: as large as fits, centred
                fit_w = min(0.8, 0.8 * frame_h / frame_w * pic.width() / max(1, pic.height()))
                img.width = round(fit_w, 4)
                img.fade = 0.3
            self._images.append(img)
            added = len(self._images) - 1
            t = img.end
        if added is None:
            return
        self._refresh_track()
        self._push_images()
        self.select_image(added)
        self.preview.seek(self._images[added].start + 0.01)
        self._record()

    def _first_video_size(self) -> tuple[int, int]:
        first = next((c for c in self._clips if c.has_video), None)
        return (first.info.get("width", 0), first.info.get("height", 0)) if first else (1280, 720)

    def _cur_image(self) -> ImageOverlay | None:
        if self._sel and self._sel[0] == "image" and 0 <= self._sel[1] < len(self._images):
            return self._images[self._sel[1]]
        return None

    def select_image(self, k: int) -> None:
        if not 0 <= k < len(self._images):
            return
        self._sel = ("image", k)
        img = self._images[k]
        if not img.start <= self.preview.position() < img.end:
            self.preview.seek(img.start + 0.01)
        self._fill_image_inspector()
        self._show_inspector(self.INSP_IMAGE, "Image")
        self.track.set_selection(self._sel)
        self._push_images()

    def _push_images(self) -> None:
        sel = self._sel[1] if self._sel and self._sel[0] == "image" else None
        self.preview.set_images(list(enumerate(self._images)) if self.is_video() else [], sel)

    def _image_changed(self, kind: str = "", *, timeline: bool = False) -> None:
        if timeline:
            self._refresh_track()
            self.track.set_selection(self._sel)
        self._push_images()
        self._fill_image_inspector()
        self._record(kind)

    def _on_image_timing(self, k: int, start: float, end: float) -> None:
        if 0 <= k < len(self._images):
            self._images[k].start, self._images[k].end = start, end
            self._sel = ("image", k)
            self._image_changed(timeline=True)

    def _on_image_placed(self, k: int, x: float, y: float, width: float,
                         rotation: float = 0.0) -> None:
        if 0 <= k < len(self._images):
            img = self._images[k]
            img.x, img.y, img.width, img.rotation = x, y, width, rotation
            self._sel = ("image", k)
            self._image_changed()

    def _remove_image(self) -> None:
        if self._cur_image() is None:
            return
        del self._images[self._sel[1]]
        self.deselect()
        self._refresh_track()
        self._push_images()
        self._record()

    def _build_image_inspector(self) -> QWidget:
        inner, lay = self._page()
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)
        self.image_name = QLabel()
        self.image_name.setObjectName("info_name")
        self.image_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.image_name)
        times = QHBoxLayout()
        times.setSpacing(8)
        self.image_fields: dict[str, QLineEdit] = {}
        for key, label in (("start", "Start:"), ("end", "End:")):
            f = QLineEdit()
            f.editingFinished.connect(lambda k=key: self._image_typed(k))
            self.image_fields[key] = f
            times.addWidget(self._label(label))
            times.addWidget(f, stretch=1)
        lay.addLayout(times)
        form = QFormLayout()
        form.setSpacing(7)
        self.image_size, srow = self._level(30)
        self.image_size.setRange(3, 200)
        self.image_size.valueChanged.connect(self._set_image_size)
        form.addRow(self._label("Size:"), srow)
        self.image_opacity, orow = self._level(100)
        self.image_opacity.setRange(5, 100)
        self.image_opacity.valueChanged.connect(self._set_image_opacity)
        form.addRow(self._label("Opacity:"), orow)
        self.image_fade = QDoubleSpinBox()
        self.image_fade.setRange(0.0, 5.0)
        self.image_fade.setSingleStep(0.1)
        self.image_fade.setDecimals(1)
        self.image_fade.setSuffix(" s")
        self.image_fade.valueChanged.connect(self._set_image_fade)
        form.addRow(self._label("Fade in / out:"), self.image_fade)
        turn = QHBoxLayout()
        turn.setSpacing(6)
        self.image_rotation = QDoubleSpinBox()
        self.image_rotation.setRange(-180.0, 180.0)
        self.image_rotation.setSingleStep(5.0)
        self.image_rotation.setDecimals(1)
        self.image_rotation.setSuffix("°")
        self.image_rotation.setWrapping(True)
        self.image_rotation.valueChanged.connect(self._set_image_rotation)
        turn.addWidget(self.image_rotation, stretch=1)
        for text, step, tip in (("↺ 90°", -90.0, "Turn left 90°"), ("↻ 90°", 90.0, "Turn right 90°")):
            b = self._btn(text, lambda _c=False, d=step: self._turn_image(d), tip)
            turn.addWidget(b)
        form.addRow(self._label("Rotation:"), turn)
        lay.addLayout(form)
        lay.addWidget(self._label("POSITION", "field_cap"))
        pos_row = QHBoxLayout()
        pos_row.setSpacing(12)
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._image_anchor_btns: dict[int, QPushButton] = {}
        for r, row_anchors in enumerate(((7, 8, 9), (4, 5, 6), (1, 2, 3))):
            for c, anchor in enumerate(row_anchors):
                b = QPushButton()
                b.setObjectName("anchor_btn")
                b.setFixedSize(34, 24)
                b.setIconSize(QSize(18, 12))
                b.setCursor(QCursor(_HAND))
                b.clicked.connect(lambda _c=False, a=anchor: self._place_image(a))
                grid.addWidget(b, r, c)
                self._image_anchor_btns[anchor] = b
        pos_row.addWidget(grid_box)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(self._btn("Fill the frame", self._fill_frame_image,
                                "Cover the whole frame (a full-screen picture)"))
        col.addWidget(self._btn("Remove", self._remove_image, "Remove this picture"))
        col.addStretch()
        pos_row.addLayout(col, stretch=1)
        lay.addLayout(pos_row)
        lay.addWidget(self._label(
            "Drag the picture in the preview to move it; drag its corner to resize. Drag its "
            "block in the Images row to change when it shows.", "hint"))
        lay.addStretch()
        return self._scroll(inner)

    def _fill_image_inspector(self) -> None:
        img = self._cur_image()
        if img is None:
            return
        self.image_name.setText(QFontMetricsF(self.image_name.font()).elidedText(
            Path(img.path).name, Qt.ElideMiddle, max(120, self.insp.width() - 16)))
        self.image_name.setToolTip(img.path)
        for key, value in (("start", img.start), ("end", img.end)):
            if not self.image_fields[key].hasFocus():
                self.image_fields[key].setText(_fmt_precise(value))
        for w, v in ((self.image_size, round(img.width * 100)),
                     (self.image_opacity, round(img.opacity * 100)), (self.image_fade, img.fade),
                     (self.image_rotation, img.rotation)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self._sync_level_label(self.image_size)
        self._sync_level_label(self.image_opacity)

    def _image_typed(self, key: str) -> None:
        img = self._cur_image()
        value = parse_timecode(self.image_fields[key].text())
        if img is None or value is None:
            self._fill_image_inspector()
            return
        total = self.track.total()
        if key == "start" and value < img.end - 0.1:
            img.start = round(max(0.0, value), 2)
        elif key == "end" and value > img.start + 0.1:
            img.end = round(min(value, total) if total else value, 2)
        self._image_changed(timeline=True)

    def _set_image_size(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.width = value / 100
            self._image_changed("image_size")

    def _set_image_opacity(self, value: int) -> None:
        img = self._cur_image()
        if img is not None:
            img.opacity = value / 100
            self._image_changed("image_opacity")

    def _set_image_fade(self, value: float) -> None:
        img = self._cur_image()
        if img is not None:
            img.fade = round(value, 2)
            self._image_changed("image_fade")

    def _set_image_rotation(self, value: float) -> None:
        img = self._cur_image()
        if img is not None:
            img.rotation = round(value, 1)
            self._image_changed("image_rotation")

    def _turn_image(self, step: float) -> None:
        img = self._cur_image()
        if img is not None:
            angle = (img.rotation + step) % 360
            img.rotation = round(angle - 360 if angle > 180 else angle, 1)
            self._image_changed()

    def _place_image(self, anchor: int) -> None:
        """Snap the picture to one of 9 spots, its edge a small margin in."""
        img = self._cur_image()
        if img is None:
            return
        frame_w, frame_h = canvas_size(self.res.currentData() or "auto", *self._first_video_size())
        pic = QImage(img.path)
        h = img.width * frame_w * pic.height() / max(1, pic.width()) / frame_h if not pic.isNull() \
            else img.width
        col, row = (anchor - 1) % 3, (anchor - 1) // 3
        margin = 0.04
        img.x = round((margin + img.width / 2, 0.5, 1 - margin - img.width / 2)[col], 4)
        img.y = round((1 - margin - h / 2, 0.5, margin + h / 2)[row], 4)
        self._image_changed()

    def _fill_frame_image(self) -> None:
        img = self._cur_image()
        if img is None:
            return
        frame_w, frame_h = canvas_size(self.res.currentData() or "auto", *self._first_video_size())
        pic = QImage(img.path)
        # cover: wide enough for the frame's width and its height
        cover_h = (frame_h / frame_w) * pic.width() / max(1, pic.height()) if not pic.isNull() else 1
        img.x, img.y, img.width = 0.5, 0.5, round(max(1.0, cover_h), 4)
        self._image_changed()

    # playhead editing ------------------------------------------------------------

    def step(self, seconds: float) -> None:
        self.preview.seek(self.preview.position() + seconds)

    def _clip_at(self, t: float) -> tuple[int, float] | None:
        """(index, source time) of the clip under timeline time *t* — inside a
        transition, the one the preview shows (switching at its middle)."""
        offs, ov = self.track.offsets(), self.track.overlaps() + [0.0]
        for i, off in enumerate(offs):
            clip = self._clips[i]
            begin = off + ov[i] / 2
            end = off + clip.kept() - ov[i + 1] / 2
            if begin <= t < end or (i == len(offs) - 1 and abs(t - end) < 1e-6):
                return i, clip.span()[0] + (t - off) * clip.speed
        return None

    def split_clip(self) -> None:
        """Cut the clip under the playhead in two; both halves stay in place."""
        hit = self._clip_at(self.preview.position())
        if hit is None:
            return
        i, at = hit
        clip = self._clips[i]
        s, e = clip.span()
        if not s + MIN_CLIP <= at <= e - MIN_CLIP:
            self.status.setText(self.t("Move the playhead inside a clip to split it."))
            return
        at = round(at, 2)
        second = replace(clip, start=at, transition="none")
        clip.end = at
        self._clips.insert(i + 1, second)
        self._sel = ("clip", i + 1)
        self._project_changed()
        self.track.set_selection(self._sel)
        self._record()

    def trim_at_playhead(self, edge: str) -> None:
        """I / O: the clip under the playhead starts (or ends) right here."""
        t = self.preview.position()
        hit = self._clip_at(t)
        if hit is None:
            return
        i, at = hit
        s, e = self._clips[i].span()
        if edge == "start" and at <= e - MIN_CLIP:
            self._sel = ("clip", i)
            self._on_clip_trimmed(i, at, e)
            self.preview.seek(self.track.offsets()[i])
        elif edge == "end" and at >= s + MIN_CLIP:
            self._sel = ("clip", i)
            self._on_clip_trimmed(i, s, at)

    # undo / redo ---------------------------------------------------------------------

    def _state(self) -> dict:
        """Everything undo and project files cover, as plain comparable data."""
        return {
            "clips": [(c.path, c.edit()) for c in self._clips],
            "cues": [astuple(c) for c in self._cues],
            "images": [astuple(img) for img in self._images],
            "music": [song.edit() for song in self._songs],
            "music_opts": (self.orig_vol.value(), self.music_loop.isChecked(),
                           self.music_fade.isChecked()),
            "audio_opts": (self.loud_cb.isChecked(),),
            "style": self._style_dict(),
        }

    def _record(self, kind: str = "") -> None:
        """Call after every edit. Edits of the same *kind* in quick succession
        (typing, dragging a slider) merge into one undo step."""
        if self._restoring or self._hist_pos < 0:
            return
        state = self._state()
        if state == self._history[self._hist_pos]:
            return
        now = time.monotonic()
        last_kind, last_t = self._last_edit
        self._last_edit = (kind, now)
        del self._history[self._hist_pos + 1:]
        if kind and kind == last_kind and now - last_t < COALESCE_S and self._hist_pos > 0:
            self._history[self._hist_pos] = state
        else:
            self._history.append(state)
            if len(self._history) > HISTORY_LIMIT:
                del self._history[0]
            self._hist_pos = len(self._history) - 1
        self._update_project_ui()

    def _reset_history(self) -> None:
        self._history = [self._state()]
        self._hist_pos = 0
        self._last_edit = ("", 0.0)
        self._saved_state = self._history[0]
        self._update_project_ui()

    def can_undo(self) -> bool:
        return self._hist_pos > 0

    def can_redo(self) -> bool:
        return 0 <= self._hist_pos < len(self._history) - 1

    def undo(self) -> None:
        if self.can_undo() and not self._busy:
            self._hist_pos -= 1
            self._restore(self._history[self._hist_pos])

    def redo(self) -> None:
        if self.can_redo() and not self._busy:
            self._hist_pos += 1
            self._restore(self._history[self._hist_pos])

    def _restore(self, state: dict) -> None:
        self._restoring = True
        try:
            self._clips = [self._media[path].with_edit(edit)
                           for path, edit in state["clips"] if path in self._media]
            self._cues = [SubtitleCue(*row) for row in state["cues"]]
            self._images = [ImageOverlay(*row) for row in state.get("images", [])]
            self._songs = []
            for path, start, end, offset, volume, fade in state["music"]:
                if path in self._music_media:
                    info, wave = self._music_media[path]
                    self._songs.append(_Song(path, info, wave, start, end, offset, volume, fade))
            kind, i = self._sel or ("", 0)
            if (kind == "clip" and i >= len(self._clips)) or (kind == "cue" and i >= len(self._cues)) \
                    or (kind == "music" and i >= len(self._songs)) \
                    or (kind == "image" and i >= len(self._images)):
                self._sel = None
            orig, loop, fade = state["music_opts"]
            self.orig_vol.setValue(orig)
            self.music_loop.setChecked(loop)
            self.music_fade.setChecked(fade)
            (loud,) = state.get("audio_opts", (False,))
            self.loud_cb.setChecked(loud)
            self._apply_style_dict(state["style"])
            self._refresh_all()
            if self._sel and self._sel[0] == "cue":
                self.select_cue(self._sel[1])
            elif self._sel and self._sel[0] == "clip":
                self.track.set_selection(self._sel)
                if self.insp.currentIndex() == self.INSP_CLIP:
                    self._fill_clip_inspector()
                self._update_pan_target()
            else:
                self.deselect()
        finally:
            self._restoring = False
            self._last_edit = ("", 0.0)
        self._update_project_ui()

    # projects ------------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return bool(self._history) and self._history[self._hist_pos] != self._saved_state

    def _update_project_ui(self) -> None:
        if not hasattr(self, "undo_btn"):
            return
        self.undo_btn.setEnabled(self.can_undo())
        self.redo_btn.setEnabled(self.can_redo())
        name = Path(self._project_path).stem if self._project_path else self.t("Untitled project")
        self.project_lbl.setText(f"{name} \u2022" if self.is_dirty() else name)
        self.project_lbl.setToolTip(self._project_path)

    def _fill_project_menu(self) -> None:
        m = self.project_menu
        m.clear()
        m.addAction(self.t("New project"), QKeySequence("Ctrl+N"), self.new_project)
        m.addAction(self.t("Open project…"), QKeySequence("Ctrl+O"), lambda: self.open_project())
        recent = m.addMenu(self.t("Open recent"))
        paths = [p for p in self._recent() if Path(p).is_file()]
        for path in paths:
            recent.addAction(Path(path).name, lambda p=path: self.open_project(p)).setToolTip(path)
        recent.setEnabled(bool(paths))
        m.addSeparator()
        m.addAction(self.t("Save project"), QKeySequence("Ctrl+S"), self.save_project)
        m.addAction(self.t("Save project as…"), QKeySequence("Ctrl+Shift+S"),
                    self.save_project_as)

    def _recent(self) -> list[str]:
        if not hasattr(self.host, "setting"):
            return []
        return list(self.host.setting("recent_projects") or [])

    def _remember_project(self, path: str) -> None:
        if hasattr(self.host, "set_setting"):
            paths = [path] + [p for p in self._recent() if p != path]
            self.host.set_setting("recent_projects", paths[:8])

    def maybe_save(self) -> bool:
        """Before discarding the project: offer to save. False = cancelled."""
        if not self.is_dirty() or not self._clips:
            return True
        answer = QMessageBox.question(
            self, self.t("Unsaved changes"),
            self.t("Save the changes to this Studio project first?"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def new_project(self) -> None:
        if self._busy or not self.maybe_save():
            return
        self._load_state({"clips": [], "cues": [], "music": [],
                          "music_opts": (100, True, True),
                          "style": self._style_dict()})
        self._project_path = ""
        self.name.clear()
        self._reset_history()
        self.clear_autosave()

    # recovery ------------------------------------------------------------------------

    def _autosave_path(self) -> Path | None:
        path = getattr(self.host, "autosave_path", None)
        return Path(path()) if path else None

    def autosave(self) -> bool:
        """Copy unsaved work for recovery after a crash (not the project file
        itself). True if a copy was written."""
        target = self._autosave_path()
        if target is None or not self.is_dirty() or not self._clips or self._busy:
            return False
        data = {**self.project_data(), "autosave_of": self._project_path,
                "autosaved_at": time.strftime("%Y-%m-%d %H:%M")}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)  # never leave a half-written copy behind
        except OSError:
            return False
        return True

    def clear_autosave(self) -> None:
        target = self._autosave_path()
        if target is not None:
            target.unlink(missing_ok=True)

    def recover(self, path: str) -> bool:
        """Open a recovery copy; the project stays unsaved until you save it."""
        ok = self.open_project(path, recovering=True)
        if ok:
            self.status.setText(self.t("Recovered unsaved work"))
        return ok

    def project_data(self) -> dict:
        """The project as JSON-ready data (paths absolute, plus relative to the
        project file so a moved folder still opens)."""
        base = Path(self._project_path).parent if self._project_path else None

        def ref(path: str) -> dict:
            out = {"path": str(Path(path).resolve())}
            if base is not None:
                try:
                    out["rel"] = os.path.relpath(path, base)
                except ValueError:  # another drive on Windows
                    pass
            return out

        music = [{**ref(song.path), "start": song.start, "end": song.end,
                  "offset": song.offset, "volume": song.volume, "fade": song.fade}
                 for song in self._songs]
        return {
            "app": "VidGrab", "version": PROJECT_VERSION,
            "mode": "video" if self.is_video() else "audio",
            "resolution": self.res.currentData() or "auto",
            "export": self._export,
            "name": self.name.text().strip(),
            "output_dir": self.out_dir.text().strip(),
            "crossfade": self.xfade.value(),
            "audio_format": self.afmt.currentData(),
            "audio_bitrate": self.abr.currentData(),
            "clips": [{**ref(c.path), "start": c.start, "end": c.end,
                       "transition": c.transition, "transition_duration": c.transition_d,
                       "fit": c.fit, "zoom": c.zoom, "pan_x": c.pan_x, "pan_y": c.pan_y,
                       "volume": c.volume, "muted": c.muted, "speed": c.speed,
                       "denoise": c.denoise}
                      for c in self._clips],
            "subtitles": [asdict(c) for c in self._cues],
            "images": [{**ref(img.path), **{k: v for k, v in asdict(img).items() if k != "path"}}
                       for img in self._images],
            "music": music,
            "music_options": {"original_volume": self.orig_vol.value(),
                              "loop_last": self.music_loop.isChecked(),
                              "fade_out": self.music_fade.isChecked()},
            "normalize_loudness": self.loud_cb.isChecked(),
            "style": self._style_dict(),
        }

    def save_project(self) -> bool:
        if not self._project_path:
            return self.save_project_as()
        return self._write_project(self._project_path)

    def save_project_as(self) -> bool:
        default = (self.name.text().strip() or "project") + PROJECT_EXT
        path = self.host.pick_save(self.t("Save project"), default,
                                   f"VidGrab project (*{PROJECT_EXT})")
        if not path:
            return False
        if not path.endswith(PROJECT_EXT):
            path += PROJECT_EXT
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        self._project_path = path
        try:
            Path(path).write_text(json.dumps(self.project_data(), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, self.t("Save project"), str(exc))
            return False
        self._saved_state = self._history[self._hist_pos]
        self._remember_project(path)
        self.clear_autosave()
        self.status.setText(self.t("Project saved"))
        self._update_project_ui()
        return True

    def open_project(self, path: str | None = None, *, recovering: bool = False) -> bool:
        if self._busy or (not recovering and not self.maybe_save()):
            return False
        if path is None:
            path = self.host.pick_file(self.t("Open project"), ("Videos", "Documents"),
                                       f"VidGrab project (*{PROJECT_EXT});;All files (*)")
        if not path:
            return False
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
            QMessageBox.warning(self, self.t("Open project"),
                                self.t("That file is not a VidGrab project."))
            return False
        base = Path(path).parent
        missing: list[str] = []

        def find(ref: dict) -> str:
            for cand in (ref.get("path"), str(base / ref["rel"]) if ref.get("rel") else None):
                if cand and Path(cand).is_file():
                    return cand
            missing.append(Path(ref.get("path") or ref.get("rel") or "?").name)
            return ""

        clips = []
        for ref in data["clips"]:
            found = find(ref)
            if found and self._probe(found):
                transition = ref.get("transition", "none")
                clips.append((found, (
                    ref.get("start"), ref.get("end"),
                    transition if transition in TRANSITIONS else "none",
                    float(ref.get("transition_duration", 1.0)),
                    "fill" if ref.get("fit") == "fill" else "fit",
                    max(1.0, float(ref.get("zoom", 1.0))),
                    float(ref.get("pan_x", 0.5)), float(ref.get("pan_y", 0.5)),
                    min(2.0, max(0.0, float(ref.get("volume", 1.0)))),
                    bool(ref.get("muted", False)),
                    min(max(float(ref.get("speed", 1.0)), SPEED_RANGE[0]), SPEED_RANGE[1]),
                    bool(ref.get("denoise", False)))))
        songs: list[tuple] = []
        raw = data.get("music") or []
        if isinstance(raw, dict):  # 3.2 projects: one song, options on the song
            raw = [raw]
        opts = data.get("music_options") or {}
        if raw and not opts:
            opts = {"original_volume": raw[0].get("original_volume", 100),
                    "loop_last": raw[0].get("loop", True), "fade_out": raw[0].get("fade_out", True)}
        for m in raw:
            if not isinstance(m, dict):
                continue
            found = find(m)
            if not found:
                continue
            if found not in self._music_media:
                try:
                    info = probe_media(found, translate=self.host.t)
                    self._music_media[found] = (info, waveform(found))
                except Exception as exc:  # noqa: BLE001 - report and skip the file
                    self.host.log(f"{Path(found).name}: {exc}")
                    continue
            songs.append((found, max(0.0, float(m.get("start") or 0.0)),
                          float(m["end"]) if m.get("end") is not None else None,
                          max(0.0, float(m.get("offset") or 0.0)),
                          int(m.get("volume", 35)), max(0.0, float(m.get("fade") or 0.0))))
        music_opts = (int(opts.get("original_volume", 100)), bool(opts.get("loop_last", True)),
                      bool(opts.get("fade_out", True)))
        fields = {f for f in SubtitleCue.__dataclass_fields__}
        cues = [astuple(SubtitleCue(**{k: v for k, v in c.items() if k in fields}))
                for c in data.get("subtitles", []) if isinstance(c, dict)]
        (self.mode_video if data.get("mode", "video") == "video" else self.mode_audio) \
            .setChecked(True)
        for combo, value in ((self.res, data.get("resolution")), (self.afmt, data.get("audio_format")),
                             (self.abr, data.get("audio_bitrate"))):
            idx = combo.findData(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.xfade.setValue(float(data.get("crossfade", self.xfade.value())))
        if data.get("export") in EXPORT_PRESETS:
            self._export = data["export"]
        self.name.setText(str(data.get("name", "")))
        if data.get("output_dir"):
            self.out_dir.setText(str(data["output_dir"]))
        img_fields = set(ImageOverlay.__dataclass_fields__) - {"path"}
        images = []
        for m in data.get("images") or []:
            found = find(m) if isinstance(m, dict) else ""
            if found:
                images.append(astuple(ImageOverlay(found, **{k: v for k, v in m.items()
                                                             if k in img_fields})))
        self._load_state({"clips": clips, "cues": cues, "music": songs, "images": images,
                          "music_opts": music_opts,
                          "audio_opts": (bool(data.get("normalize_loudness", False)),),
                          "style": {**self._style_dict(), **(data.get("style") or {})}})
        self._reset_history()
        if recovering:  # back under its own name (if it had one), still unsaved
            self._project_path = str(data.get("autosave_of") or "")
            self._saved_state = None
            self._update_project_ui()
        else:
            self._project_path = path
            self._remember_project(path)
            self.clear_autosave()
        self.preview.seek(0.0)
        if missing:
            QMessageBox.warning(self, self.t("Open project"),
                                self.t("These files could not be found and were left out:\n{names}",
                                       names="\n".join(missing)))
        return True

    def _probe(self, path: str) -> bool:
        """Probe *path* once (thumbnail / waveform included) into the media cache."""
        if path in self._media:
            return True
        try:
            info = probe_media(path, translate=self.host.t)
        except Exception as exc:  # noqa: BLE001 - report and skip the file
            self.host.log(f"{Path(path).name}: {exc}")
            return False
        if not info["duration"]:
            return False
        clip = _MediaClip(path, info)
        if info["has_video"]:
            dur = info["duration"]
            count = max(2, min(FILMSTRIP, int(dur / 2)))
            for k in range(count):
                at = (k + 0.5) * dur / count
                png = thumbnail_png(path, at)
                if png:
                    clip.thumbs.append((at, QImage.fromData(png)))
            if clip.thumbs:
                # the block's label frame: the first one that isn't (nearly) black
                clip.thumb = next((img for _t, img in clip.thumbs if _brightness(img) > 40),
                                  clip.thumbs[len(clip.thumbs) // 2][1])
        elif info["has_audio"]:
            clip.wave = waveform(path)
        self._media[path] = clip
        return True

    def _load_state(self, state: dict) -> None:
        self._sel = None
        self._restore(state)
        self.fit_timeline()

    # output ---------------------------------------------------------------------------

    def _browse_out(self) -> None:
        folder = self.host.pick_dir(self.t("Save to:"), self.out_dir.text())
        if folder:
            self.out_dir.setText(folder)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        captions = busy and self._busy_job == "captions"
        # while captions are made the Render button stops them
        self.render_btn.setEnabled(not busy or captions)
        self.captions_btn.setEnabled(not busy)
        self.combine_btn.setEnabled(not busy)
        if busy:
            self.preview.stop()
            self.progress.setMaximum(0)
            self.render_btn.setText(self.t("✕  Stop") if captions else self.t("✦  Rendering…"))
        else:
            self._busy_job = "render"
            self.progress.setMaximum(100)
            self.render_btn.setText(self.t("✦  Render"))
            self._reload_preview()

    def show_progress(self, msg: str, pct: float | None) -> None:
        if pct is None:
            self.progress.setMaximum(0)
            self.status.setText(msg)
        else:
            self.progress.setMaximum(100)
            self.progress.setValue(int(pct))
            self.status.setText(f"{msg} {int(pct)}%")

    def shutdown(self) -> None:
        """Stop background frame extraction (before the window closes)."""
        self.thumbs.shutdown()

    def finish(self, ok: bool) -> None:
        self.progress.setMaximum(100)
        self.progress.setValue(100 if ok else 0)
        self.status.setText(self.t("Done") if ok else self.t("Failed"))

    # auto captions ---------------------------------------------------------------------

    def caption_sources(self) -> list[CaptionSource]:
        """The sound of every clip as it plays in the montage (muted clips and
        clips without sound are left out)."""
        out = []
        for c, offset in zip(self._clips, self.track.offsets()):
            if not c.has_audio or c.gain() <= 0:
                continue
            start, end = c.span()
            out.append(CaptionSource(c.path, start, end if c.length else c.end, c.speed, offset))
        return out

    def auto_captions(self) -> None:
        """Ask how to listen, then turn the speech in the clips into lines."""
        if self._busy:
            return
        if not captions_installed():  # a pip install without the speech add-on
            QMessageBox.information(self, self.t("Auto captions"), self.t(
                "Auto captions need the speech add-on, which this installation doesn't "
                "have. Install it with:\n\npip install \"vidgrab-studio[captions]\""))
            return
        if not self._clips:
            QMessageBox.warning(self, self.t("No clips"), self.t("Add at least one clip first."))
            return
        if not self.caption_sources():
            QMessageBox.information(self, self.t("Auto captions"),
                                    self.t("None of the clips has sound to listen to."))
            return
        if not self.host.ffmpeg_ok():
            return
        choice = self._captions_dialog()
        if choice is None:
            return
        language, size, replace_lines = choice
        if hasattr(self.host, "set_setting"):
            self.host.set_setting("caption_language", language)
            self.host.set_setting("caption_model", size)
        self._busy_job = "captions"
        self.render_requested.emit("transcribe", {
            "sources": self.caption_sources(),
            "language": language,
            "size": size,
            "gpu": bool(self.host.setting("gpu_captions")) if hasattr(self.host, "setting") else True,
            "replace": replace_lines,
        })

    def _captions_dialog(self) -> tuple[str, str, bool] | None:
        t = self.t
        setting = self.host.setting if hasattr(self.host, "setting") else (lambda _k: None)
        dlg = QDialog(self)
        dlg.setWindowTitle(t("Auto captions"))
        dlg.setMinimumWidth(480)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        intro = QLabel(t("Turns the speech in your clips into subtitle lines. It runs on "
                         "this computer; the speech model is downloaded once."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addSpacing(4)
        cap = QLabel(t("SPOKEN LANGUAGE"))
        cap.setObjectName("field_cap")
        lay.addWidget(cap)
        lang = QComboBox()
        for code, name in CAPTION_LANGUAGES.items():
            lang.addItem(name or t("Detect automatically"), code)
        idx = lang.findData(setting("caption_language") or "auto")
        lang.setCurrentIndex(max(0, idx))
        lay.addWidget(lang)
        lay.addSpacing(4)
        cap = QLabel(t("ACCURACY"))
        cap.setObjectName("field_cap")
        lay.addWidget(cap)
        sizes: dict[str, QPushButton] = {}
        box = QWidget()
        box.setObjectName("segmented")
        box.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        models_dir = self.host.models_dir() if hasattr(self.host, "models_dir") else None
        hint = QLabel()
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        notes = {"fast": t("Quickest; fine for clear speech."),
                 "balanced": t("Good for most videos."),
                 "best": t("Most accurate, and slow without a graphics card.")}

        # the model's format and size depend on the engine that will run it
        # (the window is waiting: don't stay on a driver that is slow to answer)
        engine = speech_engines(bool(setting("gpu_captions")), models_dir, timeout=3.0)[0]
        basic_gpu = engine == "openvino" and any(
            g.basic for g in detect_gpus(3.0) if g.engine == "openvino")
        needs_cuda = (engine == "cuda" and models_dir is not None
                      and not cuda_runtime.runtime_ready(models_dir))

        def pick(key: str) -> None:
            ready = models_dir is not None and model_ready(models_dir, key, engine)
            note = notes[key] + " " + (t("Already downloaded.") if ready else
                                       t("Downloads {size} the first time.",
                                         size=model_info(key, engine)[1]))
            if needs_cuda:
                note += " " + t("Also downloads the NVIDIA CUDA libraries ({size}), once.",
                                size=cuda_runtime.download_size_label())
            if basic_gpu:
                note += " " + t("Your graphics are basic and may be slower than the CPU; if so, "
                                "turn off the graphics-card switch in Settings → Hardware.")
            hint.setText(note)

        for key, label in (("fast", t("Fast")), ("balanced", t("Balanced")), ("best", t("Best"))):
            b = QPushButton(label)
            b.setObjectName("segment")
            b.setProperty("compact", True)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setMinimumHeight(30)
            b.setCursor(QCursor(_HAND))
            b.clicked.connect(lambda _c=False, k=key: pick(k))
            row.addWidget(b)
            sizes[key] = b
        current = setting("caption_model")
        current = current if current in CAPTION_MODELS else DEFAULT_CAPTION_MODEL
        sizes[current].setChecked(True)
        pick(current)
        lay.addWidget(box)
        lay.addWidget(hint)
        replace_box = QCheckBox(t("Replace the current subtitle lines"))
        replace_box.setVisible(bool(self._cues))
        lay.addWidget(replace_box)
        lay.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(t("Cancel"))
        cancel.clicked.connect(dlg.reject)
        go = QPushButton(t("Create captions"))
        go.setDefault(True)
        go.clicked.connect(dlg.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        lay.addLayout(buttons)
        self._captions_dlg = dlg  # for tests
        if dlg.exec() != QDialog.Accepted:
            return None
        size = next(k for k, b in sizes.items() if b.isChecked())
        return lang.currentData(), size, replace_box.isChecked()

    # two videos at once ------------------------------------------------------------

    def combine_videos(self) -> None:
        """Ask for two videos and a layout, then render them as one clip."""
        if self._busy or not self.host.ffmpeg_ok():
            return
        first = self._sel[1] if self._sel and self._sel[0] == "clip" else 0
        picks = [c for c in self._clips[first:first + 2]]
        if len(picks) < 2:
            picks = self._clips[:2]
        initial = [(c.path, "" if not c.start else f"{c.start:g}",
                    "" if c.end is None else f"{c.end:g}") for c in picks]

        def still(path: str, at: float) -> QImage | None:
            png = thumbnail_png(path, at, height=240) if Path(path).is_file() else None
            return QImage.fromData(png) if png else None

        dlg = SplitDialog(
            self, self.t,
            lambda: self.host.pick_file(self.t("Choose a video"), ("Videos", "Downloads"),
                                        "Videos (*.mp4 *.mkv *.webm *.mov *.avi *.m4v);;All files (*)"),
            initial, still)
        self._split_dlg = dlg  # for tests
        if dlg.exec() != QDialog.Accepted:
            return
        values = dlg.values()
        folder = Path(self.out_dir.text().strip() or self.host.default_output_dir())
        names = [Path(c.path).stem for c in values["clips"]]
        name = "".join(ch for ch in " + ".join(names) if ch not in '<>:"/\\|?*').strip()
        self._busy_job = "combine"
        self.render_requested.emit("combine", {
            **values,
            "output_file": folder / f"{name[:120] or 'split screen'}.mp4",
            "render_quality": (self.host.setting("render_quality")
                               if hasattr(self.host, "setting") else "balanced"),
            "hardware": bool(self.host.setting("gpu_render"))
            if hasattr(self.host, "setting") else False,
        })

    def combined_ready(self, path: str) -> None:
        """The two-video clip is made: it joins the timeline like any file."""
        self.add_clips([path])
        self.select_clip(len(self._clips) - 1)
        self.status.setText(self.t("Added {name}", name=Path(path).name))

    def captions_ready(self, cues: list[SubtitleCue], replace_lines: bool) -> None:
        """Put the recognised lines on the Subtitles row (one undo step)."""
        if not cues:
            self.status.setText(self.t("No speech was found in the clips."))
            return
        self._cues = list(cues) if replace_lines else sorted(
            [*self._cues, *cues], key=lambda c: c.start)
        self.deselect()
        self._cues_changed()
        self._record()
        self.status.setText(self.t("Added {n} subtitle lines", n=len(cues)))

    def cancel_job(self) -> None:
        self.cancel_requested.emit()

    def render(self) -> None:
        if self._busy:
            if self._busy_job == "captions":
                self.cancel_job()
            return
        if not self._clips:
            QMessageBox.warning(self, self.t("No clips"), self.t("Add at least one clip first."))
            return
        if not self.host.ffmpeg_ok():
            return
        video = self.is_video()
        clips = [Clip(c.path, str(c.start) if c.start else None,
                      str(c.end) if c.end is not None else None,
                      transition=c.transition if video else "none",
                      transition_duration=c.transition_d,
                      fit=c.fit, zoom=c.zoom, pan_x=c.pan_x, pan_y=c.pan_y,
                      volume=c.volume, muted=c.muted, speed=c.speed, denoise=c.denoise)
                 for c in self._clips]
        folder = Path(self.out_dir.text().strip() or self.host.default_output_dir())
        name = self.name.text().strip() or self.name.placeholderText()
        name = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "vidgrab"
        if self.is_video():
            last = len(self._songs) - 1
            music = [BackgroundMusic(
                path=song.path, volume=song.volume / 100,
                original_volume=self.orig_vol.value() / 100,
                loop=k == last and self.music_loop.isChecked(),
                fade_out=self.music_fade.isChecked(),
                start=song.start, end=song.end, offset=song.offset, fade=song.fade,
            ) for k, song in enumerate(self._songs)] or None
            self.render_requested.emit("compose_video", {
                "clips": clips,
                "output_file": folder / f"{name}{EXPORT_PRESETS[self._export][2]}",
                "resolution": self.res.currentData() or "auto",
                "subtitles": self.cues() or None,
                "images": [replace(img) for img in self._images] or None,
                "subtitle_style": self._style(),
                "music": music,
                "render_quality": (self.host.setting("render_quality")
                                   if hasattr(self.host, "setting") else "balanced"),
                "hardware": bool(self.host.setting("gpu_render"))
                if hasattr(self.host, "setting") else False,
                "normalize_loudness": self.loud_cb.isChecked(),
            })
        else:
            ext = self.afmt.currentData() or ".mp3"
            self.render_requested.emit("compose_audio", {
                "clips": clips,
                "output_file": folder / f"{name}{ext}",
                "crossfade": self.xfade.value(),
                "bitrate": self.abr.currentData(),
            })
