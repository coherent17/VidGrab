"""Captions, combining videos and the render."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QImage,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab.ai import cuda_runtime
from vidgrab.ai.captions import DEFAULT_MODEL as DEFAULT_CAPTION_MODEL
from vidgrab.ai.captions import LANGUAGES as CAPTION_LANGUAGES
from vidgrab.ai.captions import MODELS as CAPTION_MODELS
from vidgrab.ai.captions import (
    CaptionSource,
    detect_gpus,
    model_info,
    model_ready,
    speech_engines,
)
from vidgrab.ai.captions import (
    installed as captions_installed,
)
from vidgrab.media import effects
from vidgrab.media.studio import (
    ANIMATIONS,
    BackgroundMusic,
    Clip,
    SubtitleCue,
    thumbnail_png,
)
from vidgrab.ui.split_dialog import SplitDialog
from vidgrab.ui.studio.common import _HAND, EXPORT_PRESETS


class RenderMixin:
    """Captions, combining videos and the render."""

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
            lang.addItem(name or t("Translate to English" if code == "translate" else "Detect automatically"), code)
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
        lay.addSpacing(4)
        cap = QLabel(t("CAPTION STYLE"))
        cap.setObjectName("field_cap")
        lay.addWidget(cap)
        style_box = QComboBox()
        for anim, label in (("highlight", "Word highlight"), ("karaoke", "Karaoke"), ("none", "Plain")):
            style_box.addItem(t(label), anim)
        style_box.setCurrentIndex(max(0, style_box.findData(setting("caption_style") or "highlight")))
        lay.addWidget(style_box)
        style_hint = QLabel(t("Word highlight lights up each word as it is said. You can change "
                              "it per line later (Effects tab)."))
        style_hint.setObjectName("hint")
        style_hint.setWordWrap(True)
        lay.addWidget(style_hint)
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
        self._caption_anim = style_box.currentData() or "none"
        if hasattr(self.host, "set_setting"):
            self.host.set_setting("caption_style", self._caption_anim)
        return lang.currentData(), size, replace_box.isChecked()

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
        anim = getattr(self, "_caption_anim", "none")
        for cue in cues:
            if cue.animation == "none" and anim in ANIMATIONS:
                cue.animation = anim  # the style chosen in the Auto captions dialog
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
                      volume=c.volume, muted=c.muted, speed=c.speed, denoise=c.denoise,
                      fx=effects.sanitize(c.fx))
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
                duck=self.music_duck.isChecked(),
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
                "models_dir": self.host.models_dir() if hasattr(self.host, "models_dir") else None,
            })
        else:
            ext = self.afmt.currentData() or ".mp3"
            self.render_requested.emit("compose_audio", {
                "clips": clips,
                "output_file": folder / f"{name}{ext}",
                "crossfade": self.xfade.value(),
                "bitrate": self.abr.currentData(),
            })
