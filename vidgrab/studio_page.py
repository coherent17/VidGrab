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
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
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
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab.preview import Segment, StudioPreview, fmt_time
from vidgrab.studio import (
    SUBTITLE_FONT_NAME,
    BackgroundMusic,
    Clip,
    SubtitleCue,
    SubtitleStyle,
    canvas_size,
    format_srt,
    parse_srt,
    parse_timecode,
    probe_media,
    system_fonts,
    thumbnail_png,
    waveform,
)

_HAND = Qt.PointingHandCursor
MIN_CLIP = 0.2  # shortest a clip can be trimmed to (s)


# (label key, colour) presets for subtitle text and its background box
TEXT_COLORS = [("White", "#FFFFFF"), ("Yellow", "#FFE500"), ("Cyan", "#00FFFF"),
               ("Pink", "#FF69B4"), ("Red", "#FF4D4D"), ("Green", "#3EE07A"),
               ("Black", "#000000")]
BG_COLORS = [("Black", "#000000"), ("Dark gray", "#333333"), ("White", "#FFFFFF"),
             ("Yellow", "#FFE500")]
CUSTOM = "custom"


def _swatch(color: str | None) -> QIcon:
    """Small colour square for combo items (checkerboard for 'none')."""
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if color:
        p.setBrush(QColor(color))
        p.setPen(QPen(QColor("#808080"), 1))
        p.drawRoundedRect(QRectF(1, 1, 14, 14), 3, 3)
    else:
        for i in range(4):
            for j in range(4):
                p.fillRect(i * 4, j * 4, 4, 4,
                           QColor("#cccccc") if (i + j) % 2 else QColor("#ffffff"))
        p.setPen(QPen(QColor("#ef4444"), 1.6))
        p.drawLine(QPointF(2, 14), QPointF(14, 2))
    p.end()
    return QIcon(pm)


@dataclass
class _MediaClip:
    path: str
    info: dict
    start: float | None = None
    end: float | None = None
    thumb: QImage | None = None
    wave: list[float] = field(default_factory=list)

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

    def kept(self) -> float:
        s, e = self.span()
        return max(0.0, e - s)


# ── multi-track timeline ──────────────────────────────────────────────────


class TrackTimeline(QWidget):
    """One row per clip, then Subtitles and Music, under a time ruler."""

    seek_requested = Signal(float)
    clip_selected = Signal(int)
    clip_trimming = Signal(int, float, float, str)  # row, start, end, "start"|"end"
    clip_trimmed = Signal(int, float, float)
    clip_moved = Signal(int, int)  # from, to
    cue_selected = Signal(int)
    cue_changed = Signal(int, float, float)
    cue_add_requested = Signal(float)
    music_selected = Signal()
    add_media_requested = Signal()
    music_requested = Signal()

    HEADER_W, RULER_H, GAP = 168, 24, 5
    CLIP_H, SUBS_H, MUSIC_H = 46, 30, 36
    EDGE = 10  # px around a block edge that grabs its trim handle
    HEADROOM = 1.12  # spare width on the right so clips can be lengthened

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._clips: list[_MediaClip] = []
        self._cues: list[tuple[float, float, str]] = []
        self._music: dict | None = None
        self._labels = {"subs": "Subtitles", "music": "Music", "empty": "",
                        "empty_subs": "", "empty_music": ""}
        self._show_subs = True
        self._show_music = True
        self._playhead = 0.0
        self._selection: tuple[str, int] | None = None
        self._hover: tuple[str, int, str] | None = None
        self._drag: dict | None = None
        self._icons: dict[str, QImage] = {}
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

    def set_labels(self, **labels: str) -> None:
        self._labels.update(labels)
        self.update()

    def set_tracks(self, *, subs: bool, music: bool) -> None:
        self._show_subs, self._show_music = subs, music
        self._update_height()

    def set_data(self, clips: list[_MediaClip], cues, music: dict | None) -> None:
        if self._drag is not None:
            return
        self._clips, self._cues, self._music = clips, cues, music
        self._update_height()

    def set_playhead(self, t: float) -> None:
        self._playhead = t
        self.update()

    def set_selection(self, sel: tuple[str, int] | None) -> None:
        self._selection = sel
        self.update()

    def total(self) -> float:
        return sum(c.kept() for c in self._clips)

    def offsets(self) -> list[float]:
        out, t = [], 0.0
        for c in self._clips:
            out.append(t)
            t += c.kept()
        return out

    # geometry ------------------------------------------------------------

    def _rows(self) -> list[tuple[str, int, int]]:
        """(kind, index, height) for every row, top to bottom."""
        rows = [("clip", i, self.CLIP_H) for i in range(len(self._clips))] or \
            [("empty", 0, self.CLIP_H)]
        if self._show_subs:
            rows.append(("subs", 0, self.SUBS_H))
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
        span = max(self.total() * self.HEADROOM, 1.0)
        return max(1.0, self.width() - self.HEADER_W - 10) / span

    def _x(self, t: float) -> float:
        return self.HEADER_W + t * self._pps()

    def _t(self, x: float) -> float:
        return min(max((x - self.HEADER_W) / self._pps(), 0.0), max(self.total(), 0.0))

    def _clip_rect(self, i: int) -> QRectF:
        """The kept part of clip *i* (honours an in-progress trim drag)."""
        d = self._drag or {}
        offs = d.get("offsets") or self.offsets()
        row = self._row_rect("clip", i)
        clip = self._clips[i]
        s, e = clip.span()
        x0 = self._x(offs[i])
        if d.get("kind") in ("trim_start", "trim_end") and d.get("row") == i:
            pps = self._pps()
            # the source stays put; the handle slides over it
            src_left = x0 - d["s0"] * pps
            return QRectF(src_left + d["s"] * pps, row.top(), (d["e"] - d["s"]) * pps,
                          row.height())
        return QRectF(x0, row.top(), max(4.0, (e - s) * self._pps()), row.height())

    def _source_rect(self, i: int) -> QRectF:
        """The whole source of clip *i*, aligned so its kept part sits in place."""
        d = self._drag or {}
        offs = d.get("offsets") or self.offsets()
        row = self._row_rect("clip", i)
        clip = self._clips[i]
        s0 = d["s0"] if d.get("row") == i and "s0" in d else clip.span()[0]
        left = self._x(offs[i]) - s0 * self._pps()
        return QRectF(left, row.top(), clip.length * self._pps(), row.height())

    def _cue_rects(self) -> list[QRectF]:
        r = self._row_rect("subs")
        if r is None:
            return []
        return [QRectF(self._x(s), r.top() + 3, max(4.0, (e - s) * self._pps()), r.height() - 6)
                for s, e, _t in self._cues]

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
        t = 0.0
        while total > 0 and self._x(t) < self.width() - 20:
            x = self._x(t)
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
            selected_row = self._selection == ("clip", i) and kind == "clip"
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
        self._paint_music(p, c, fm, total)
        p.restore()

        if total > 0:  # playhead
            x = self._x(min(self._playhead, total))
            p.setPen(Qt.NoPen)
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
            p.setPen(c["text"])
            name_rect = QRectF(x, rect.top() + 4, rect.right() - x, rect.height() / 2 - 2)
            p.drawText(name_rect, Qt.AlignBottom | Qt.AlignLeft,
                       fm.elidedText(clip.name, Qt.ElideMiddle, name_rect.width()))
            p.setPen(c["muted"])
            p.drawText(QRectF(x, rect.center().y() + 1, rect.right() - x, rect.height() / 2 - 4),
                       Qt.AlignTop | Qt.AlignLeft, fmt_time(clip.kept()))
        elif kind in ("subs", "music"):
            p.setPen(c["muted"])
            p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self._labels[kind])

    def _paint_clip(self, p, c, fm, i: int) -> None:
        d = self._drag or {}
        if d.get("kind") == "reorder" and d.get("row") == i and d.get("active"):
            p.setOpacity(0.35)
        clip = self._clips[i]
        base = QColor(c["clip"] if i % 2 == 0 else c["clip2"]) if clip.has_video \
            else QColor(c["audio"])
        selected = self._selection == ("clip", i)
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
            th = body.height()
            tw = clip.thumb.width() * th / max(1, clip.thumb.height())
            x = body.left()
            while x < body.right():
                p.drawImage(QRectF(x, body.top(), tw, th), clip.thumb)
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
            sel = self._selection == ("cue", i)
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

    def _paint_music(self, p, c, fm, total: float) -> None:
        r = self._row_rect("music")
        if r is None:
            return
        if self._music is None:
            if self._clips:
                p.setPen(c["muted"])
                p.drawText(r, Qt.AlignCenter, self._labels["empty_music"])
            return
        if total <= 0:
            return
        dur, loop = self._music["dur"], self._music["loop"]
        end = total if (loop or not dur) else min(dur, total)
        rect = QRectF(self._x(0), r.top() + 3, end * self._pps(), r.height() - 6)
        sel = self._selection == ("music", 0)
        base = QColor(c["music"])
        p.setPen(QPen(QColor(c["sel"]), 2) if sel else Qt.NoPen)
        p.setBrush(QColor(base).darker(250))
        p.drawRoundedRect(rect, 6, 6)
        wave = self._music.get("wave") or []
        if wave and dur:
            p.save()
            p.setClipRect(rect, Qt.IntersectClip)
            x0, seg_w = rect.left(), dur * self._pps()
            while x0 < rect.right():  # repeat the waveform where the song loops
                self._wave(p, QRectF(x0, rect.top() + 2, seg_w, rect.height() - 4),
                           wave, (0.0, dur), dur, base)
                x0 += seg_w
                if not loop:
                    break
            p.restore()
        p.setPen(QColor("#ffffff"))
        label = ("↻ " if loop else "") + self._music["name"]
        inner = rect.adjusted(8, 0, -6, 0)
        p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(label, Qt.ElideRight, inner.width()))

    # hit testing -----------------------------------------------------------

    def _hit(self, pos: QPointF) -> tuple[str, int, str] | None:
        for i in range(len(self._clips)):
            row = self._row_rect("clip", i)
            if not row.adjusted(-self.HEADER_W, 0, 0, 0).contains(pos):
                continue
            if pos.x() < self.HEADER_W:
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
        r = self._row_rect("music")
        if r is not None and self._music is not None and r.contains(pos) \
                and pos.x() <= self._x(self.total()):
            return "music", 0, "body"
        return None

    # mouse -------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        hit = self._hit(pos) if pos.y() > self.RULER_H else None
        if hit is None or hit[2] == "row":
            if hit is not None:
                self.clip_selected.emit(hit[1])
            self._drag = {"kind": "seek"}
            self.seek_requested.emit(self._t(pos.x()))
            return
        kind, i, part = hit
        if kind == "clip":
            s, e = self._clips[i].span()
            self.clip_selected.emit(i)
            base = {"row": i, "pps": self._pps(), "offsets": self.offsets(),
                    "s0": s, "e0": e, "s": s, "e": e, "x0": pos.x(), "y": pos.y()}
            if part in ("start", "end"):
                self._drag = {**base, "kind": f"trim_{part}"}
            else:
                self._drag = {**base, "kind": "reorder", "active": False}
        elif kind == "cue":
            s, e, _txt = self._cues[i]
            self._drag = {"kind": f"cue_{part}", "row": i, "x0": pos.x(), "s": s, "e": e,
                          "s0": s, "e0": e}
            self.cue_selected.emit(i)
        else:
            self.music_selected.emit()
        self.update()

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
            if hit and hit[2] in ("start", "end"):
                self.setCursor(QCursor(Qt.SizeHorCursor))
            elif hit and hit[0] == "clip" and hit[2] == "body":
                self.setCursor(QCursor(Qt.SizeVerCursor if len(self._clips) > 1
                                       else Qt.ArrowCursor))
            elif hit and hit[0] == "cue":
                self.setCursor(QCursor(Qt.OpenHandCursor))
            else:
                self.setCursor(QCursor(_HAND))
            return
        kind = d["kind"]
        if kind == "seek":
            self.seek_requested.emit(self._t(pos.x()))
            return
        if kind == "reorder":
            if not d["active"] and abs(pos.y() - d["y"]) > 8 and len(self._clips) > 1:
                d["active"] = True
            d["y"] = pos.y() if d["active"] else d["y"]
            self.update()
            return
        dt = (pos.x() - d["x0"]) / self._pps()
        if kind in ("trim_start", "trim_end"):
            clip = self._clips[d["row"]]
            if kind == "trim_start":
                d["s"] = round(min(max(0.0, d["s0"] + dt), d["e0"] - MIN_CLIP), 2)
            else:
                d["e"] = round(max(min(clip.length, d["e0"] + dt), d["s0"] + MIN_CLIP), 2)
            self.update()
            self.clip_trimming.emit(d["row"], d["s"], d["e"], kind[5:])
            return
        total = self.total()  # subtitle move / resize
        s, e = d["s0"], d["e0"]
        if kind == "cue_body":
            length = e - s
            s = min(max(0.0, s + dt), max(0.0, total - length))
            e = s + length
        elif kind == "cue_start":
            s = min(max(0.0, s + dt), e - 0.3)
        else:
            e = max(min(total, e + dt), s + 0.3)
        d["s"], d["e"] = round(s, 2), round(e, 2)
        row = d["row"]
        self._cues[row] = (d["s"], d["e"], self._cues[row][2])
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        d, self._drag = self._drag, None
        if not d:
            return
        kind = d["kind"]
        if kind == "reorder" and d["active"]:
            dest = self._reorder_target(d["y"])
            if dest != d["row"]:
                self.clip_moved.emit(d["row"], dest)
        elif kind in ("trim_start", "trim_end"):
            self.clip_trimmed.emit(d["row"], d["s"], d["e"])
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

    INSP_PROJECT, INSP_CUE, INSP_MUSIC = range(3)

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self._clips: list[_MediaClip] = []
        self._cues: list[SubtitleCue] = []
        self._music_info: dict | None = None
        self._music_wave: list[float] = []
        self._sel: tuple[str, int] | None = None
        self._busy = False
        self._i18n: list[tuple[object, str, str]] = []
        self._build()
        self._wire_shortcuts()
        self._on_mode()  # show the controls for the starting mode

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
        bar.addWidget(self._btn("＋ Add media…", self._add_dialog))
        self.add_sub_btn = self._btn("＋ Subtitle", self._add_cue,
                                     "Add a subtitle line at the playhead")
        self.music_btn = self._btn("♪ Background music…", self._browse_music)
        self.import_btn = self._btn("Import .srt…", self._import_srt)
        self.export_btn = self._btn("Export .srt…", self._export_srt)
        for b in (self.add_sub_btn, self.music_btn, self.import_btn, self.export_btn):
            bar.addWidget(b)
        bar.addStretch()
        self.total_lbl = QLabel()
        self.total_lbl.setObjectName("total_lbl")
        bar.addWidget(self.total_lbl)
        bar.addSpacing(8)
        for key, slot, tip in (("▲", lambda: self._move_clip(-1), "Move up"),
                               ("▼", lambda: self._move_clip(1), "Move down"),
                               ("✕", self._delete_selected, "Delete selected (Del)")):
            b = self._btn(key, slot, tip)
            b.setFixedWidth(40)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.track = TrackTimeline()
        self.track.seek_requested.connect(self._on_track_seek)
        self.track.clip_selected.connect(self.select_clip)
        self.track.clip_trimming.connect(self._on_clip_trimming)
        self.track.clip_trimmed.connect(self._on_clip_trimmed)
        self.track.clip_moved.connect(self._on_clip_moved)
        self.track.cue_selected.connect(self.select_cue)
        self.track.cue_changed.connect(self._on_cue_dragged)
        self.track.cue_add_requested.connect(self._add_cue_at)
        self.track.music_selected.connect(self.select_music)
        self.track.add_media_requested.connect(self._add_dialog)
        self.track.music_requested.connect(self._browse_music)
        self.track_scroll = QScrollArea()
        self.track_scroll.setObjectName("page_scroll")
        self.track_scroll.setWidgetResizable(True)
        self.track_scroll.setFrameShape(QFrame.NoFrame)
        self.track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.track_scroll.setWidget(self.track)
        lay.addWidget(self.track_scroll)
        self._fit_timeline()
        return panel

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
                      self._build_music_inspector):
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
        form = QFormLayout()
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.res = QComboBox()
        self.res.currentIndexChanged.connect(lambda _i: self._refresh_aspect())
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
        lay.addWidget(self._label("Save to:"))
        row = QHBoxLayout()
        self.out_dir = QLineEdit(str(self.host.default_output_dir()))
        row.addWidget(self.out_dir, stretch=1)
        b = self._btn("…", self._browse_out, "Browse…")
        b.setFixedWidth(40)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(self._label(
            "Each clip has its own row in the timeline. Drag the left handle to choose "
            "where it starts and the right handle to choose where it ends; drag a clip "
            "up or down to reorder.", "hint"))
        lay.addStretch()
        return w

    def _build_cue_inspector(self) -> QWidget:
        """Selected line (text, timing, position, split / duplicate), then the
        style every line shares. Scrolls when the window is short."""
        inner, lay = self._page()
        head = QHBoxLayout()
        head.addWidget(self._label("Text:"), stretch=1)
        head.addWidget(self._btn("Paste", self._paste_text, "Paste text from the clipboard"))
        lay.addLayout(head)
        self.cue_text = QPlainTextEdit()
        self.cue_text.setFixedHeight(64)
        self.cue_text.textChanged.connect(self._edit_cue_text)
        lay.addWidget(self.cue_text)
        form = QFormLayout()
        form.setSpacing(8)
        self.cue_start = QLineEdit()
        self.cue_end = QLineEdit()
        self.cue_start.editingFinished.connect(lambda: self._edit_cue_time("start"))
        self.cue_end.editingFinished.connect(lambda: self._edit_cue_time("end"))
        form.addRow(self._label("Start:"), self.cue_start)
        form.addRow(self._label("End:"), self.cue_end)
        lay.addLayout(form)

        # position: 3×3 quick grid (same numbering as ASS \an), or drag in preview
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
                b.setFixedSize(30, 22)
                b.setIconSize(QSize(18, 12))
                b.setCursor(QCursor(_HAND))
                b.clicked.connect(lambda _c=False, a=anchor: self._set_anchor(a))
                grid.addWidget(b, r, c)
                self._anchor_btns[anchor] = b
        pos_row.addWidget(grid_box)
        pos_col = QVBoxLayout()
        pos_col.setSpacing(4)
        pos_col.addWidget(self._label("Position:"))
        self.cue_pos = QLabel()
        self.cue_pos.setObjectName("hint")
        self.cue_pos.setWordWrap(True)
        pos_col.addWidget(self.cue_pos)
        pos_col.addStretch()
        pos_row.addLayout(pos_col, stretch=1)
        lay.addLayout(pos_row)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._btn("Reset position", self._reset_cue_pos))
        row.addWidget(self._btn("Use for all", self._apply_pos_all,
                                "Use this position for all lines"))
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(self._btn("✂ Split at playhead", self._split_cue,
                                 "Cut this line in two at the playhead"))
        row2.addWidget(self._btn("Duplicate", self._duplicate_cue,
                                 "Copy this line right after itself"))
        lay.addLayout(row2)

        # style shared by every line
        sep = QFrame()
        sep.setObjectName("brand_divider")
        sep.setFrameShape(QFrame.NoFrame)
        lay.addSpacing(4)
        lay.addWidget(sep)
        lay.addWidget(self._label("STYLE (ALL LINES)", "field_cap"))
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
        style = QFormLayout()
        style.setSpacing(8)
        style.setRowWrapPolicy(QFormLayout.WrapLongRows)
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
        size_row = QHBoxLayout()
        size_row.addWidget(self.sub_size, stretch=1)
        size_row.addWidget(self.sub_bold)
        self.sub_color = QComboBox()
        self.sub_bg = QComboBox()
        self.sub_pos = QComboBox()
        self._combo_prev: dict[QComboBox, int] = {}
        self.sub_size.valueChanged.connect(lambda _v: self._push_style())
        self.sub_color.activated.connect(lambda _i: self._color_picked(self.sub_color))
        self.sub_bg.activated.connect(lambda _i: self._color_picked(self.sub_bg))
        self.sub_pos.currentIndexChanged.connect(lambda _i: self._push_style())
        self.sub_bg_opacity, op_row = self._level(60)
        self.sub_bg_opacity.setRange(10, 100)
        self.sub_bg_opacity.valueChanged.connect(lambda _v: self._push_style())
        self.sub_fade = QDoubleSpinBox()
        self.sub_fade.setRange(0.0, 2.0)
        self.sub_fade.setSingleStep(0.1)
        self.sub_fade.setDecimals(1)
        self.sub_fade.setSuffix(" s")
        self.sub_fade.valueChanged.connect(lambda _v: self._push_style())
        style.addRow(self._label("Font:"), self.sub_font)
        style.addRow(self._label("Size:"), size_row)
        style.addRow(self._label("Text color:"), self.sub_color)
        style.addRow(self._label("Background:"), self.sub_bg)
        style.addRow(self._label("Opacity:"), op_row)
        style.addRow(self._label("Fade in / out:"), self.sub_fade)
        style.addRow(self._label("Default position:"), self.sub_pos)
        lay.addLayout(style)
        lay.addWidget(self._label(
            "Drag the text in the preview to place it; drag its block in the timeline "
            "to change when it shows.", "hint"))
        lay.addStretch()
        self._fill_fonts()

        scroll = QScrollArea()
        scroll.setObjectName("page_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

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
        for anchor, b in self._anchor_btns.items():
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

    def _build_music_inspector(self) -> QWidget:
        w, lay = self._page()
        self.music_name = QLabel()
        self.music_name.setObjectName("info_name")
        self.music_name.setWordWrap(True)
        lay.addWidget(self.music_name)
        row = QHBoxLayout()
        row.addWidget(self._btn("Change…", self._browse_music))
        row.addWidget(self._btn("Remove", self._clear_music))
        lay.addLayout(row)
        self.music_vol, mv = self._level(35)
        self.orig_vol, ov = self._level(100)
        lay.addWidget(self._label("Music volume:"))
        lay.addLayout(mv)
        lay.addWidget(self._label("Original audio:"))
        lay.addLayout(ov)
        self.music_loop = QCheckBox()
        self.music_loop.setChecked(True)
        self.music_loop.toggled.connect(lambda _c: self._refresh_track())
        self._tr(self.music_loop, "Loop music to fit the video")
        self.music_fade = QCheckBox()
        self.music_fade.setChecked(True)
        self._tr(self.music_fade, "Fade out at the end")
        lay.addWidget(self.music_loop)
        lay.addWidget(self.music_fade)
        lay.addStretch()
        return w

    def _level(self, value: int) -> tuple[QSlider, QHBoxLayout]:
        s = QSlider(Qt.Horizontal)
        s.setObjectName("level_slider")
        s.setRange(0, 100)
        s.setValue(value)
        s.setCursor(QCursor(_HAND))
        lbl = QLabel(f"{value}%")
        lbl.setObjectName("level_value")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
        row = QHBoxLayout()
        row.addWidget(s, stretch=1)
        row.addWidget(lbl)
        return s, row

    def _wire_shortcuts(self) -> None:
        for key, slot in (("Space", self.preview.toggle_play),
                          ("Delete", self._delete_selected)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

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
            subs=t("Subtitles"), music=t("Music"),
            empty=t("＋ Drop video or music files here (or double-click)"),
            empty_subs=t("Double-click to add a subtitle"),
            empty_music=t("Double-click to add background music"),
        )
        self.preview.set_texts(empty=t("Add clips to start"), audio="♪")
        self._fill(self.res, [
            (t("Same as first clip"), "auto"),
            (t("1080p landscape (16:9)"), "1080p"),
            (t("720p landscape (16:9)"), "720p"),
            (t("480p landscape (16:9)"), "480p"),
            (t("Vertical 1080×1920 (9:16)"), "vertical"),
            (t("Square 1080×1080 (1:1)"), "square"),
        ])
        self._fill_colors(self.sub_color, TEXT_COLORS, default="#FFFFFF")
        self._fill_colors(self.sub_bg, BG_COLORS, none=True, default="#000000")
        self._fill(self.sub_pos, [(t("Bottom"), "bottom"), (t("Top"), "top")])
        self.refresh_presets()
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
        for w in (self.add_sub_btn, self.music_btn, self.import_btn, self.export_btn,
                  self.res_lbl, self.res):
            w.setVisible(video)
        for w in (self.xfade_lbl, self.xfade, self.afmt_lbl, self.afmt, self.abr_lbl, self.abr):
            w.setVisible(not video)
        self.track.set_tracks(subs=video, music=video)
        if not video and self._sel and self._sel[0] in ("cue", "music"):
            self.deselect()
        self._style_icons()
        self._refresh_all()

    # selection ----------------------------------------------------------------------

    def _show_inspector(self, page: int, title: str) -> None:
        self.insp.setCurrentIndex(page)
        self.insp_title.setText(self.t(title))

    def deselect(self) -> None:
        self._sel = None
        self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(None)
        self.preview.set_cues(self._preview_cues(), None)

    def select_clip(self, i: int) -> None:
        if not 0 <= i < len(self._clips):
            return
        if self._sel != ("clip", i):
            self._sel = ("clip", i)
            self.preview.seek(self.track.offsets()[i] + 0.01)
        self._show_inspector(self.INSP_PROJECT, "Project")
        self.track.set_selection(self._sel)
        self.preview.set_cues(self._preview_cues(), None)

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

    def select_music(self) -> None:
        if not self.music_path():
            return
        self._sel = ("music", 0)
        self.music_name.setText(Path(self.music_path()).name)
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
        segs = []
        for i, c in enumerate(self._clips):
            s, e = c.span()
            if override is not None and override[0] == i:
                s, e = override[1], override[2]
            if e - s > 0:
                segs.append(Segment(c.path, s, e - s, c.has_video))
        return segs

    def _reload_preview(self, position: float | None = None) -> None:
        segs = self._segments()
        if segs:
            self.preview.load_timeline(segs, position)
        else:
            self.preview.clear()
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
        if self.music_path():
            music = {"name": Path(self.music_path()).name,
                     "dur": float((self._music_info or {}).get("duration") or 0),
                     "loop": self.music_loop.isChecked(), "wave": self._music_wave}
        self.track.set_data(
            list(self._clips),
            [(c.start, c.end, c.text) for c in self._cues] if self.is_video() else [],
            music if self.is_video() else None,
        )
        self._fit_timeline()
        total = sum(c.kept() for c in self._clips)
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

    def _style(self) -> SubtitleStyle:
        bg = self.sub_bg.currentData() or None
        self.sub_bg_opacity.setEnabled(bg is not None)
        return SubtitleStyle(size=self.sub_size.value(),
                             color=self.sub_color.currentData() or "#FFFFFF",
                             position=self.sub_pos.currentData() or "bottom",
                             background=bg,
                             bg_opacity=self.sub_bg_opacity.value() / 100,
                             font=self.sub_font.currentData() or SUBTITLE_FONT_NAME,
                             bold=self.sub_bold.isChecked(),
                             fade=self.sub_fade.value())

    # colour pickers -----------------------------------------------------------

    def _fill_colors(self, combo: QComboBox, presets: list[tuple[str, str]], *,
                     none: bool = False, default: str) -> None:
        """Presets (+ 'None', a picked custom colour, and 'Custom…')."""
        t = self.t
        current = combo.currentData() if combo.count() else default
        combo.blockSignals(True)
        combo.clear()
        if none:
            combo.addItem(_swatch(None), t("None (transparent)"), "")
        for key, color in presets:
            combo.addItem(_swatch(color), t(key), color)
        if current and combo.findData(current) < 0 and current != CUSTOM:
            combo.addItem(_swatch(current), current, current)
        combo.addItem(t("Custom\u2026"), CUSTOM)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        self._combo_prev[combo] = combo.currentIndex()
        combo.blockSignals(False)

    def _color_picked(self, combo: QComboBox) -> None:
        if combo.currentData() == CUSTOM:
            prev = combo.itemData(self._combo_prev.get(combo, 0)) or "#FFFFFF"
            chosen = QColorDialog.getColor(QColor(prev), self, self.t("Custom\u2026"))
            combo.blockSignals(True)
            if chosen.isValid():
                hex_ = chosen.name().upper()
                idx = combo.findData(hex_)
                if idx < 0:
                    idx = combo.count() - 1  # just before "Custom…"
                    combo.insertItem(idx, _swatch(hex_), hex_, hex_)
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentIndex(self._combo_prev.get(combo, 0))
            combo.blockSignals(False)
        self._combo_prev[combo] = combo.currentIndex()
        self._push_style()

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
        self._cues.sort(key=lambda c: c.start)
        if sel_cue is not None:
            self._sel = ("cue", self._cues.index(sel_cue))
            self.track.set_selection(self._sel)
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
        for path in paths:
            try:
                info = probe_media(path, translate=self.host.t)
            except Exception as exc:  # noqa: BLE001 - report and skip the file
                self.host.log(f"{Path(path).name}: {exc}")
                continue
            if not info["duration"]:
                self.host.log(self.t("Could not determine the length of {name}.",
                                     name=Path(path).name))
                continue
            clip = _MediaClip(path, info)
            if info["has_video"]:
                png = thumbnail_png(path, min(1.0, info["duration"] / 3))
                if png:
                    clip.thumb = QImage.fromData(png)
            elif info["has_audio"]:
                clip.wave = waveform(path)
            self._clips.append(clip)
            added += 1
        if added:
            self._project_changed()

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

    def _delete_selected(self) -> None:
        if not self._sel:
            return
        kind, i = self._sel
        if kind == "clip":
            del self._clips[i]
            self.deselect()
            self._project_changed()
        elif kind == "cue":
            del self._cues[i]
            self.deselect()
            self._cues_changed()
        elif kind == "music":
            self._clear_music()

    def clips(self) -> list[_MediaClip]:
        return list(self._clips)

    # trimming -----------------------------------------------------------------------

    def _on_clip_trimming(self, row: int, s: float, e: float, edge: str) -> None:
        """A handle is moving: show the frame right under it in the preview."""
        self._sel = ("clip", row)
        offset = self.track.offsets()[row]
        at = offset if edge == "start" else offset + max(0.0, e - s - 0.04)
        self.preview.load_timeline(self._segments((row, s, e)), at)

    def _on_clip_trimmed(self, row: int, s: float, e: float) -> None:
        c = self._clips[row]
        c.start = round(s, 2) if s > 0.05 else None
        c.end = round(e, 2) if e < c.length - 0.05 else None
        self._refresh_track()
        self._reload_preview()  # stays on the frame shown while dragging
        self.track.set_selection(self._sel)

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
            self.cue_pos.setText(self.t("Default ({where})", where=self.sub_pos.currentText()))
        else:
            self.cue_pos.setText(self.t("Custom ({x}%, {y}%)",
                                        x=round(cue.x * 100), y=round(cue.y * 100)))
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
        self._fill_cue_inspector()

    def _on_cue_moved(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].x, self._cues[row].y = x, y
            self._cues[row].anchor = 5  # dragging places the text's centre
            if self._sel != ("cue", row):
                self.select_cue(row)
            self.preview.set_cues(self._preview_cues(), row)
            self._fill_cue_inspector()

    def _on_cue_dragged(self, row: int, start: float, end: float) -> None:
        if 0 <= row < len(self._cues):
            self._cues[row].start, self._cues[row].end = start, end
            self._sel = ("cue", row)
            self._cue_edited()

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

    def _select_color(self, combo: QComboBox, color: str | None) -> None:
        idx = combo.findData(color or "")
        if idx < 0 and color:
            idx = combo.count() - 1  # a custom colour goes just before "Custom…"
            combo.insertItem(idx, _swatch(color), color, color)
        combo.setCurrentIndex(max(idx, 0))
        self._combo_prev[combo] = combo.currentIndex()

    def apply_preset(self, name: str) -> None:
        preset = self.host.subtitle_presets().get(name)
        if not preset:
            self.preset_del.setEnabled(False)
            return
        for w in (self.sub_font, self.sub_size, self.sub_bold, self.sub_bg_opacity,
                  self.sub_fade, self.sub_pos):
            w.blockSignals(True)
        font_idx = self.sub_font.findData(preset.get("font", SUBTITLE_FONT_NAME))
        self.sub_font.setCurrentIndex(max(font_idx, 0))
        self.sub_size.setValue(int(preset.get("size", 24)))
        self.sub_bold.setChecked(bool(preset.get("bold")))
        self._select_color(self.sub_color, preset.get("color", "#FFFFFF"))
        self._select_color(self.sub_bg, preset.get("background"))
        self.sub_bg_opacity.setValue(round(float(preset.get("bg_opacity", 0.6)) * 100))
        self.sub_fade.setValue(float(preset.get("fade", 0.0)))
        self.sub_pos.setCurrentIndex(max(0, self.sub_pos.findData(preset.get("position", "bottom"))))
        for w in (self.sub_font, self.sub_size, self.sub_bold, self.sub_bg_opacity,
                  self.sub_fade, self.sub_pos):
            w.blockSignals(False)
        self.preset_del.setEnabled(True)
        self._push_style()

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

    def _apply_pos_all(self) -> None:
        if self._sel and self._sel[0] == "cue":
            src = self._cues[self._sel[1]]
            for cue in self._cues:
                cue.x, cue.y, cue.anchor = src.x, src.y, src.anchor
            self.preview.set_cues(self._preview_cues(), self._sel[1])

    def _import_srt(self) -> None:
        path = self.host.pick_file(self.t("Import subtitles"), ("Videos", "Downloads"),
                                   "SubRip (*.srt);;All files (*)")
        if path and not self.load_srt(path):
            QMessageBox.warning(self, self.t("Import subtitles"),
                                self.t("No subtitle lines found in that file."))

    def load_srt(self, path: str) -> bool:
        """Replace the subtitle lines with those in an .srt file."""
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
        return True

    def _export_srt(self) -> None:
        if not self._cues:
            return
        path = self.host.pick_save(self.t("Export subtitles"), "subtitles.srt", "SubRip (*.srt)")
        if path:
            Path(path).write_text(format_srt(self._cues), encoding="utf-8")

    def cues(self) -> list[SubtitleCue]:
        return [replace(c) for c in self._cues if c.text.strip()]

    # music ---------------------------------------------------------------------------

    def music_path(self) -> str:
        return (self._music_info or {}).get("path", "")

    def _browse_music(self) -> None:
        path = self.host.pick_file(
            self.t("Choose background music"), ("Music", "Downloads"),
            "Audio (*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.mp4);;All files (*)",
        )
        if path:
            self.set_music(path)

    def set_music(self, path: str) -> None:
        try:
            info = probe_media(path, translate=self.host.t)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self.t("Choose background music"), str(exc))
            return
        self._music_info = {**info, "path": path}
        self._music_wave = waveform(path)
        self._refresh_track()
        self.select_music()

    def _clear_music(self) -> None:
        self._music_info = None
        self._music_wave = []
        if self._sel and self._sel[0] == "music":
            self.deselect()
        self._refresh_track()

    # output ---------------------------------------------------------------------------

    def _browse_out(self) -> None:
        folder = self.host.pick_dir(self.t("Save to:"), self.out_dir.text())
        if folder:
            self.out_dir.setText(folder)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.render_btn.setEnabled(not busy)
        if busy:
            self.preview.stop()
            self.progress.setMaximum(0)
            self.render_btn.setText(self.t("✦  Rendering…"))
        else:
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

    def finish(self, ok: bool) -> None:
        self.progress.setMaximum(100)
        self.progress.setValue(100 if ok else 0)
        self.status.setText(self.t("Done") if ok else self.t("Failed"))

    def render(self) -> None:
        if self._busy:
            return
        if not self._clips:
            QMessageBox.warning(self, self.t("No clips"), self.t("Add at least one clip first."))
            return
        if not self.host.ffmpeg_ok():
            return
        clips = [Clip(c.path, str(c.start) if c.start else None,
                      str(c.end) if c.end is not None else None) for c in self._clips]
        folder = Path(self.out_dir.text().strip() or self.host.default_output_dir())
        name = self.name.text().strip() or self.name.placeholderText()
        name = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "vidgrab"
        if self.is_video():
            music = None
            if self.music_path():
                music = BackgroundMusic(
                    path=self.music_path(),
                    volume=self.music_vol.value() / 100,
                    original_volume=self.orig_vol.value() / 100,
                    loop=self.music_loop.isChecked(),
                    fade_out=self.music_fade.isChecked(),
                )
            self.render_requested.emit("compose_video", {
                "clips": clips,
                "output_file": folder / f"{name}.mp4",
                "resolution": self.res.currentData() or "auto",
                "subtitles": self.cues() or None,
                "subtitle_style": self._style(),
                "music": music,
                "render_quality": (self.host.setting("render_quality")
                                   if hasattr(self.host, "setting") else "balanced"),
            })
        else:
            ext = self.afmt.currentData() or ".mp3"
            self.render_requested.emit("compose_audio", {
                "clips": clips,
                "output_file": folder / f"{name}{ext}",
                "crossfade": self.xfade.value(),
                "bitrate": self.abr.currentData(),
            })
