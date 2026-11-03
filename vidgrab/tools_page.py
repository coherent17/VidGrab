"""The Tools page: small one-shot jobs on a single file (shrink to a size,
convert, GIF, thumbnail, extract audio). The engine is `tools.py`."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab import reframe, shorts, studio, tools
from vidgrab.downloader import DownloadCancelled
from vidgrab.ui_kit import rgba

TOOLS = ["short", "compress", "convert", "gif", "thumbnail", "audio"]
_NAMES = {"short": "Make a Short", "compress": "Shrink to a size", "convert": "Convert", "gif": "Make a GIF",
          "thumbnail": "Thumbnail", "audio": "Extract audio"}
_BLURBS = {"short": "A vertical clip with captions", "compress": "Make a video fit a size limit", "convert": "Change the file format",
           "gif": "Turn a few seconds into a GIF", "thumbnail": "Pick a frame and add a title",
           "audio": "Save just the sound"}
_ICONS = {"short": "scissors", "compress": "download", "convert": "folder", "gif": "film", "thumbnail": "captions", "audio": "music"}
_FILTER = "Media (*.mp4 *.mkv *.webm *.mov *.avi *.mp3 *.m4a *.opus *.wav *.flac *.ogg *.aac *.gif)"
THUMB_W, THUMB_H = 1280, 720


class _Relay(QObject):
    progress = Signal(str, float)
    done = Signal(str, str)  # output path, error text


class _Task(QRunnable):
    def __init__(self, relay: _Relay, cmd: list[str], total: float, label: str,
                 cancel: threading.Event, tr) -> None:
        super().__init__()
        self._relay, self._cmd, self._total, self._label, self._cancel, self._tr = relay, cmd, total, label, cancel, tr

    def run(self) -> None:
        def progress(msg: str, pct: float | None) -> None:
            if self._cancel.is_set():
                raise DownloadCancelled("cancelled")
            if pct is not None:
                self._relay.progress.emit(msg, pct)

        try:
            out = tools.run_tool(self._cmd, self._total, label=self._label, on_progress=progress,
                                 translate=self._tr)
            self._relay.done.emit(str(out), "")
        except DownloadCancelled:
            self._relay.done.emit("", "cancelled")
        except Exception as exc:  # noqa: BLE001 - whatever ffmpeg / the disk did, show it
            self._relay.done.emit("", str(exc) or exc.__class__.__name__)


class _Job(QRunnable):
    """A Python job (not one ffmpeg command): fn(progress, cancelled) -> output file."""

    def __init__(self, relay: _Relay, fn, cancel: threading.Event) -> None:
        super().__init__()
        self._relay, self._fn, self._cancel = relay, fn, cancel

    def run(self) -> None:
        def progress(msg: str, pct: float | None) -> None:
            if self._cancel.is_set():
                raise DownloadCancelled("cancelled")
            if pct is not None:
                self._relay.progress.emit(msg, pct)

        try:
            self._relay.done.emit(str(self._fn(progress, self._cancel.is_set)), "")
        except DownloadCancelled:
            self._relay.done.emit("", "cancelled")
        except Exception as exc:  # noqa: BLE001 - whatever failed, show it
            self._relay.done.emit("", str(exc) or exc.__class__.__name__)


def _spin(lo: float, hi: float, value: float, suffix: str = "", step: float = 1.0, dec: int = 1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class ToolsPage(QWidget):
    """*host* gives t(), icon(), default_output_dir(), pick_file(), ffmpeg_ok(),
    log() and reveal()."""

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self._palette: dict[str, str] = {}
        self._tool = "short"
        self._src = ""
        self._duration = 0.0
        self._out = ""
        self._pool = QThreadPool(self)
        self._relay = _Relay(self)
        self._relay.progress.connect(self._progress)
        self._relay.done.connect(self._done)
        self._cancel = threading.Event()
        self._running = False
        self._shot = QTimer(self)
        self._shot.setSingleShot(True)
        self._shot.setInterval(350)
        self._shot.timeout.connect(self._update_thumb)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.tiles: dict[str, QPushButton] = {}
        for k in TOOLS:
            b = QPushButton()
            b.setObjectName("tool_tile")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedWidth(280)
            b.setMinimumHeight(66)
            b.clicked.connect(lambda _c=False, key=k: self.select_tool(key))
            left.addWidget(b)
            self.tiles[k] = b
        left.addStretch()
        lay.addLayout(left)

        card = QFrame()
        card.setObjectName("tool_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 22)
        cl.setSpacing(12)
        self.title = QLabel()
        self.blurb = QLabel()
        cl.addWidget(self.title)
        cl.addWidget(self.blurb)
        row = QHBoxLayout()
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.file.setMinimumHeight(36)
        self.browse = QPushButton()
        self.browse.setObjectName("secondary")
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.file, stretch=1)
        row.addWidget(self.browse)
        cl.addLayout(row)
        self.info = QLabel()
        cl.addWidget(self.info)
        self.opts = QStackedWidget()
        for k in TOOLS:
            self.opts.addWidget(self._options(k))
        cl.addWidget(self.opts, stretch=1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        cl.addWidget(self.bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        cl.addWidget(self.status)
        foot = QHBoxLayout()
        self.run_btn = QPushButton()
        self.run_btn.setObjectName("primary")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._start_stop)
        self.show_btn = QPushButton()
        self.show_btn.setObjectName("secondary")
        self.show_btn.clicked.connect(lambda: self._out and self.host.reveal(self._out))
        foot.addWidget(self.run_btn)
        foot.addWidget(self.show_btn)
        foot.addStretch()
        cl.addLayout(foot)
        lay.addWidget(card, stretch=1)
        self.retranslate()
        self.select_tool("short")

    # ── option panels ──────────────────────────────────────────────────

    def _options(self, key: str) -> QWidget:
        w = QWidget()
        g = QVBoxLayout(w)
        g.setContentsMargins(0, 4, 0, 0)
        g.setSpacing(10)
        if key == "compress":
            self.size_combo = QComboBox()
            for mb in tools.SIZE_PRESETS_MB:
                self.size_combo.addItem(f"{mb} MB", mb)
            self.size_combo.addItem("", 0)
            self.size_custom = _spin(0.5, 4000, 25, " MB", 1)
            self.size_combo.currentIndexChanged.connect(self._sync_size)
            self.size_lbl = QLabel()
            self.shrink_box = QComboBox()
            for _i in range(2):
                self.shrink_box.addItem("")
            self.shrink_box.setItemData(0, True)
            self.shrink_box.setItemData(1, False)
            self.size_combo.setCurrentIndex(1)
            for lbl, wd in ((self.size_lbl, self.size_combo), (None, self.size_custom)):
                if lbl:
                    g.addWidget(lbl)
                g.addWidget(wd)
            self.shrink_lbl = QLabel()
            g.addWidget(self.shrink_lbl)
            g.addWidget(self.shrink_box)
            self._sync_size()
        elif key == "short":
            self.short_len = QComboBox()
            for sec in shorts.LENGTHS:
                self.short_len.addItem(f"{sec} s", sec)
            self.short_len.setCurrentIndex(1)
            self.short_lbl = QLabel()
            self.short_follow = QCheckBox()
            self.short_follow.setChecked(reframe.available())
            self.short_follow.setEnabled(reframe.available())
            self.short_caps = QCheckBox()
            self.short_caps.setChecked(True)
            self.short_note = QLabel()
            self.short_note.setWordWrap(True)
            for wd in (self.short_lbl, self.short_len, self.short_follow, self.short_caps, self.short_note):
                g.addWidget(wd)
        elif key in ("convert", "audio"):
            combo = QComboBox()
            for f in (tools.CONVERT if key == "convert" else tools.AUDIO_TARGETS):
                combo.addItem(f.upper(), f)
            setattr(self, f"{key}_fmt", combo)
            lbl = QLabel()
            setattr(self, f"{key}_lbl", lbl)
            g.addWidget(lbl)
            g.addWidget(combo)
        elif key == "gif":
            self.gif_start = _spin(0, 99999, 0, " s", 0.5)
            self.gif_len = _spin(0.5, 30, 4, " s", 0.5)
            self.gif_width = QComboBox()
            for wpx in tools.GIF_WIDTHS:
                self.gif_width.addItem(f"{wpx} px", wpx)
            self.gif_width.setCurrentIndex(1)
            self.gif_lbls = [QLabel() for _ in range(3)]
            for lbl, wd in zip(self.gif_lbls, (self.gif_start, self.gif_len, self.gif_width), strict=True):
                g.addWidget(lbl)
                g.addWidget(wd)
        else:  # thumbnail
            self.th_time = _spin(0, 99999, 1, " s", 0.5)
            self.th_text = QLineEdit()
            self.th_time.valueChanged.connect(lambda _v: self._shot.start())
            self.th_text.textChanged.connect(lambda _v: self._shot.start())
            self.th_lbls = [QLabel() for _ in range(2)]
            self.th_prev = QLabel()
            self.th_prev.setAlignment(Qt.AlignCenter)
            self.th_prev.setMinimumHeight(206)
            for lbl, wd in zip(self.th_lbls, (self.th_time, self.th_text), strict=True):
                g.addWidget(lbl)
                g.addWidget(wd)
            g.addWidget(self.th_prev, stretch=1)
        g.addStretch()
        return w

    def _sync_size(self) -> None:
        custom = self.size_combo.currentData() == 0
        self.size_custom.setVisible(custom)

    def target_mb(self) -> float:
        return self.size_custom.value() if self.size_combo.currentData() == 0 else float(self.size_combo.currentData())

    # ── look / text ────────────────────────────────────────────────────

    def apply_theme(self, p: dict[str, str]) -> None:
        self._palette = p
        self.setStyleSheet(
            f"QFrame#tool_card {{ background:{p['SURFACE']}; border:1px solid {p['BORDER']}; border-radius:16px; }}"
            f"QPushButton#tool_tile {{ background:{p['SURFACE']}; color:{p['TEXT']}; border:1px solid {p['BORDER']};"
            " border-radius:14px; text-align:left; padding:10px 16px; font-size:14px; font-weight:700; }"
            f"QPushButton#tool_tile:hover {{ border-color:{p['ACCENT_HI']}; background:{p['SURFACE_HI']}; }}"
            f"QPushButton#tool_tile:checked {{ border:2px solid {p['ACCENT']}; background:{rgba(p['ACCENT'], .16)}; }}")
        self.title.setStyleSheet(f"font-size:22px; font-weight:800; color:{p['TEXT']};")
        self.blurb.setStyleSheet(f"font-size:13px; color:{p['TEXT_MUTED']};")
        self.info.setStyleSheet(f"font-size:12px; color:{p['TEXT_MUTED']};")
        self.status.setStyleSheet(f"font-size:13px; color:{p['TEXT_DIM']};")
        for k, b in self.tiles.items():
            b.setIcon(self.host.icon(_ICONS[k], p["ACCENT_HI"], 26))
            b.setIconSize(b.iconSize().expandedTo(b.iconSize()))
        self._update_thumb()

    def retranslate(self) -> None:
        t = self.host.t
        for k, b in self.tiles.items():
            b.setText(f"{t(_NAMES[k])}\n{t(_BLURBS[k])}")
        self.browse.setText(t("Choose file…"))
        self.file.setPlaceholderText(t("Choose a file, or drop one on this window"))
        self.show_btn.setText(t("Show in folder"))
        self.size_combo.setItemText(self.size_combo.count() - 1, t("Custom…"))
        self.short_lbl.setText(t("Length of the Short"))
        self.short_follow.setText(t("Keep the main face in the picture"))
        self.short_caps.setText(t("Add word-by-word captions"))
        self.short_note.setText(t("It picks the liveliest part, makes it vertical (9:16) and evens out the "
                                  "sound. Captions need the speech model, which downloads once."))
        self.size_lbl.setText(t("Make the file about"))
        self.shrink_lbl.setText(t("Picture size"))
        self.shrink_box.setItemText(0, t("Lower the resolution when needed (recommended)"))
        self.shrink_box.setItemText(1, t("Keep the resolution"))
        self.convert_lbl.setText(t("Convert to"))
        self.audio_lbl.setText(t("Save as"))
        for lbl, key in zip(self.gif_lbls, ("Start at", "Length", "Width"), strict=True):
            lbl.setText(t(key))
        for lbl, key in zip(self.th_lbls, ("Take the frame at", "Title on the picture (optional)"), strict=True):
            lbl.setText(t(key))
        self.th_text.setPlaceholderText(t("Leave empty for no text"))
        self._refresh_ui()

    # ── state ──────────────────────────────────────────────────────────

    def select_tool(self, key: str) -> None:
        self._tool = key
        self.tiles[key].setChecked(True)
        self.opts.setCurrentIndex(TOOLS.index(key))
        t = self.host.t
        self.title.setText(t(_NAMES[key]))
        self.blurb.setText(t(_BLURBS[key]))
        self.status.setText("")
        self.bar.setValue(0)
        self._refresh_ui()
        self._update_thumb()

    def set_file(self, path: str) -> None:
        """Use *path* as the input (also called by the Library)."""
        self._src = path
        self.file.setText(path)
        try:
            self._duration = float(studio.probe_media(path).get("duration") or 0.0)
        except (RuntimeError, OSError, ValueError):
            self._duration = 0.0
        self.info.setText(f"{Path(path).name}  ·  {self._duration:.0f} s" if self._duration else Path(path).name)
        for spin in (self.gif_start, self.th_time):
            spin.setMaximum(max(self._duration, 1.0))
        self.status.setText("")
        self.bar.setValue(0)
        self._refresh_ui()
        self._update_thumb()

    def _refresh_ui(self) -> None:
        t = self.host.t
        self.run_btn.setText(t("Cancel") if self._running else t("Start"))
        self.run_btn.setEnabled(bool(self._src) or self._running)
        self.show_btn.setVisible(bool(self._out) and not self._running)

    def _browse(self) -> None:
        path = self.host.pick_file(self.host.t("Choose a file"), ("videos", "downloads"), _FILTER)
        if path:
            self.set_file(path)

    # ── running ────────────────────────────────────────────────────────

    def _start_stop(self) -> None:
        if self._running:
            self._cancel.set()
            return
        if not self.host.ffmpeg_ok():
            return
        src, t, key = self._src, self.host.t, self._tool
        try:
            if key == "thumbnail":
                self._save_thumb()
                return
            if key == "short":
                self._start_short(src)
                return
            cmd, total = self._command(src)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            return
        self._cancel.clear()
        self._running, self._out = True, ""
        self.bar.setValue(0)
        self.status.setText(t("Working…"))
        self._refresh_ui()
        self._pool.start(_Task(self._relay, cmd, total, t("Working…"), self._cancel, self.host.t))

    def _start_short(self, src: str) -> None:
        t = self.host.t
        out = tools.output_for(src, "short", ".mp4")
        seconds, follow, caps = self.short_len.currentData(), self.short_follow.isChecked(), self.short_caps.isChecked()
        models, gpu = self.host.models_dir(), self.host.use_gpu_captions()

        def work(progress, cancelled):
            try:
                return shorts.make_short(src, out, seconds=seconds, follow=follow, with_captions=caps,
                                         models_dir=models, gpu=gpu, on_progress=progress,
                                         on_log=self.host.log, cancelled=cancelled, translate=t)
            except BaseException:
                out.unlink(missing_ok=True)
                raise

        self._cancel.clear()
        self._running, self._out = True, ""
        self.bar.setValue(0)
        self.status.setText(t("Working…"))
        self._refresh_ui()
        self._pool.start(_Job(self._relay, work, self._cancel))

    def _command(self, src: str) -> tuple[list[str], float]:
        key, dur = self._tool, self._duration
        folder = None  # next to the source file
        if key == "compress":
            mb = self.target_mb()
            height = tools.suggested_height(mb, dur) if self.shrink_box.currentData() else 0
            out = tools.output_for(src, f"{mb:g} MB", ".mp4", folder)
            return tools.compress_command(src, str(out), mb, dur, height), dur
        if key in ("convert", "audio"):
            fmt = (self.convert_fmt if key == "convert" else self.audio_fmt).currentData()
            out = tools.output_for(src, "converted" if key == "convert" else "audio", tools.CONVERT[fmt][0], folder)
            return tools.convert_command(src, str(out), fmt), dur
        length = self.gif_len.value()
        out = tools.output_for(src, "gif", ".gif", folder)
        return tools.gif_command(src, str(out), self.gif_start.value(), length, self.gif_width.currentData()), length

    def _progress(self, msg: str, pct: float) -> None:
        self.bar.setValue(int(pct))
        if self._tool == "short" and msg:
            self.status.setText(msg)

    def _done(self, out: str, err: str) -> None:
        t = self.host.t
        self._running = False
        if err == "cancelled":
            self.status.setText(t("Cancelled"))
        elif err:
            self.status.setText(err)
            self.host.log(err)
        else:
            self._out = out
            self.bar.setValue(100)
            size = Path(out).stat().st_size / (1024 * 1024) if Path(out).is_file() else 0
            self.status.setText(t("Done: {name} ({mb:.1f} MB)", name=Path(out).name, mb=size))
        self._refresh_ui()

    # ── thumbnail maker ────────────────────────────────────────────────

    def _frame(self, height: int) -> QImage | None:
        if not self._src or studio.find_ffmpeg() is None:
            return None
        png = studio.thumbnail_png(self._src, self.th_time.value(), height)
        return QImage.fromData(png) if png else None

    def _compose(self, img: QImage) -> QImage:
        """The frame with the title painted on (bottom, white with a dark edge)."""
        text = self.th_text.text().strip()
        out = img.convertToFormat(QImage.Format_RGB32)
        if not text:
            return out
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(int(out.height() * 0.13), 10))
        p.setFont(font)
        path = QPainterPath()
        width = p.fontMetrics().horizontalAdvance(text)
        while width > out.width() * 0.9 and font.pixelSize() > 8:
            font.setPixelSize(font.pixelSize() - 2)
            p.setFont(font)
            width = p.fontMetrics().horizontalAdvance(text)
        path.addText((out.width() - width) / 2, out.height() * 0.88, font, text)
        p.setPen(QPen(QColor(0, 0, 0, 230), max(out.height() * 0.012, 2), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.fillPath(path, QColor("#ffffff"))
        p.end()
        return out

    def _update_thumb(self) -> None:
        if self._tool != "thumbnail" or not hasattr(self, "th_prev"):
            return
        img = self._frame(360)
        if img is None or img.isNull():
            self.th_prev.clear()
            return
        self.th_prev.setPixmap(QPixmap.fromImage(self._compose(img)).scaled(
            QSize(360, 202), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _save_thumb(self) -> None:
        t = self.host.t
        img = self._frame(THUMB_H)
        if img is None or img.isNull():
            self.status.setText(t("Could not read a frame from this file."))
            return
        out = tools.output_for(self._src, "thumbnail", ".png")
        if self._compose(img).save(str(out)):
            self._out = str(out)
            self.status.setText(t("Done: {name} ({mb:.1f} MB)", name=out.name, mb=out.stat().st_size / (1024 * 1024)))
        else:
            self.status.setText(t("Could not save the picture."))
        self._refresh_ui()

    def shutdown(self) -> None:
        self._cancel.set()
        self._pool.waitForDone(3000)
