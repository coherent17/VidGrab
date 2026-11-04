"""The video canvas: frame, subtitles, pictures and guides painted by hand."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
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
    QSizePolicy,
    QWidget,
)

from vidgrab.media.studio import (
    ANIM_IN,
    HIGHLIGHT,
    SUBTITLE_FONT_NAME,
    SUBTITLE_MARGIN,
    ImageOverlay,
    SubtitleCue,
    SubtitleStyle,
    active_word,
    box_padding,
    char_end_times,
    color_hex,
    cue_style,
    source_index,
    subtitle_scale,
    typewriter_time,
    word_spans,
    wrap_cue_text,
)

# transitions the canvas draws from two frames (the rest are dips or cuts)
BLENDED = ("fade", "dissolve", "wipeleft", "slideleft", "circleopen", "zoomin")


def frame_geometry(fw: float, fh: float, rect: QRectF, fit: str, zoom: float,
                   pan_x: float, pan_y: float,
                   focus: tuple[float, float] | None = None) -> tuple[QRectF, QRectF]:
    """(source rect inside the frame, target rect on the canvas) — the same
    scale / crop / pad steps `studio._frame_filter` gives ffmpeg."""
    cover = fit == "fill"
    scale = (max if cover else min)(rect.width() / fw, rect.height() / fh) * max(zoom, 1.0)
    sw, sh = fw * scale, fh * scale
    cw, ch = min(sw, rect.width()), min(sh, rect.height())
    if focus is not None:  # auto-reframe: centre the window on the face (as the render does)
        pan_x = min(max((focus[0] * sw - cw / 2) / (sw - cw), 0.0), 1.0) if sw > cw else pan_x
        pan_y = min(max((focus[1] * sh - ch / 2) / (sh - ch), 0.0), 1.0) if sh > ch else pan_y
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


def _runs(idx: list[int]) -> list[tuple[int, int]]:
    """[2, 3, 4, 7] -> [(2, 5), (7, 8)]: the stretches of consecutive numbers."""
    out: list[tuple[int, int]] = []
    for i in sorted(idx):
        if out and out[-1][1] == i:
            out[-1] = (out[-1][0], i + 1)
        else:
            out.append((i, i + 1))
    return out


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
        self._zoom_now: float | None = None
        self._focus: tuple[float, float] | None = None  # auto-reframe: where the face is now
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
        self._guides = False  # always show the safe area + centre cross
        # lines a dragged item has snapped to: ("x" | "y", fraction of the frame)
        self._snapped: list[tuple[str, float]] = []
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

    SAFE = 0.05  # title-safe margin, a fraction of the frame on each side
    SNAP_PX = 8

    def set_guides(self, on: bool) -> None:
        self._guides = on
        self.update()

    def _snap_axis(self, value: float, size: float, extent: float, targets: list[float],
                   axis: str, free: bool) -> float:
        """Snap a centre *value* (fraction) whose item is *size* (fraction) wide:
        its centre to the middle, its edges to the safe margins."""
        if free:
            return value
        tol = self.SNAP_PX / max(1.0, extent)
        best = None
        for target in targets:
            for edge in (0.0, -size / 2, size / 2):  # centre, then the item's edges
                if edge and target == 0.5:
                    continue
                d = target - (value + edge)
                if abs(d) <= tol and (best is None or abs(d) < abs(best[0])):
                    best = (d, target)
        if best is None:
            return value
        self._snapped.append((axis, best[1]))
        return value + best[0]

    def _paint_guides(self, p: QPainter, rect: QRectF) -> None:
        accent = QColor(self._colors["accent"])
        p.save()
        if self._guides:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            m = self.SAFE
            p.drawRect(QRectF(rect.x() + rect.width() * m, rect.y() + rect.height() * m,
                              rect.width() * (1 - 2 * m), rect.height() * (1 - 2 * m)))
            p.drawLine(QPointF(rect.center().x(), rect.top()), QPointF(rect.center().x(), rect.bottom()))
            p.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        p.setPen(QPen(accent, 1.5))
        for axis, f in self._snapped:
            if axis == "x":
                x = rect.x() + f * rect.width()
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            else:
                y = rect.y() + f * rect.height()
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        p.restore()

    def picture(self, path: str) -> QImage:
        img = self._pictures.get(path)
        if img is None:
            img = QImage(path)
            self._pictures[path] = img
        return img

    def _image_box(self, img: ImageOverlay, rect: QRectF) -> QRectF:
        w = rect.width() * img.width
        if not img.is_picture():  # a blur / pixel box has its own height
            h = rect.height() * img.height
        else:
            pic = self.picture(img.path)
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
                img = replace(img, x=x, y=y, width=w, rotation=rot,
                              height=img.height * w / max(img.width, 1e-6))
            pic = self.picture(img.path) if img.is_picture() else QImage()
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
            elif not img.is_picture():  # a marker for what gets hidden: frosted, hatched, labelled
                self._paint_cover(p, local, img)
            p.setOpacity(1.0)
            grip = QRectF(local.right() - 7, local.bottom() - 7, 14, 14)
            knob = QRectF(-7, local.top() - 30, 14, 14)
            if not img.is_picture():
                knob = QRectF(-1e6, -1e6, 0, 0)  # a box does not turn
            if row == self._selected_image:
                p.setPen(QPen(QColor(self._colors["accent"]), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(local)
                if img.is_picture():
                    p.drawLine(QPointF(0, local.top()), QPointF(0, knob.bottom()))
                p.setPen(QPen(QColor("#ffffff"), 1.2))
                p.setBrush(QColor(self._colors["accent"]))
                p.drawRect(grip)
                if img.is_picture():
                    p.drawEllipse(knob)
            p.restore()
            self._img_hits.append((row, box, img.rotation, grip, knob))
        p.restore()

    def _paint_cover(self, p: QPainter, local: QRectF, img: ImageOverlay) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRect(local)
        p.setBrush(QBrush(QColor(255, 255, 255, 90), Qt.BDiagPattern))
        p.drawRect(local)
        p.setPen(QColor(255, 255, 255, 220))
        font = p.font()
        font.setPixelSize(max(10, min(int(local.height() * 0.3), 18)))
        font.setBold(True)
        p.setFont(font)
        p.drawText(local, Qt.AlignCenter, "blur" if img.kind == "blur" else "pixels")

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

    def set_focus(self, focus: tuple[float, float] | None, zoom: float | None = None) -> None:
        """*focus*: where the crop is aimed (face path / keyframes); *zoom*: the keyframes'
        zoom at this moment (None = the clip's own)."""
        if focus != self._focus or zoom != self._zoom_now:
            self._focus, self._zoom_now = focus, zoom
            self.update()

    def _framing_now(self) -> tuple:
        """The framing to draw: the clip's, or fill-frame at the keyframed zoom."""
        if self._zoom_now is None:
            return self._framing
        return ("fill", self._zoom_now, self._framing[2], self._framing[3])

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

    def _font(self, rect: QRectF, style: SubtitleStyle | None = None) -> QFont:
        # libass treats Fontsize as the font's full line height (ascent +
        # descent), Qt's pixel size as its em height. CJK fonts are ~1.45 em
        # tall, so convert or the preview draws text far larger than the render.
        style = style or self._style
        target = style.size * subtitle_scale(int(rect.width()), int(rect.height()))
        f = QFont(style.font or SUBTITLE_FONT_NAME)
        f.setBold(style.bold)
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
            margin = SUBTITLE_MARGIN * subtitle_scale(int(rect.width()), int(rect.height()))
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
                                                *self._framing_now(), focus=self._focus)
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
        if self._guides or self._snapped:
            self._paint_guides(p, rect)
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
        """Each line in its own look, with its entrance animation — the same
        rules the ASS file gives libass (studio.format_ass)."""
        k = subtitle_scale(int(rect.width()), int(rect.height()))
        p.save()
        p.setClipRect(rect)
        fade = max(0.0, self._style.fade)
        for row, cue in self._cues:
            dragging = self._drag is not None and self._drag[0] == row and self._drag_pos
            if dragging:
                cue = SubtitleCue(cue.start, cue.end, cue.text, *self._drag_pos, anchor=5,
                                  look=cue.look, animation=cue.animation)
            style = cue_style(cue, self._style)
            font = self._font(rect, style)
            fm = QFontMetricsF(font)
            fill = QColor(color_hex(style.color))
            bg = None
            if style.background:
                bg = QColor(color_hex(style.background, "#000000"))
                bg.setAlphaF(min(max(style.bg_opacity, 0.0), 1.0))
                outline = 0.0
            else:
                outline = max(1.0, 2 * k) if style.outline else 0.0
            pad = box_padding(style.size * k)
            lines = wrap_cue_text(cue.text, style.size * k, rect.width() - 2 * SUBTITLE_MARGIN * k)
            line_h = fm.height()
            text_h = line_h * len(lines)
            text_w = max(fm.horizontalAdvance(line) for line in lines)
            box, align = self._cue_box(cue, rect, text_w, text_h)
            hit_box = QRectF(box)
            el = self._time - cue.start  # seconds since the line came on
            anim = "none" if self._drag is not None else cue.animation
            opacity = 1.0
            if fade > 0 and self._drag is None:
                f = min(fade, (cue.end - cue.start) / 2) or 1.0
                opacity = min(1.0, max(0.0, min(self._time - cue.start, cue.end - self._time) / f))
            p.save()
            if anim == "pop":  # grows from 40 % around its anchor point
                grow = min(1.0, max(0.0, el / ANIM_IN["pop"]))
                scale = 0.4 + 0.6 * grow
                anchor = cue.anchor if cue.x is not None and 1 <= cue.anchor <= 9 else \
                    (8 if self._style.position == "top" else 2)
                col, rrow = (anchor - 1) % 3, (anchor - 1) // 3
                ox = (box.left(), box.center().x(), box.right())[col]
                oy = (box.bottom(), box.center().y(), box.top())[rrow]
                p.translate(ox, oy)
                p.scale(scale, scale)
                p.translate(-ox, -oy)
            elif anim == "slide":  # rises 5 % of the frame into place
                rise = rect.height() * 0.05 * (1 - min(1.0, max(0.0, el / ANIM_IN["slide"])))
                box.translate(0, rise)
                if fade <= 0:
                    opacity *= min(1.0, max(0.0, el / (ANIM_IN["slide"] * 0.7)))
            # typewriter: how many characters are out; karaoke: how many are sung
            chars = sum(len(line) for line in lines)
            shown = chars
            sung = None
            if anim == "typewriter":
                step = typewriter_time(cue.end - cue.start) / max(1, chars)
                shown = min(chars, int(max(0.0, el) / step) + 1) if el >= 0 else 0
            spans = word_spans(cue)
            src = source_index(cue.text, lines) if spans else []
            timed = bool(spans) and len(src) == chars
            hot_runs: set[int] = set()  # characters of the word being said (highlight)
            if anim == "highlight" and timed:
                k = active_word(spans, el)
                hot_runs = {n for n, i in enumerate(src) if k is not None and spans[k][0] <= i < spans[k][1]}
            elif anim in ("karaoke", "highlight"):
                if timed:  # as many characters as have been said by now
                    sung = sum(1 for e in char_end_times(src, spans) if e <= el)
                else:
                    sweep = max(0.01, (cue.end - cue.start) * 0.9)
                    sung = int(chars * min(1.0, max(0.0, el / sweep)))
                unsung = QColor("#AAAAAA") if fill.name().upper() == "#FFFFFF" else QColor("#FFFFFF")
            p.setOpacity(opacity)
            path, sung_path, hot_path = QPainterPath(), QPainterPath(), QPainterPath()
            used = 0
            for i, line in enumerate(lines):
                lw = fm.horizontalAdvance(line)
                lx = box.left() + (0.0, (text_w - lw) / 2, text_w - lw)[align + 1]
                top = box.top() + i * line_h
                visible = line[:max(0, shown - used)]
                if visible and bg is not None:  # one box per line, like libass
                    vw = fm.horizontalAdvance(visible)
                    p.fillRect(QRectF(lx - pad, top - pad / 2, vw + 2 * pad, line_h + pad), bg)
                if visible:
                    if sung is None:
                        path.addText(QPointF(lx, top + fm.ascent()), font, visible)
                        for run in _runs([n - used for n in hot_runs if used <= n < used + len(visible)]):
                            hot_path.addText(
                                QPointF(lx + fm.horizontalAdvance(visible[:run[0]]), top + fm.ascent()),
                                font, visible[run[0]:run[1]])
                    else:  # sung part in the line's colour, the rest light
                        n = max(0, min(len(visible), sung - used))
                        sung_path.addText(QPointF(lx, top + fm.ascent()), font, visible[:n])
                        path.addText(QPointF(lx + fm.horizontalAdvance(visible[:n]),
                                             top + fm.ascent()), font, visible[n:])
                used += len(line)
            if outline:
                pen = QPen(QColor("#000000"), outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                p.strokePath(path, pen)
                p.strokePath(sung_path, pen)
            p.fillPath(path, unsung if sung is not None else fill)
            p.fillPath(sung_path, fill)
            p.fillPath(hot_path, QColor("#FFFFFF" if fill.name().upper() == HIGHLIGHT else HIGHLIGHT))
            p.restore()
            hit = hit_box.adjusted(-8, -6, 8, 6)
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
                img = next(i for r, i in self._images if r == row)
                box = self._image_box(img, rect)
                free = bool(event.modifiers() & Qt.AltModifier) or r0 % 90 != 0
                self._snapped = []
                targets = [self.SAFE, 0.5, 1 - self.SAFE]
                x = self._snap_axis(x, box.width() / rect.width(), rect.width(), targets, "x", free)
                y = self._snap_axis(y, box.height() / rect.height(), rect.height(), targets, "y",
                                    free)
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
        # snap the line's centre to the middle, its edges to the safe margins
        hit = next((r for row, r in self._hits if row == self._drag[0]), None)
        w = (hit.width() - 16) / rect.width() if hit is not None else 0.0
        h = (hit.height() - 12) / rect.height() if hit is not None else 0.0
        free = bool(event.modifiers() & Qt.AltModifier)
        self._snapped = []
        targets = [self.SAFE, 0.5, 1 - self.SAFE]
        x = self._snap_axis(x, w, rect.width(), targets, "x", free)
        y = self._snap_axis(y, h, rect.height(), targets, "y", free)
        self._drag_pos = (x, y)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._snapped = []
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
