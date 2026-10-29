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
    QApplication,
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
    ImageOverlay,
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
    fade: float = 0.0  # fade in / out at the song's own edges

    def gain(self, t: float, total: float) -> float:
        """Volume at montage time *t*: edge fades and the end-of-video fade."""
        level = self.volume
        if self.fade > 0:
            level *= min(1.0, max(0.0, (t - self.offset) / self.fade))
            if not self.loop:
                stop = self.offset + (self.end - self.start)
                level *= min(1.0, max(0.0, (stop - t) / self.fade))
        if self.fade_out and total > 4:
            level *= min(1.0, max(0.0, (total - t) / 3))
        return level

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
    """A transition on the montage timeline. The main player switches clips
    at its middle; a second player shows the other clip meanwhile, and the
    canvas blends the two the way the render does (dips just fade the frame)."""

    at: float  # middle of the transition (s)
    duration: float
    kind: str
    label: str
    incoming: int = -1  # the segment it leads into (the outgoing one is incoming - 1)

    def progress(self, t: float) -> float | None:
        """0..1 through the transition at time *t* (None outside it)."""
        if self.duration <= 0 or abs(t - self.at) >= self.duration / 2:
            return None
        return (t - (self.at - self.duration / 2)) / self.duration


# transitions the canvas draws from two frames (the rest are dips or cuts)
BLENDED = ("fade", "dissolve", "wipeleft", "slideleft", "circleopen", "zoomin")


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
    image_clicked = Signal(int)
    image_changed = Signal(int, float, float, float, float)  # row, centre x, y, width, rotation

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
        # a transition in progress: the other clip's frame and framing, the
        # kind, how far through (0..1), and whether the main frame is the outgoing one
        # (kind, progress, outgoing frame, its framing, incoming frame, its framing)
        self._blend: tuple | None = None
        self._images: list[tuple[int, ImageOverlay]] = []  # the ones showing now
        self._selected_image: int | None = None
        self._pictures: dict[str, QImage] = {}  # loaded once per file
        # row, box (unrotated), its rotation, resize grip, rotate knob (unrotated frame)
        self._img_hits: list[tuple[int, QRectF, float, QRectF, QRectF]] = []
        # dragging a picture: row, "move" | "size" | "turn", press point, original
        # x / y / width / rotation
        self._img_drag: tuple[int, str, QPointF, float, float, float, float] | None = None
        self._img_live: tuple[float, float, float, float] | None = None

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

    def set_images(self, images: list[tuple[int, ImageOverlay]], selected: int | None) -> None:
        self._images, self._selected_image = images, selected
        self.update()

    def picture(self, path: str) -> QImage:
        img = self._pictures.get(path)
        if img is None:
            img = QImage(path)
            self._pictures[path] = img
        return img

    def _image_box(self, img: ImageOverlay, rect: QRectF) -> QRectF:
        pic = self.picture(img.path)
        w = rect.width() * img.width
        h = w * pic.height() / max(1, pic.width()) if not pic.isNull() else w
        cx, cy = rect.x() + img.x * rect.width(), rect.y() + img.y * rect.height()
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _paint_images(self, p: QPainter, rect: QRectF) -> None:
        self._img_hits = []
        p.save()
        p.setClipRect(rect)
        for row, img in self._images:
            if self._img_drag is not None and self._img_drag[0] == row and self._img_live:
                x, y, w, rot = self._img_live
                img = ImageOverlay(img.path, img.start, img.end, x, y, w,
                                   opacity=img.opacity, fade=img.fade, rotation=rot)
            pic = self.picture(img.path)
            box = self._image_box(img, rect)
            level = img.opacity
            if img.fade > 0 and self._img_drag is None:
                fade = min(img.fade, (img.end - img.start) / 2) or 1.0
                level *= min(1.0, max(0.0, min(self._time - img.start, img.end - self._time) / fade))
            # draw in the picture's own (rotated) frame, centred on its centre
            p.save()
            p.translate(box.center())
            p.rotate(img.rotation)
            local = QRectF(-box.width() / 2, -box.height() / 2, box.width(), box.height())
            p.setOpacity(level)
            if not pic.isNull():
                p.drawImage(local, pic)
            p.setOpacity(1.0)
            grip = QRectF(local.right() - 7, local.bottom() - 7, 14, 14)
            knob = QRectF(-7, local.top() - 30, 14, 14)
            if row == self._selected_image:
                p.setPen(QPen(QColor(self._colors["accent"]), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(local)
                p.drawLine(QPointF(0, local.top()), QPointF(0, knob.bottom()))
                p.setPen(QPen(QColor("#ffffff"), 1.2))
                p.setBrush(QColor(self._colors["accent"]))
                p.drawRect(grip)
                p.drawEllipse(knob)
            p.restore()
            self._img_hits.append((row, box, img.rotation, grip, knob))
        p.restore()

    @staticmethod
    def _to_local(pos: QPointF, box: QRectF, rotation: float) -> QPointF:
        """*pos* in a picture's own frame: centred on it, rotation undone."""
        from math import cos, radians, sin

        d = pos - box.center()
        a = radians(-rotation)
        return QPointF(d.x() * cos(a) - d.y() * sin(a), d.x() * sin(a) + d.y() * cos(a))

    def _image_hit(self, pos: QPointF) -> tuple[int, str] | None:
        for row, box, rotation, grip, knob in reversed(self._img_hits):  # top-most first
            local = self._to_local(pos, box, rotation)
            if row == self._selected_image:
                if knob.adjusted(-5, -5, 5, 5).contains(local):
                    return row, "turn"
                if grip.adjusted(-4, -4, 4, 4).contains(local):
                    return row, "size"
            if QRectF(-box.width() / 2, -box.height() / 2, box.width(), box.height()).contains(local):
                return row, "move"
        return None

    def set_framing(self, fit: str, zoom: float, pan_x: float, pan_y: float) -> None:
        self._framing = (fit, zoom, pan_x, pan_y)
        self.update()

    def set_pannable(self, on: bool) -> None:
        """Let the picture be dragged to choose what stays in frame."""
        self._pannable = on
        if not on:
            self._pan_drag = None
        self.update()

    def set_blend(self, kind: str, progress: float, outgoing: QImage | None, out_framing: tuple,
                  incoming: QImage | None, in_framing: tuple) -> None:
        self._blend = (kind, progress, outgoing, out_framing, incoming, in_framing)
        self.update()

    def clear_blend(self) -> None:
        if self._blend is not None:
            self._blend = None
            self.update()

    def blending(self) -> bool:
        b = self._blend
        return b is not None and all(img is not None and not img.isNull() for img in (b[2], b[4]))

    def _draw_frame(self, p: QPainter, rect: QRectF, img: QImage, framing: tuple, *,
                    dx: float = 0.0, scale: float = 1.0, opacity: float = 1.0,
                    clip: QPainterPath | None = None) -> None:
        source, target = frame_geometry(img.width(), img.height(), rect, *framing)
        p.save()
        p.setClipRect(rect)
        if clip is not None:
            p.setClipPath(clip, Qt.IntersectClip)
        if scale != 1.0:
            p.translate(rect.center())
            p.scale(scale, scale)
            p.translate(-rect.center())
        p.translate(dx, 0)
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawImage(target, img, source)
        p.restore()

    def _paint_transition(self, p: QPainter, rect: QRectF) -> None:
        """Both clips, combined like ffmpeg's xfade of the same name."""
        from math import hypot

        kind, prog, o_img, o_fr, i_img, i_fr = self._blend
        w, h = rect.width(), rect.height()
        if kind == "slideleft":  # both move left together
            self._draw_frame(p, rect, o_img, o_fr, dx=-w * prog)
            self._draw_frame(p, rect, i_img, i_fr, dx=w * (1 - prog))
        elif kind == "zoomin":  # the outgoing clip grows and fades away
            self._draw_frame(p, rect, i_img, i_fr)
            self._draw_frame(p, rect, o_img, o_fr, scale=1 + prog, opacity=1 - prog)
        else:
            self._draw_frame(p, rect, o_img, o_fr)
            if kind == "wipeleft":  # the edge sweeps from right to left
                clip = QPainterPath()
                clip.addRect(QRectF(rect.right() - w * prog, rect.top(), w * prog, h))
                self._draw_frame(p, rect, i_img, i_fr, clip=clip)
            elif kind == "circleopen":  # a circle opening from the centre
                clip = QPainterPath()
                r = prog * hypot(w, h) / 2
                clip.addEllipse(rect.center(), r, r)
                self._draw_frame(p, rect, i_img, i_fr, clip=clip)
            else:  # fade / dissolve: the incoming clip fades in on top
                self._draw_frame(p, rect, i_img, i_fr, opacity=prog)

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
            if self.blending():
                self._paint_transition(p, rect)
            else:
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
        if self._images:
            self._paint_images(p, rect)
        else:
            self._img_hits = []
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
        img_hit = self._image_hit(event.position()) if hit is None else None
        if img_hit is not None and event.button() == Qt.LeftButton:
            row, part = img_hit
            img = next(i for r, i in self._images if r == row)
            self._img_drag = (row, part, event.position(), img.x, img.y, img.width, img.rotation)
            self._img_live = None
            self.setCursor(QCursor(Qt.SizeFDiagCursor if part == "size" else Qt.ClosedHandCursor))
            self.image_clicked.emit(row)
            return None
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
        if self._img_drag is not None:
            row, part, start, x0, y0, w0, r0 = self._img_drag
            rect = self.canvas_rect()
            delta = event.position() - start
            if part == "move":
                x = min(max(x0 + delta.x() / rect.width(), 0.0), 1.0)
                y = min(max(y0 + delta.y() / rect.height(), 0.0), 1.0)
                self._img_live = (x, y, w0, r0)
            elif part == "size":  # the corner: grow / shrink around the centre
                img = next(i for r, i in self._images if r == row)
                box = self._image_box(img, rect)
                grow = self._to_local(event.position(), box, r0).x() \
                    - self._to_local(start, box, r0).x()
                w = min(max(w0 + 2 * grow / rect.width(), 0.03), 2.0)
                self._img_live = (x0, y0, w, r0)
            else:  # the knob: the angle from the centre to the mouse
                from math import atan2, degrees

                centre = QPointF(rect.x() + x0 * rect.width(), rect.y() + y0 * rect.height())
                d = event.position() - centre
                angle = (degrees(atan2(d.y(), d.x())) + 90) % 360
                if not event.modifiers() & Qt.AltModifier:  # snap to the square angles
                    nearest = round(angle / 90) * 90
                    if abs(angle - nearest) < 6:
                        angle = nearest % 360
                angle = round(angle - 360 if angle > 180 else angle, 1)
                self._img_live = (x0, y0, w0, angle)
            self.update()
            return
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
            img = None if over else self._image_hit(event.position())
            pan = self._pannable and self.canvas_rect().contains(event.position())
            if img is not None and img[1] == "size":
                self.setCursor(QCursor(Qt.SizeFDiagCursor))
            elif img is not None and img[1] == "turn":
                self.setCursor(QCursor(Qt.CrossCursor))
            else:
                self.setCursor(QCursor(Qt.OpenHandCursor if over or pan or img
                                       else Qt.ArrowCursor))
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
        if self._img_drag is not None:
            row, live = self._img_drag[0], self._img_live
            self._img_drag = self._img_live = None
            self.setCursor(QCursor(Qt.OpenHandCursor))
            if live is not None:
                self.image_changed.emit(row, *(round(v, 4) for v in live))
            self.update()
            return
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
    image_clicked = Signal(int)
    image_changed = Signal(int, float, float, float, float)

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
        self._images: list[tuple[int, ImageOverlay]] = []
        self._selected_image: int | None = None
        self._aux_source = ""
        self._aux_pending: float | None = None
        self._aux_awaiting = False  # like the main player: ignore the old file's "loaded"
        self._aux_img: QImage | None = None
        # the latest frame of each file (from either player): a transition
        # blends these, so the two players swapping files never leaves a gap
        self._last_frame: dict[str, QImage] = {}
        self._main_img: QImage | None = None  # the main player's own latest frame
        self._music: list[MusicBed] = []
        self._music_players: list[tuple[QMediaPlayer, QAudioOutput, str]] = []
        # headless (tests, scripts): the speakers stay silent
        self._muted = QApplication.platformName() == "offscreen"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.canvas = VideoCanvas()
        self.canvas.cue_moved.connect(self.cue_moved)
        self.canvas.cue_clicked.connect(self.cue_clicked)
        self.canvas.pan_dragged.connect(lambda x, y: self.pan_dragged.emit(self._seg_idx, x, y))
        self.canvas.pan_finished.connect(self.pan_finished)
        self.canvas.image_clicked.connect(self.image_clicked)
        self.canvas.image_changed.connect(self.image_changed)
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
            self._audio.setMuted(self._muted)
            self.player.setAudioOutput(self._audio)
            self._sink = QVideoSink(self)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self.player.setVideoSink(self._sink)
            self.player.positionChanged.connect(self._on_player_position)
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.sourceChanged.connect(self._on_source_changed)
            self.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())
            self.player.playbackStateChanged.connect(lambda _s: self._sync_music())
            # the other clip of a transition plays on a second player, kept in
            # step with the playhead by _sync_transition()
            self.aux_player = QMediaPlayer(self)
            self._aux_audio = QAudioOutput(self)
            self._aux_audio.setMuted(self._muted)
            self.aux_player.setAudioOutput(self._aux_audio)
            self._aux_sink = QVideoSink(self)
            self._aux_sink.videoFrameChanged.connect(self._on_aux_frame)
            self.aux_player.setVideoSink(self._aux_sink)
            self.aux_player.mediaStatusChanged.connect(self._on_aux_status)
            self.aux_player.sourceChanged.connect(self._on_aux_source_changed)
            # each background song plays on its own player, kept in step with
            # the montage timeline by _sync_music()
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

    def set_music(self, beds: MusicBed | list[MusicBed] | None) -> None:
        if beds is None:
            beds = []
        elif isinstance(beds, MusicBed):
            beds = [beds]
        self._music = list(beds)
        if self.player is None:
            return
        while len(self._music_players) < len(self._music):
            player, out = QMediaPlayer(self), QAudioOutput(self)
            out.setMuted(self._muted)
            player.setAudioOutput(out)
            self._music_players.append((player, out, ""))
        for k, (player, out, source) in enumerate(self._music_players):
            path = self._music[k].path if k < len(self._music) else ""
            if path != source:
                player.stop()
                player.setSource(QUrl.fromLocalFile(path) if path else QUrl())
                self._music_players[k] = (player, out, path)
        self._sync_music(force=True)

    def music_bed(self) -> MusicBed | None:
        return self._music[0] if self._music else None

    def music_beds(self) -> list[MusicBed]:
        return list(self._music)

    @property
    def music_player(self) -> QMediaPlayer | None:
        """The first song's player (tests / scripts)."""
        return self._music_players[0][0] if self._music_players else None

    def set_muted(self, muted: bool) -> None:
        """Silence every player (tests and scripted recordings)."""
        self._muted = muted
        if self.player is not None:
            self._audio.setMuted(muted)
            self._aux_audio.setMuted(muted)
            for _player, out, _source in self._music_players:
                out.setMuted(muted)

    def _sync_music(self, force: bool = False) -> None:
        """Play / pause / re-seek each song to match the montage playhead."""
        if self.player is None:
            return
        t = self._pos
        playing = self.is_playing() or (self._want_play and bool(self._segments))
        for k, (mp, out, _source) in enumerate(self._music_players):
            bed = self._music[k] if k < len(self._music) else None
            pos = bed.position(t) if bed and t < self._duration else None
            if bed is not None:
                out.setVolume(min(1.0, max(0.0, bed.gain(t, self._duration))))
            if pos is None or not playing:
                if mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    mp.pause()
                if pos is not None and force:
                    mp.setPosition(int(pos * 1000))
                continue
            if force or abs(mp.position() / 1000 - pos) > 0.3:
                mp.setPosition(int(pos * 1000))
            if mp.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                mp.play()

    def set_images(self, images: list[tuple[int, ImageOverlay]], selected: int | None) -> None:
        """Every picture (row, overlay); the canvas shows those active now."""
        self._images, self._selected_image = images, selected
        self._refresh_overlay()

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
            for mp, _out, _source in self._music_players:
                mp.pause()
            self.aux_player.pause()
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
        self.canvas.set_images([(row, img) for row, img in self._images
                                if img.start <= t < img.end], self._selected_image)
        dip, badge = None, ""
        for mark in self._transitions:
            half = mark.duration / 2
            if half > 0 and abs(t - mark.at) < half:
                if mark.kind in ("fadeblack", "fadewhite"):
                    color = "#000000" if mark.kind == "fadeblack" else "#ffffff"
                    dip = (color, 1.0 - abs(t - mark.at) / half)
                elif mark.kind not in BLENDED:
                    badge = mark.label
                break
        self.canvas.set_transition_overlay(dip, badge)
        self._sync_transition()

    # transitions: the second player --------------------------------------

    def _active_mark(self, t: float) -> TransitionMark | None:
        for mark in self._transitions:
            if mark.kind in BLENDED and 1 <= mark.incoming < len(self._segments) \
                    and mark.progress(t) is not None:
                return mark
        return None

    def _sync_transition(self) -> None:
        """Inside a transition: show the other clip on the second player and
        blend; just before one: load it so the first frame is ready."""
        if self.player is None:
            return
        t = self._pos
        mark = self._active_mark(t)
        if mark is None:
            self.canvas.clear_blend()
            if self.aux_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.aux_player.pause()
            self._set_main_level(1.0)
            upcoming = next((m for m in self._transitions if m.kind in BLENDED
                             and 1 <= m.incoming < len(self._segments)
                             and 0 < (m.at - m.duration / 2) - t < 1.5), None)
            if upcoming is not None:  # preload the clip that is about to come in
                seg = self._segments[upcoming.incoming]
                self._aux_to(seg, seg.start - upcoming.duration / 2, play=False)
            return
        prog = mark.progress(t)
        out_seg, in_seg = self._segments[mark.incoming - 1], self._segments[mark.incoming]
        main_out = self._seg_idx == mark.incoming - 1
        other = in_seg if main_out else out_seg
        if not (out_seg.has_video and in_seg.has_video):
            self.canvas.clear_blend()
            return
        # the other clip at this moment of the montage (its tail or its head)
        self._aux_to(other, other.start + (t - other.offset), play=self.is_playing())
        if out_seg.path == in_seg.path:  # one file, two parts: tell them apart by player
            main_img = self._main_img
            aux_img = self._aux_img if self._aux_pending is None else None
            out_img, in_img = (main_img, aux_img) if main_out else (aux_img, main_img)
        else:
            out_img = self._last_frame.get(out_seg.path)
            in_img = self._last_frame.get(in_seg.path)
        self.canvas.set_blend(mark.kind, prog,
                              out_img, (out_seg.fit, out_seg.zoom, out_seg.pan_x, out_seg.pan_y),
                              in_img, (in_seg.fit, in_seg.zoom, in_seg.pan_x, in_seg.pan_y))
        # the sound crossfades too (acrossfade in the render)
        main_w = (1 - prog) if main_out else prog
        self._set_main_level(main_w)
        self._aux_audio.setVolume(min(1.0, max(0.0, other.volume * (1 - main_w))))

    def _set_main_level(self, weight: float) -> None:
        seg = self._segments[self._seg_idx] if 0 <= self._seg_idx < len(self._segments) else None
        if seg is not None:
            self._audio.setVolume(min(1.0, max(0.0, seg.volume * weight)))

    def _aux_to(self, seg: Segment, local: float, *, play: bool) -> None:
        aux = self.aux_player
        local = max(0.0, local)
        if self._aux_source != seg.path:
            self._aux_source, self._aux_img = seg.path, None
            self._aux_pending = local
            self._aux_awaiting = True
            aux.setSource(QUrl.fromLocalFile(seg.path))
            if play:
                aux.play()
            else:
                aux.pause()
            return
        if self._aux_pending is not None:
            self._aux_pending = local
            return
        drift = abs(aux.position() / 1000 - local)
        if drift > (0.25 if play else 0.04):
            aux.setPosition(int(local * 1000))
        playing = aux.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if play and not playing:
            aux.play()
        elif not play and playing:
            aux.pause()

    def _on_aux_status(self, status) -> None:
        loaded = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        if status in loaded and self._aux_pending is not None and not self._aux_awaiting:
            target, self._aux_pending = self._aux_pending, None
            self.aux_player.setPosition(int(target * 1000))

    def _on_aux_source_changed(self, _url) -> None:
        self._aux_awaiting = False
        self._on_aux_status(self.aux_player.mediaStatus())

    def _on_aux_frame(self, frame) -> None:
        if self._aux_pending is not None or self._aux_awaiting:
            return
        img = frame.toImage()
        if img.isNull():
            return
        self._aux_img = img
        self._last_frame[self._aux_source] = img
        if self.canvas._blend is not None:
            self._sync_transition()

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
        if self._pending_seek is not None or self._awaiting_source:
            return  # a new file's first frame, before the jump: keep the last picture
        img = frame.toImage()
        if not img.isNull():
            self._main_img = img
            self._last_frame[self._source] = img
            self.canvas.set_frame(img)
            if self.canvas._blend is not None:
                self._sync_transition()

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
