"""The painted timeline."""
from __future__ import annotations

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QSizePolicy,
    QWidget,
)

from vidgrab.ui.preview import (
    fmt_time,
)
from vidgrab.ui.studio.clips import _MediaClip, clip_overlaps
from vidgrab.ui.studio.common import _HAND, MIN_CLIP, MIN_MUSIC, THUMB_STEPS
from vidgrab.ui.studio.tasks import ThumbCache


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
