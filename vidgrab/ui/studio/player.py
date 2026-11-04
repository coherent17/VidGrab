"""The preview player: chained segments, transitions and the music beds."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QCursor,
    QImage,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.media import effects, fx_preview
from vidgrab.media.studio import (
    ImageOverlay,
    SubtitleCue,
    SubtitleStyle,
)
from vidgrab.ui.studio.canvas import BLENDED, VideoCanvas, fmt_time, transport_icon

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
    speed: float = 1.0  # the source plays this many times as fast
    fx: dict = field(default_factory=dict)  # picture effects (see effects.py); the colour ones show here
    key_bg: str = ""  # picture behind a green screen

    def source_at(self, t: float) -> float:
        """Source time shown at montage time *t*."""
        return self.start + (t - self.offset) * self.speed

    def montage_at(self, local: float) -> float:
        """Montage time of source time *local*."""
        return self.offset + (local - self.start) / self.speed

    def source_end(self) -> float:
        return self.start + self.duration * self.speed


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
        self._raw_main: QImage | None = None  # ... before the colour effects
        self._raw_seg = -1  # which segment it belongs to
        self._aux_fx: tuple[dict, str] = ({}, "")
        self._bg_cache: tuple[tuple, QImage] | None = None
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
        self.guides_btn = QPushButton()
        self.guides_btn.setObjectName("secondary")
        self.guides_btn.setCheckable(True)
        self.guides_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.guides_btn.toggled.connect(self.canvas.set_guides)
        row.addWidget(self.guides_btn)
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

    def set_texts(self, *, empty: str, audio: str, guides: str = "Guides",
                  guides_tip: str = "", play_tip: str = "") -> None:
        self._texts = {"empty": empty, "audio": audio}
        self.play_btn.setToolTip(play_tip)
        self.guides_btn.setText(guides)
        self.guides_btn.setToolTip(guides_tip)
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
        self._show_segment(idx, seg.source_at(seconds), play=self.is_playing())

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
            if self.player.playbackRate() != seg.speed:
                self.player.setPlaybackRate(seg.speed)
        self._set_pos(seg.montage_at(local))
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
                self._aux_to(seg, seg.start - upcoming.duration / 2 * seg.speed, play=False)
            return
        prog = mark.progress(t)
        out_seg, in_seg = self._segments[mark.incoming - 1], self._segments[mark.incoming]
        main_out = self._seg_idx == mark.incoming - 1
        other = in_seg if main_out else out_seg
        if not (out_seg.has_video and in_seg.has_video):
            self.canvas.clear_blend()
            return
        # the other clip at this moment of the montage (its tail or its head)
        self._aux_to(other, other.source_at(t), play=self.is_playing())
        if self.aux_player.playbackRate() != other.speed:
            self.aux_player.setPlaybackRate(other.speed)
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
        self._aux_fx = (seg.fx, seg.key_bg)
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

    # picture effects ------------------------------------------------------

    FX_MAX_W = 800  # frames are shrunk to this before the colour maths (the canvas is small)

    def _fx_image(self, img: QImage, fx: dict, key_bg: str) -> QImage:
        """*img* with the colour looks / sliders / green screen applied (as far as
        `fx_preview` can); the frame itself when there is nothing to show."""
        if not fx or not fx_preview.available() or not fx_preview.can_show(fx):
            return img
        if img.width() > self.FX_MAX_W:
            img = img.scaledToWidth(self.FX_MAX_W, Qt.FastTransformation)
        img = img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = img.width(), img.height()
        np = fx_preview.np
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, : w * 3]
        back = self._background(key_bg, w, h) if fx.get("key") and key_bg else None
        out = np.ascontiguousarray(fx_preview.apply(arr.reshape(h, w, 3), fx, back))
        return QImage(out.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()

    def _background(self, path: str, w: int, h: int):
        """The picture behind a green screen, scaled to cover w x h (an array)."""
        key = (path, w, h)
        if self._bg_cache is None or self._bg_cache[0] != key:
            pic = QImage(path)
            if pic.isNull():
                return None
            pic = pic.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            pic = pic.copy((pic.width() - w) // 2, (pic.height() - h) // 2, w, h)
            self._bg_cache = (key, pic.convertToFormat(QImage.Format.Format_RGB888))
        pic = self._bg_cache[1]
        np = fx_preview.np
        return np.frombuffer(pic.constBits(), np.uint8).reshape(h, pic.bytesPerLine())[:, : w * 3] \
            .reshape(h, w, 3)

    def _follow(self, seg: Segment | None) -> None:
        """Auto-reframe: aim the crop at the face where the showing frame is."""
        keys = seg.fx.get("follow") if seg is not None else None
        zoomkeys = seg.fx.get("keys") if seg is not None else None
        now = self.player.position() / 1000
        at = effects.keys_at(zoomkeys, now) if zoomkeys else None
        focus = effects.focus_at(keys, now) if keys else (at[:2] if at else None)
        self.canvas.set_focus(focus, at[2] if at else None)

    def refresh_effects(self, segments: list[Segment]) -> None:
        """The effects of the clips changed (a slider moved): take them over and
        redraw the frame that is showing, without reloading anything."""
        for old, new in zip(self._segments, segments, strict=False):
            if old.path == new.path:
                old.fx, old.key_bg = new.fx, new.key_bg
        seg = self._segments[self._seg_idx] if 0 <= self._seg_idx < len(self._segments) else None
        self._follow(seg)
        if (seg is not None and self._raw_main is not None and seg.has_video
                and self._raw_seg == self._seg_idx):
            img = self._fx_image(self._raw_main, seg.fx, seg.key_bg)
            self._main_img = img
            self._last_frame[self._source] = img
            self.canvas.set_frame(img)

    def _on_aux_frame(self, frame) -> None:
        if self._aux_pending is not None or self._aux_awaiting:
            return
        img = frame.toImage()
        if img.isNull():
            return
        img = self._fx_image(img, *self._aux_fx)
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
            self._follow(seg)
            self._raw_main, self._raw_seg = img, self._seg_idx
            img = self._fx_image(img, seg.fx, seg.key_bg)
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
                self._set_pos(max(seg.offset, seg.montage_at(local)))
                return
            else:
                # still somewhere else: the seek was dropped, ask again now and
                # then (not on every report, which would stall playback)
                self._seek_misses += 1
                if self._seek_misses % 3 == 0:
                    self.player.setPosition(int(self._seek_target * 1000))
                return
        if local >= seg.source_end():
            if self.is_playing():
                self._advance()
            return
        self._set_pos(max(seg.offset, seg.montage_at(local)))

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
