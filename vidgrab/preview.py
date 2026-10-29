"""Studio preview: plays the whole montage inside the window.

The clips play back to back exactly as they will be rendered (each clip's
start / end, letterboxed onto the output frame), with the subtitle lines
drawn on top. Lines can be dragged to a new position.

Frames are painted with plain QPainter from a QVideoSink — QVideoWidget needs
a working OpenGL context, which many Linux / WSLg setups don't have.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vidgrab.studio import (
    SUBTITLE_FONT_NAME,
    SUBTITLE_MARGIN,
    SubtitleCue,
    SubtitleStyle,
    box_padding,
    color_hex,
    subtitle_scale,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    QT_MULTIMEDIA_OK = True
except Exception:  # noqa: BLE001 - Qt may be built without multimedia
    QAudioOutput = QMediaPlayer = QVideoSink = None  # type: ignore[assignment]
    QT_MULTIMEDIA_OK = False


@dataclass
class Segment:
    """One clip on the preview timeline."""

    path: str
    start: float  # in-point inside the source file (s)
    duration: float  # how long it plays (s)
    has_video: bool
    offset: float = 0.0  # where it begins on the montage timeline (s)
    # framing on the output canvas (see studio.Clip)
    fit: str = "fit"
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    volume: float = 1.0  # 0 = muted


@dataclass
class MusicBed:
    """Background music as the render mixes it: the song part start..end,
    coming in at *offset* on the montage timeline, optionally looped."""

    path: str
    start: float
    end: float
    offset: float = 0.0
    loop: bool = True
    volume: float = 0.35
    fade_out: bool = True

    def position(self, t: float) -> float | None:
        """Song time to play at montage time *t* (None = silent there)."""
        length = self.end - self.start
        if length <= 0 or t < self.offset:
            return None
        rel = t - self.offset
        if self.loop:
            rel %= length
        elif rel >= length:
            return None
        return self.start + rel


@dataclass
class TransitionMark:
    """A transition on the montage timeline. The preview cuts at its middle
    (one player can't show two clips at once); dips to black / white are
    drawn, other kinds are labelled while they play."""

    at: float  # middle of the transition (s)
    duration: float
    kind: str
    label: str


def frame_geometry(fw: float, fh: float, rect: QRectF, fit: str, zoom: float,
                   pan_x: float, pan_y: float) -> tuple[QRectF, QRectF]:
    """(source rect inside the frame, target rect on the canvas) — the same
    scale / crop / pad steps `studio._frame_filter` gives ffmpeg."""
    cover = fit == "fill"
    scale = (max if cover else min)(rect.width() / fw, rect.height() / fh) * max(zoom, 1.0)
    sw, sh = fw * scale, fh * scale
    cw, ch = min(sw, rect.width()), min(sh, rect.height())
    cx, cy = (sw - cw) * pan_x, (sh - ch) * pan_y
    source = QRectF(cx / scale, cy / scale, cw / scale, ch / scale)
    target = QRectF(rect.center().x() - cw / 2, rect.center().y() - ch / 2, cw, ch)
    return source, target


def fmt_time(seconds: float) -> str:
    """M:SS.s — tenths keep in/out points precise without clutter."""
    seconds = max(0.0, seconds)
    tenths = round(seconds * 10)
    whole, frac = divmod(tenths, 10)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    base = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return f"{base}.{frac}"


def transport_icon(kind: str, color: str, size: int = 18) -> QIcon:
    """Play / pause drawn as shapes (the ⏸ glyph is missing from many fonts)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    if kind == "pause":
        w = size * 0.26
        p.drawRoundedRect(QRectF(size * 0.2, size * 0.15, w, size * 0.7), 1.5, 1.5)
        p.drawRoundedRect(QRectF(size * 0.8 - w, size * 0.15, w, size * 0.7), 1.5, 1.5)
    else:
        p.drawPolygon([QPointF(size * 0.25, size * 0.12), QPointF(size * 0.25, size * 0.88),
                       QPointF(size * 0.88, size * 0.5)])
    p.end()
    return QIcon(pm)


# ── video canvas with draggable subtitles ─────────────────────────────────


class VideoCanvas(QWidget):
    """Paints the current frame onto the output-shaped canvas, plus subtitles."""

    cue_moved = Signal(int, float, float)  # row, x, y (fractions of the frame)
    cue_clicked = Signal(int)
    pan_dragged = Signal(float, float)  # new pan_x, pan_y while dragging the picture
    pan_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._frame: QImage | None = None
        self._aspect = (16, 9)
        self._cues: list[tuple[int, SubtitleCue]] = []
        self._style = SubtitleStyle()
        self._selected: int | None = None
        self._placeholder = ""
        self._hits: list[tuple[int, QRectF]] = []
        self._drag: tuple[int, QPointF] | None = None  # row, grab offset
        self._drag_pos: tuple[float, float] | None = None
        self._colors = {"bg": "#05060f", "accent": "#7c5cff", "muted": "#7b80aa"}
        self._time = 0.0
        self._framing = ("fit", 1.0, 0.5, 0.5)
        self._pannable = False
        self._pan_drag: tuple[QPointF, float, float] | None = None
        self._dip: tuple[str, float] | None = None  # colour, opacity
        self._badge = ""

    def sizeHint(self) -> QSize:
        return QSize(640, 360)

    # state ---------------------------------------------------------------

    def set_colors(self, bg: str, accent: str, muted: str) -> None:
        self._colors = {"bg": bg, "accent": accent, "muted": muted}
        self.update()

    def set_aspect(self, width: int, height: int) -> None:
        self._aspect = (max(1, width), max(1, height))
        self.update()

    def set_frame(self, image: QImage | None) -> None:
        self._frame = image
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def set_cues(self, cues: list[tuple[int, SubtitleCue]], selected: int | None) -> None:
        self._cues = cues
        self._selected = selected
        self.update()

    def set_style(self, style: SubtitleStyle) -> None:
        self._style = style
        self.update()

    def set_framing(self, fit: str, zoom: float, pan_x: float, pan_y: float) -> None:
        self._framing = (fit, zoom, pan_x, pan_y)
        self.update()

    def set_pannable(self, on: bool) -> None:
        """Let the picture be dragged to choose what stays in frame."""
        self._pannable = on
        if not on:
            self._pan_drag = None
        self.update()

    def set_transition_overlay(self, dip: tuple[str, float] | None, badge: str) -> None:
        if (dip, badge) != (self._dip, self._badge):
            self._dip, self._badge = dip, badge
            self.update()

    def _overflow(self) -> tuple[float, float, float]:
        """How far the scaled picture overhangs the canvas (w, h) and its scale."""
        if self._frame is None or self._frame.isNull():
            return 0.0, 0.0, 1.0
        rect = self.canvas_rect()
        fw, fh = self._frame.width(), self._frame.height()
        fit, zoom, _px, _py = self._framing
        scale = (max if fit == "fill" else min)(rect.width() / fw, rect.height() / fh) * zoom
        return max(0.0, fw * scale - rect.width()), max(0.0, fh * scale - rect.height()), scale

    def set_time(self, seconds: float) -> None:
        """Playhead time, for fading lines in and out."""
        self._time = seconds
        self.update()

    # geometry ------------------------------------------------------------

    def canvas_rect(self) -> QRectF:
        """The output frame, fitted (letterboxed) into the widget."""
        aw, ah = self._aspect
        w, h = self.width(), self.height()
        scale = min(w / aw, h / ah)
        cw, ch = aw * scale, ah * scale
        return QRectF((w - cw) / 2, (h - ch) / 2, cw, ch)

    def _font(self, rect: QRectF) -> QFont:
        # libass treats Fontsize as the font's full line height (ascent +
        # descent), Qt's pixel size as its em height. CJK fonts are ~1.45 em
        # tall, so convert or the preview draws text far larger than the render.
        target = self._style.size * subtitle_scale(int(rect.height()))
        f = QFont(self._style.font or SUBTITLE_FONT_NAME)
        f.setBold(self._style.bold)
        f.setPixelSize(100)
        fm = QFontMetricsF(f)
        ratio = (fm.ascent() + fm.descent()) / 100 or 1.0
        f.setPixelSize(max(6, round(target / ratio)))
        return f

    def _cue_box(self, cue: SubtitleCue, rect: QRectF, text_w: float,
                 text_h: float) -> tuple[QRectF, int]:
        """Where the text block goes, and its horizontal alignment
        (-1 left, 0 centre, 1 right) — the same rules libass applies."""
        if cue.x is not None and cue.y is not None:
            anchor = cue.anchor if 1 <= cue.anchor <= 9 else 5
            px = rect.x() + cue.x * rect.width()
            py = rect.y() + cue.y * rect.height()
        else:
            anchor = 8 if self._style.position == "top" else 2
            margin = SUBTITLE_MARGIN * subtitle_scale(int(rect.height()))
            px = rect.center().x()
            py = rect.top() + margin if anchor == 8 else rect.bottom() - margin
        col = (anchor - 1) % 3  # 0 left, 1 centre, 2 right
        row = (anchor - 1) // 3  # 0 bottom, 1 middle, 2 top
        left = px - (0, text_w / 2, text_w)[col]
        top = py - (text_h, text_h / 2, 0)[row]
        return QRectF(left, top, text_w, text_h), col - 1

    # painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(self._colors["bg"]))
        rect = self.canvas_rect()
        p.fillRect(rect, QColor("#000000"))

        if self._frame is not None and not self._frame.isNull():
            source, target = frame_geometry(self._frame.width(), self._frame.height(), rect,
                                            *self._framing)
            p.drawImage(target, self._frame, source)
            if self._pannable and (self._pan_drag is not None or self.underMouse()):
                p.setPen(QPen(QColor(self._colors["accent"]), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(1, 1, -1, -1))
        elif self._placeholder:
            p.setPen(QColor(self._colors["muted"]))
            f = QFont(self.font())
            f.setPixelSize(15)
            p.setFont(f)
            p.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self._placeholder)

        if self._dip is not None:
            color = QColor(self._dip[0])
            color.setAlphaF(min(max(self._dip[1], 0.0), 1.0))
            p.fillRect(rect, color)
        self._hits = []
        if self._cues:
            self._paint_cues(p, rect)
        if self._badge:
            f = QFont(self.font())
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetricsF(f)
            badge = QRectF(rect.left() + 10, rect.top() + 10,
                           fm.horizontalAdvance(self._badge) + 20, fm.height() + 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(badge, 6, 6)
            p.setPen(QColor("#ffffff"))
            p.drawText(badge, Qt.AlignCenter, self._badge)
        p.end()

    def _paint_cues(self, p: QPainter, rect: QRectF) -> None:
        font = self._font(rect)
        fm = QFontMetricsF(font)
        k = subtitle_scale(int(rect.height()))
        fill = QColor(color_hex(self._style.color))
        bg = None
        if self._style.background:
            bg = QColor(color_hex(self._style.background, "#000000"))
            bg.setAlphaF(min(max(self._style.bg_opacity, 0.0), 1.0))
            outline = 0.0
        else:
            outline = max(1.0, 2 * k) if self._style.outline else 0.0
        pad = box_padding(self._style.size * k)
        p.save()
        p.setClipRect(rect)
        fade = max(0.0, self._style.fade)
        for row, cue in self._cues:
            if self._drag is not None and self._drag[0] == row and self._drag_pos:
                cue = SubtitleCue(cue.start, cue.end, cue.text, *self._drag_pos, anchor=5)
            lines = cue.text.split("\n")
            line_h = fm.height()
            text_h = line_h * len(lines)
            text_w = max(fm.horizontalAdvance(line) for line in lines)
            box, align = self._cue_box(cue, rect, text_w, text_h)
            opacity = 1.0
            if fade > 0 and self._drag is None:
                f = min(fade, (cue.end - cue.start) / 2) or 1.0
                opacity = min(1.0, max(0.0, min(self._time - cue.start, cue.end - self._time) / f))
            p.setOpacity(opacity)
            path = QPainterPath()
            for i, line in enumerate(lines):
                lw = fm.horizontalAdvance(line)
                lx = box.left() + (0.0, (text_w - lw) / 2, text_w - lw)[align + 1]
                top = box.top() + i * line_h
                if bg is not None:  # one box per line, like libass
                    p.fillRect(QRectF(lx - pad, top - pad / 2, lw + 2 * pad, line_h + pad), bg)
                path.addText(QPointF(lx, top + fm.ascent()), font, line)
            if outline:
                p.strokePath(path, QPen(QColor("#000000"), outline * 2, Qt.SolidLine,
                                        Qt.RoundCap, Qt.RoundJoin))
            p.fillPath(path, fill)
            p.setOpacity(1.0)
            hit = box.adjusted(-8, -6, 8, 6)
            if row == self._selected:
                pen = QPen(QColor(self._colors["accent"]), 1.5, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(hit, 6, 6)
            self._hits.append((row, hit))
        p.restore()

    # dragging ------------------------------------------------------------

    def _hit(self, pos: QPointF) -> tuple[int, QRectF] | None:
        for row, rect in reversed(self._hits):
            if rect.contains(pos):
                return row, rect
        return None

    def mousePressEvent(self, event) -> None:
        hit = self._hit(event.position())
        if hit is None and event.button() == Qt.LeftButton and self._pannable \
                and self.canvas_rect().contains(event.position()):
            _fit, _zoom, px, py = self._framing
            self._pan_drag = (event.position(), px, py)
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return None
        if hit is None or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        row, rect = hit
        self._drag = (row, event.position() - rect.center())
        self._drag_pos = None
        self.setCursor(QCursor(Qt.ClosedHandCursor))
        self.cue_clicked.emit(row)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_drag is not None:
            start, px0, py0 = self._pan_drag
            ow, oh, _scale = self._overflow()
            delta = event.position() - start
            # dragging the picture right shows more of its left side
            px = min(max(px0 - delta.x() / ow, 0.0), 1.0) if ow > 0.5 else px0
            py = min(max(py0 - delta.y() / oh, 0.0), 1.0) if oh > 0.5 else py0
            self.pan_dragged.emit(round(px, 4), round(py, 4))
            return
        if self._drag is None:
            over = self._hit(event.position()) is not None
            pan = self._pannable and self.canvas_rect().contains(event.position())
            self.setCursor(QCursor(Qt.OpenHandCursor if over or pan else Qt.ArrowCursor))
            self.update()
            return
        rect = self.canvas_rect()
        center = event.position() - self._drag[1]
        x = min(max((center.x() - rect.x()) / rect.width(), 0.0), 1.0)
        y = min(max((center.y() - rect.y()) / rect.height(), 0.0), 1.0)
        self._drag_pos = (x, y)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._pan_drag is not None:
            self._pan_drag = None
            self.setCursor(QCursor(Qt.OpenHandCursor))
            self.pan_finished.emit()
            self.update()
            return
        if self._drag is None:
            return super().mouseReleaseEvent(event)
        row = self._drag[0]
        pos = self._drag_pos
        self._drag = None
        self._drag_pos = None
        self.setCursor(QCursor(Qt.OpenHandCursor))
        if pos is not None:
            self.cue_moved.emit(row, round(pos[0], 4), round(pos[1], 4))


# ── composite preview ─────────────────────────────────────────────────────


class StudioPreview(QWidget):
    """Canvas + play button, chaining the montage's clips on one QMediaPlayer."""

    position_changed = Signal(float)
    cue_moved = Signal(int, float, float)
    cue_clicked = Signal(int)
    pan_dragged = Signal(int, float, float)  # segment, pan_x, pan_y
    pan_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[Segment] = []
        self._seg_idx = -1
        self._source = ""
        self._pending_seek: float | None = None  # seconds within the source
        # where the player was last told to go; some backends drop a seek made
        # right after a source switch, so it is re-issued until the player
        # actually reports that position
        self._seek_target: float | None = None
        self._seek_misses = 0
        # after setSource the player may still report the *previous* file's
        # "loaded" status; wait for sourceChanged before seeking
        self._awaiting_source = False
        self._want_play = False
        self._pos = 0.0
        self._duration = 0.0
        self._cues: list[tuple[int, SubtitleCue]] = []
        self._selected_cue: int | None = None
        self._texts = {"empty": "", "audio": "♪"}
        self._icon_color = "#eceeff"
        self._transitions: list[TransitionMark] = []
        self._pan_segment: int | None = None
        self._music: MusicBed | None = None
        self._music_source = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.canvas = VideoCanvas()
        self.canvas.cue_moved.connect(self.cue_moved)
        self.canvas.cue_clicked.connect(self.cue_clicked)
        self.canvas.pan_dragged.connect(lambda x, y: self.pan_dragged.emit(self._seg_idx, x, y))
        self.canvas.pan_finished.connect(self.pan_finished)
        lay.addWidget(self.canvas, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("play_btn")
        self.play_btn.setFixedSize(52, 36)
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_lbl = QLabel("0:00.0 / 0:00.0")
        self.time_lbl.setObjectName("time_lbl")
        row.addWidget(self.play_btn)
        row.addWidget(self.time_lbl)
        row.addStretch()
        lay.addLayout(row)

        self.player = None
        if QT_MULTIMEDIA_OK:
            self.player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self.player.setAudioOutput(self._audio)
            self._sink = QVideoSink(self)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self.player.setVideoSink(self._sink)
            self.player.positionChanged.connect(self._on_player_position)
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.sourceChanged.connect(self._on_source_changed)
            self.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())
            self.player.playbackStateChanged.connect(lambda _s: self._sync_music())
            # the background music plays on its own player, kept in step with
            # the montage timeline by _sync_music()
            self.music_player = QMediaPlayer(self)
            self._music_audio = QAudioOutput(self)
            self.music_player.setAudioOutput(self._music_audio)
        self._update_play_icon()
        self._refresh_controls()

    # public API ----------------------------------------------------------

    def position(self) -> float:
        return self._pos

    def duration(self) -> float:
        return self._duration

    def is_playing(self) -> bool:
        return (
            self.player is not None
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def set_texts(self, *, empty: str, audio: str) -> None:
        self._texts = {"empty": empty, "audio": audio}
        self._update_placeholder()

    def set_colors(self, palette: dict[str, str]) -> None:
        self.canvas.set_colors(palette["PREVIEW_BG"], palette["ACCENT"], palette["TEXT_MUTED"])
        self._icon_color = palette["TEXT"]
        self._update_play_icon()

    def set_aspect(self, width: int, height: int) -> None:
        self.canvas.set_aspect(width, height)

    def set_style(self, style: SubtitleStyle) -> None:
        self.canvas.set_style(style)

    def clear(self) -> None:
        self._stop_player()
        self._segments = []
        self._seg_idx = -1
        self._duration = 0.0
        self.canvas.set_frame(None)
        self._set_pos(0.0)
        self._update_placeholder()
        self._refresh_controls()

    def load_timeline(self, segments: list[Segment], position: float | None = None) -> None:
        """Play *segments* back to back; keep the playhead unless *position*."""
        pos = self._pos if position is None else position
        offset = 0.0
        for seg in segments:
            seg.offset = offset
            offset += seg.duration
        self._segments = segments
        self._duration = offset
        if segments:
            self.seek(min(pos, max(0.0, offset - 0.05)))
        else:
            self.clear()
        self._refresh_controls()

    def set_cues(self, cues: list[tuple[int, SubtitleCue]], selected: int | None) -> None:
        self._cues = cues
        self._selected_cue = selected
        self._refresh_overlay()

    def set_music(self, bed: MusicBed | None) -> None:
        self._music = bed
        if self.player is None:
            return
        path = bed.path if bed else ""
        if path != self._music_source:
            self._music_source = path
            self.music_player.stop()
            self.music_player.setSource(QUrl.fromLocalFile(path) if path else QUrl())
        self._sync_music(force=True)

    def music_bed(self) -> MusicBed | None:
        return self._music

    def set_muted(self, muted: bool) -> None:
        """Silence both players (tests and scripted recordings)."""
        if self.player is not None:
            self._audio.setMuted(muted)
            self._music_audio.setMuted(muted)

    def _sync_music(self, force: bool = False) -> None:
        """Play / pause / re-seek the music to match the montage playhead."""
        if self.player is None:
            return
        mp, bed, t = self.music_player, self._music, self._pos
        pos = bed.position(t) if bed and t < self._duration else None
        playing = self.is_playing() or (self._want_play and bool(self._segments))
        if bed is not None:
            fade = 1.0
            if bed.fade_out and self._duration > 4:
                fade = min(1.0, max(0.0, (self._duration - t) / 3))
            self._music_audio.setVolume(min(1.0, max(0.0, bed.volume * fade)))
        if pos is None or not playing:
            if mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                mp.pause()
            if pos is not None and force:
                mp.setPosition(int(pos * 1000))
            return
        if force or abs(mp.position() / 1000 - pos) > 0.3:
            mp.setPosition(int(pos * 1000))
        if mp.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            mp.play()

    def set_transitions(self, marks: list[TransitionMark]) -> None:
        self._transitions = marks
        self._refresh_overlay()

    def set_pan_segment(self, index: int | None) -> None:
        """The segment whose picture may be dragged (the selected clip)."""
        self._pan_segment = index
        self._refresh_framing()

    def set_segment_volume(self, index: int, volume: float) -> None:
        if 0 <= index < len(self._segments):
            self._segments[index].volume = volume
            if index == self._seg_idx and self.player is not None:
                self._audio.setVolume(min(1.0, max(0.0, volume)))

    def set_segment_framing(self, index: int, fit: str, zoom: float, pan_x: float,
                            pan_y: float) -> None:
        """Update one segment's framing without reloading the timeline."""
        if 0 <= index < len(self._segments):
            seg = self._segments[index]
            seg.fit, seg.zoom, seg.pan_x, seg.pan_y = fit, zoom, pan_x, pan_y
            self._refresh_framing()

    def _refresh_framing(self) -> None:
        seg = self._segments[self._seg_idx] if 0 <= self._seg_idx < len(self._segments) else None
        if seg is None:
            self.canvas.set_framing("fit", 1.0, 0.5, 0.5)
            self.canvas.set_pannable(False)
            return
        self.canvas.set_framing(seg.fit, seg.zoom, seg.pan_x, seg.pan_y)
        self.canvas.set_pannable(seg.has_video and self._seg_idx == self._pan_segment)

    def seek(self, seconds: float) -> None:
        """Jump to *seconds* on the montage timeline."""
        if not self._segments:
            return
        seconds = min(max(seconds, 0.0), self._duration)
        idx = len(self._segments) - 1
        for i, seg in enumerate(self._segments):
            if seconds < seg.offset + seg.duration:
                idx = i
                break
        seg = self._segments[idx]
        self._show_segment(idx, seg.start + (seconds - seg.offset), play=self.is_playing())

    def toggle_play(self) -> None:
        if self.player is None or not self._segments:
            return
        if self.is_playing():
            self._want_play = False
            self.player.pause()
            return
        if self._pos >= self._duration - 0.05:  # parked at the end: start over
            self.seek(0.0)
        self._want_play = True
        self.player.play()

    def stop(self) -> None:
        self._stop_player()

    # internals -----------------------------------------------------------

    def _stop_player(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
            self.music_player.pause()
        self._source = ""
        self._want_play = False

    def _show_segment(self, idx: int, local: float, *, play: bool) -> None:
        seg = self._segments[idx]
        self._seg_idx = idx
        self._refresh_framing()
        if self.player is not None:
            self._audio.setVolume(min(1.0, max(0.0, seg.volume)))
        self._set_pos(seg.offset + (local - seg.start))
        if not seg.has_video:
            self.canvas.set_frame(None)
        self._update_placeholder()
        if self.player is None:
            return
        self._want_play = play
        if self._source != seg.path:
            self._source = seg.path
            self._pending_seek = local
            self._seek_target = None
            self._awaiting_source = True
            self.player.setSource(QUrl.fromLocalFile(seg.path))
            if play:
                self.player.play()
            else:
                self.player.pause()  # decodes and shows the first frame
        elif self._pending_seek is not None:
            # still loading this file: the newest jump replaces the queued one
            self._pending_seek = local
            if play:
                self.player.play()
        else:
            self._seek_to(local)
            if play and not self.is_playing():
                self.player.play()

    def _on_source_changed(self, _url) -> None:
        self._awaiting_source = False
        status = self.player.mediaStatus()
        if self._pending_seek is not None and status in (
                QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            target, self._pending_seek = self._pending_seek, None
            self._seek_to(target)

    def _seek_to(self, local: float) -> None:
        self._seek_target = local
        self._seek_misses = 0
        self.player.setPosition(int(local * 1000))

    def _set_pos(self, seconds: float) -> None:
        jumped = abs(seconds - self._pos) > 0.5
        self._pos = seconds
        self.time_lbl.setText(f"{fmt_time(seconds)} / {fmt_time(self._duration)}")
        self._refresh_overlay()
        self._sync_music(force=jumped and not self.is_playing())
        self.position_changed.emit(seconds)

    def _refresh_overlay(self) -> None:
        t = self._pos
        active = [(row, c) for row, c in self._cues if c.start <= t < c.end]
        self.canvas.set_time(t)
        self.canvas.set_cues(active, self._selected_cue)
        dip, badge = None, ""
        for mark in self._transitions:
            half = mark.duration / 2
            if half > 0 and abs(t - mark.at) < half:
                if mark.kind in ("fadeblack", "fadewhite"):
                    color = "#000000" if mark.kind == "fadeblack" else "#ffffff"
                    dip = (color, 1.0 - abs(t - mark.at) / half)
                else:
                    badge = mark.label
                break
        self.canvas.set_transition_overlay(dip, badge)

    def _update_placeholder(self) -> None:
        seg = self._segments[self._seg_idx] if 0 <= self._seg_idx < len(self._segments) else None
        if seg is None:
            self.canvas.set_placeholder(self._texts["empty"])
        elif not seg.has_video:
            name = seg.path.replace("\\", "/").rsplit("/", 1)[-1]
            self.canvas.set_placeholder(f"{self._texts['audio']}\n{name}")
        else:
            self.canvas.set_placeholder("")

    def _update_play_icon(self) -> None:
        self.play_btn.setIcon(
            transport_icon("pause" if self.is_playing() else "play", self._icon_color)
        )

    def _refresh_controls(self) -> None:
        self.play_btn.setEnabled(bool(self._segments) and self.player is not None)

    # player callbacks ----------------------------------------------------

    def _on_frame(self, frame) -> None:
        seg = self._segments[self._seg_idx] if 0 <= self._seg_idx < len(self._segments) else None
        if seg is None or not seg.has_video:
            return
        img = frame.toImage()
        if not img.isNull():
            self.canvas.set_frame(img)

    def _on_status(self, status) -> None:
        loaded = (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        if status == QMediaPlayer.MediaStatus.LoadingMedia and not self._awaiting_source \
                and self._pending_seek is None and self._seek_target is not None:
            # (re)loading resets the position: go back to where we were asked
            self._pending_seek = self._seek_target
        elif status in loaded and self._pending_seek is not None and not self._awaiting_source:
            target, self._pending_seek = self._pending_seek, None
            self._seek_to(target)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._advance()

    def _on_player_position(self, ms: int) -> None:
        if self._pending_seek is not None or not (0 <= self._seg_idx < len(self._segments)):
            return
        seg = self._segments[self._seg_idx]
        local = ms / 1000.0
        if self._seek_target is not None:
            if abs(local - self._seek_target) < 0.5 and self.is_playing() \
                    or self._seek_misses > 30:
                self._seek_target = None  # playing from there (or give up and follow)
            elif abs(local - self._seek_target) < 0.5:
                self._set_pos(seg.offset + max(0.0, local - seg.start))
                return
            else:
                # still somewhere else: the seek was dropped, ask again now and
                # then (not on every report, which would stall playback)
                self._seek_misses += 1
                if self._seek_misses % 3 == 0:
                    self.player.setPosition(int(self._seek_target * 1000))
                return
        if local >= seg.start + seg.duration:
            if self.is_playing():
                self._advance()
            return
        self._set_pos(seg.offset + max(0.0, local - seg.start))

    def _advance(self) -> None:
        """Clip finished: continue with the next one, or park at the end."""
        if self._seg_idx + 1 < len(self._segments):
            nxt = self._seg_idx + 1
            self._show_segment(nxt, self._segments[nxt].start, play=self._want_play)
            return
        if self.player is not None:
            self.player.pause()
        self._want_play = False
        self._set_pos(self._duration)
