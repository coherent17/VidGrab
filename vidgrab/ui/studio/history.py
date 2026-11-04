"""Undo / redo and the project file."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, astuple
from pathlib import Path

from PySide6.QtGui import (
    QImage,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QMessageBox,
)

from vidgrab.media import effects
from vidgrab.media.studio import (
    COVER_KINDS,
    SPEED_RANGE,
    TRANSITIONS,
    ImageOverlay,
    SubtitleCue,
    probe_media,
    thumbnail_png,
    waveform,
)
from vidgrab.ui.studio.clips import _brightness, _MediaClip, _Song
from vidgrab.ui.studio.common import (
    COALESCE_S,
    EXPORT_PRESETS,
    FILMSTRIP,
    HISTORY_LIMIT,
    PROJECT_EXT,
    PROJECT_VERSION,
)


class HistoryMixin:
    """Undo / redo and the project file."""

    def _state(self) -> dict:
        """Everything undo and project files cover, as plain comparable data."""
        return {
            "clips": [(c.path, c.edit()) for c in self._clips],
            "cues": [astuple(c) for c in self._cues],
            "images": [astuple(img) for img in self._images],
            "music": [song.edit() for song in self._songs],
            "music_opts": (self.orig_vol.value(), self.music_loop.isChecked(),
                           self.music_fade.isChecked(), self.music_duck.isChecked()),
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
            orig, loop, fade, *more = state["music_opts"]
            self.orig_vol.setValue(orig)
            self.music_loop.setChecked(loop)
            self.music_fade.setChecked(fade)
            self.music_duck.setChecked(bool(more[0]) if more else False)
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
        m.addSeparator()
        subs = m.addMenu(self.t("Subtitles"))
        subs.addAction(self.t("Import subtitles…"), self.import_subtitles)
        subs.addAction(self.t("Export subtitles…"), self.export_subtitles).setEnabled(
            bool(self.cues()))
        subs.addAction(self.t("Copy the transcript"), self.copy_transcript).setEnabled(
            bool(self.cues()))

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
                       "denoise": c.denoise, "fx": effects.sanitize(c.fx)}
                      for c in self._clips],
            "subtitles": [asdict(c) for c in self._cues],
            "images": [{**(ref(img.path) if img.is_picture() else {"path": ""}),
                        **{k: v for k, v in asdict(img).items() if k != "path"}}
                       for img in self._images],
            "music": music,
            "music_options": {"original_volume": self.orig_vol.value(),
                              "loop_last": self.music_loop.isChecked(),
                              "fade_out": self.music_fade.isChecked(),
                              "duck": self.music_duck.isChecked()},
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
                    bool(ref.get("denoise", False)),
                    effects.edit_tuple(ref.get("fx")))))
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
                      bool(opts.get("fade_out", True)), bool(opts.get("duck", False)))
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
            found = find(m) if isinstance(m, dict) and m.get("kind", "image") == "image" else ""
            if isinstance(m, dict) and m.get("kind") in COVER_KINDS:  # a box has no file to find
                images.append(astuple(ImageOverlay("", **{k: v for k, v in m.items() if k in img_fields})))
            elif found:
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
