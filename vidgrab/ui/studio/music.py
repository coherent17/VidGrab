"""Background music: the inspector and its songs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QFontMetricsF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QSlider,
    QWidget,
)

from vidgrab.media.studio import (
    parse_timecode,
    probe_media,
    waveform,
)
from vidgrab.ui.preview import (
    MusicBed,
)
from vidgrab.ui.studio.clips import _fmt_precise, _Song
from vidgrab.ui.studio.common import _HAND, MIN_MUSIC


class MusicMixin:
    """Background music: the inspector and its songs."""

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

        lay.addWidget(self._label("CUT TO THE BEAT", "field_cap"))
        self.beat_btn = self._btn("Cut clips to the beat", self.cut_to_beat,
                                  "Moves each cut a little so it lands on this song's beat")
        lay.addWidget(self.beat_btn)
        lay.addWidget(self._label(
            "Listens to the song and trims the clips so every cut lands on a beat. "
            "Works with plain cuts (no transitions).", "hint"))
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
        self.music_duck = QCheckBox()
        self.music_duck.toggled.connect(lambda _c: self._record())
        self._tr(self.music_duck, "Lower the music while someone is speaking")
        self._tr(self.music_duck, "The clips' own sound steers the music: it is pressed down while "
                 "there is speech and comes back up in the pauses. Applied when you render; the "
                 "preview does not play it.", "setToolTip")
        lay.addWidget(self.music_loop)
        lay.addWidget(self.music_fade)
        lay.addWidget(self.music_duck)
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
