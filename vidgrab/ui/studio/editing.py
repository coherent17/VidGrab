"""Adding, moving, selecting, copying and cutting clips."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QMenu,
)

from vidgrab.ai import beats
from vidgrab.media.studio import (
    IMAGE_EXTS,
)
from vidgrab.ui.preview import (
    fmt_time,
)
from vidgrab.ui.silence_dialog import SilenceDialog
from vidgrab.ui.studio.clips import _MediaClip, _Song
from vidgrab.ui.studio.common import BEST_LENGTHS, MIN_CLIP, PROJECT_EXT
from vidgrab.ui.studio.tasks import _BeatTask, _BestTask


class EditingMixin:
    """Adding, moving, selecting, copying and cutting clips."""

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

    def remove_silences(self) -> None:
        """Ask how quiet counts as a pause, then split the selected clip into
        the parts that stay (each keeps the clip's speed, framing and effects)."""
        if not self._sel or self._sel[0] != "clip" or self._busy or not self.host.ffmpeg_ok():
            return
        i = self._sel[1]
        clip = self._clips[i]
        s, e = clip.span()
        dlg = SilenceDialog(self, self.t, clip.path, s, e)
        self._silence_dlg = dlg  # for tests
        if dlg.exec() != QDialog.Accepted:
            return
        self.cut_ranges(i, dlg.ranges())

    def _best_menu(self) -> None:
        """Pick a length, then keep that much of the selected clip: the liveliest part."""
        if not self._sel or self._sel[0] != "clip" or self._busy or not self.host.ffmpeg_ok():
            return
        menu = QMenu(self)
        for secs in BEST_LENGTHS:
            menu.addAction(self.t("Best {n} seconds", n=secs), lambda n=secs: self.find_best_moment(n))
        self._best_menu_obj = menu  # for tests
        menu.exec(self.best_btn.mapToGlobal(self.best_btn.rect().bottomLeft()))

    def find_best_moment(self, length: float) -> None:
        if not self._sel or self._sel[0] != "clip":
            return
        i = self._sel[1]
        s, e = self._clips[i].span()
        if e - s <= length + 1:
            self.status.setText(self.t("This clip is already that short."))
            return
        self.best_btn.setEnabled(False)
        self.status.setText(self.t("Listening for the best moment…"))
        self._best_pool.start(_BestTask(self._best_relay, i, self._clips[i].path, s, e, length))

    def _best_done(self, i: int, start: float, end: float, err: str) -> None:
        self.best_btn.setEnabled(True)
        if err:
            self.status.setText(self.t("Could not analyse the sound: {err}", err=err))
            return
        if i >= len(self._clips):
            return
        self._sel = ("clip", i)
        self._on_clip_trimmed(i, start, end)
        self.select_clip(i)
        self.status.setText(self.t("Kept the best {n} seconds ({a} – {b}).", n=round(end - start),
                                   a=fmt_time(start), b=fmt_time(end)))

    def _beat_song(self) -> _Song | None:
        if self._sel and self._sel[0] == "music" and 0 <= self._sel[1] < len(self._songs):
            return self._songs[self._sel[1]]
        return self._songs[0] if self._songs else None

    def cut_to_beat(self) -> None:
        song = self._beat_song()
        if song is None or len(self._clips) < 2 or not self.is_video():
            self.status.setText(self.t("Add at least two clips and a song first."))
            return
        if any(c.transition != "none" for c in self._clips[1:]):
            self.status.setText(self.t("Cut to the beat works with plain cuts: set the transitions to None first."))
            return
        if not beats.available():
            self.status.setText(self.t("Beat finding needs the speech add-on (numpy), which this "
                                       "installation doesn't have."))
            return
        self.beat_btn.setEnabled(False)
        self.status.setText(self.t("Listening for the beat…"))
        start, end = song.span()
        self._beat_pool.start(_BeatTask(self._beat_relay, song.path, start, end, song.offset))

    def _beat_done(self, bpm: float, times: list, err: str) -> None:
        self.beat_btn.setEnabled(True)
        if err or not times:
            self.status.setText(self.t("Could not find a clear beat in this song.") if not err
                                else self.t("Could not analyse the sound: {err}", err=err))
            return
        before = [c.kept() for c in self._clips]
        after = beats.snap_durations(before, [t for t in times if t >= 0])
        changed = 0
        for clip, new in zip(self._clips, after, strict=True):
            start = clip.span()[0]
            new_end = round(start + new * clip.speed, 3)
            if clip.length:
                new_end = min(new_end, clip.length)
            if abs(new_end - clip.span()[1]) > 0.01:
                clip.end = new_end
                changed += 1
        if not changed:
            self.status.setText(self.t("The cuts already sit on the beat ({bpm} BPM).", bpm=round(bpm)))
            return
        self._project_changed()
        self._record("beat")
        self.status.setText(self.t("Cut {n} clips to the beat ({bpm} BPM).", n=changed, bpm=round(bpm)))

    def cut_ranges(self, i: int, keeps: list[tuple[float, float]]) -> None:
        """Replace clip *i* by one clip per kept (start, end); only the first
        keeps the transition in."""
        if len(keeps) < 1 or (len(keeps) == 1 and keeps[0] == self._clips[i].span()):
            return
        clip = self._clips[i]
        pieces = [replace(clip, start=a, end=b, transition="none" if n else clip.transition)
                  for n, (a, b) in enumerate(keeps)]
        self._clips[i:i + 1] = pieces
        self._sel = ("clip", i)
        self._picked = {self._sel}
        self._project_changed()
        self.select_clip(i)  # also refreshes the Trim fields to the first part
        self._record()
        self.status.setText(self.t("Cut into {n} parts.", n=len(pieces)))

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
