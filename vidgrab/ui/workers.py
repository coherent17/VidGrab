"""Background threads (probe, ffmpeg fetch, updates, the render / download worker)."""
from __future__ import annotations

import sys

from PySide6.QtCore import (
    QThread,
    Signal,
)

from vidgrab.ai.captions import (
    detect_gpus,
    transcribe,
)
from vidgrab.core import (
    ffmpeg_fetch,
    self_update,
    update_check,
    ytdlp_update,
)
from vidgrab.core.downloader import (
    DownloadCancelled,
    download,
    download_both,
    download_playlist,
    fetch_dislikes,
    probe,
)
from vidgrab.core.gpu import detect_encoder
from vidgrab.core.jobs import run_job
from vidgrab.media.studio import compose_audio, compose_split, compose_video
from vidgrab.ui.config import _models_dir

_STOP_GRACE_MS = 5000  # how long a thread gets to finish when the window closes


_STUCK: list[QThread] = []  # threads that ignored a stop request; kept alive, see main()


def _detached() -> dict:
    """Popen options so the restarted VidGrab outlives this one."""
    if sys.platform == "win32":
        return {"creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def _stop_thread(thread: QThread, grace_ms: int | None = None) -> bool:
    """Ask *thread* to stop and wait for it; True if it finished. One that is
    stuck in a driver or library call can't be killed safely: it is parked in
    `_STUCK` (destroying a running QThread aborts the whole process) and
    `main()` leaves with `os._exit` instead of tearing it down."""
    if not thread.isRunning():
        return True
    cancel = getattr(thread, "cancel", None)
    if callable(cancel):
        cancel()
    if thread.wait(_STOP_GRACE_MS if grace_ms is None else grace_ms):
        return True
    if thread not in _STUCK:
        _STUCK.append(thread)
    return False


class _HwProbe(QThread):
    """Find the graphics video encoder that works here (it test-encodes a clip,
    a couple of seconds) without freezing the window."""

    found = Signal(object)  # gpu.HwEncoder or None

    def __init__(self, ffmpeg: str | None) -> None:
        super().__init__()
        self._ffmpeg = ffmpeg

    def run(self) -> None:
        encoder = detect_encoder(self._ffmpeg) if self._ffmpeg else None
        detect_gpus()  # the captions engines too (starts OpenVINO's GPU plugin); cached for later
        self.found.emit(encoder)


class _FfmpegThread(QThread):
    """Download the pinned ffmpeg into the user's cache (see ffmpeg_fetch)."""

    progress = Signal(int)  # percent, -1 = unknown
    done = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        def report(got: int, total: int) -> None:
            if self.isInterruptionRequested():
                raise RuntimeError("cancelled")
            self.progress.emit(int(got * 100 / total) if total else -1)

        try:
            self.done.emit(ffmpeg_fetch.ensure(report))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _ReleaseThread(QThread):
    found = Signal(dict)

    def __init__(self, proxy: str) -> None:
        super().__init__()
        self._proxy = proxy

    def run(self) -> None:
        news = update_check.latest_release(proxy=self._proxy)
        if news:
            self.found.emit(news)


class _InstallThread(QThread):
    """Download the new version and swap it in (`self_update`); never destroyed while running."""

    progress = Signal(int)
    done = Signal()
    failed = Signal(str)

    def __init__(self, news: dict, how: self_update.Plan, proxy: str) -> None:
        super().__init__()
        self._news, self._how, self._proxy = news, how, proxy

    def run(self) -> None:
        try:
            new = self_update.download(self._news, self._how, on_progress=self.progress.emit,
                                       cancelled=self.isInterruptionRequested, proxy=self._proxy)
            if self.isInterruptionRequested():
                new.unlink(missing_ok=True)
                return
            self_update.install(new, self._how.exe)
        except self_update.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.done.emit()


class _YtdlpThread(QThread):
    """Ask PyPI for a newer yt-dlp ("check"), or download and unpack it ("update")."""

    result = Signal(object)  # check(): the dict; update(): {"updated": version}
    failed = Signal(str)

    def __init__(self, task: str) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            if self._task == "check":
                self.result.emit(ytdlp_update.check())
            else:
                self.result.emit({"updated": ytdlp_update.update()})
        except Exception as exc:  # noqa: BLE001 - offline, PyPI down, bad file…
            self.failed.emit(str(exc))


class _Worker(QThread):
    """Run a download / processing / probe task off the main thread."""

    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(str, object)
    log = Signal(str)
    probed = Signal(object)
    probe_error = Signal(str)

    def __init__(self, task: str, **kwargs) -> None:
        super().__init__()
        self._task = task
        self._kw = kwargs
        self._cancel = False

    def cancel(self) -> None:
        """Ask the task to stop at its next progress update."""
        self._cancel = True

    def _cb_progress(self, msg: str, pct: float | None) -> None:
        if self._cancel:
            raise DownloadCancelled()
        self.progress.emit(msg, pct)

    def _cb_log(self, msg: str) -> None:
        self.log.emit(msg)

    def run(self) -> None:
        try:
            if self._task == "probe":
                result = probe(
                    self._kw["url"],
                    thumb_dir=self._kw.get("thumb_dir"),
                    translate=self._kw.get("translate"),
                )
                if result.get("is_playlist") is False and result.get("dislike_count") is None:
                    dislike = fetch_dislikes(result.get("id") or "")
                    if dislike is not None:
                        result["dislike_count"] = dislike
                self.probed.emit(result)
                return
            common = {
                "video_filter": self._kw.get("video_filter"),
                "speed": self._kw.get("speed"),
                "quality": self._kw.get("quality"),
                "section_start": self._kw.get("section_start"),
                "section_end": self._kw.get("section_end"),
                "on_progress": self._cb_progress,
                "on_log": self._cb_log,
                "translate": self._kw.get("translate"),
            }
            if self._task == "download":
                result = download(
                    self._kw["url"], self._kw["output_dir"], self._kw["fmt"],
                    **common,
                )
            elif self._task == "download_both":
                result = download_both(
                    self._kw["url"], self._kw["output_dir"], **common,
                )
            elif self._task == "download_playlist":
                result = download_playlist(
                    self._kw["url"], self._kw["output_dir"], self._kw["fmt"],
                    quality=self._kw.get("quality"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "job":
                result = run_job(
                    self._kw["job"],
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "compose_video":
                result = compose_video(
                    self._kw["clips"], self._kw["output_file"],
                    resolution=self._kw.get("resolution", "auto"),
                    subtitles=self._kw.get("subtitles"),
                    subtitle_style=self._kw.get("subtitle_style"),
                    music=self._kw.get("music"),
                    images=self._kw.get("images"),
                    quality=self._kw.get("render_quality", "balanced"),
                    hardware=bool(self._kw.get("hardware")),
                    normalize_loudness=bool(self._kw.get("normalize_loudness")),
                    models_dir=self._kw.get("models_dir"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "combine":
                result = compose_split(
                    self._kw["clips"], self._kw["output_file"],
                    layout=self._kw.get("layout", "side"),
                    resolution=self._kw.get("resolution", "1080p"),
                    gap=self._kw.get("gap", 0),
                    audio=self._kw.get("audio", "both"),
                    length=self._kw.get("length", "longest"),
                    quality=self._kw.get("render_quality", "balanced"),
                    hardware=bool(self._kw.get("hardware")),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "transcribe":
                result = transcribe(
                    self._kw["sources"], _models_dir(),
                    language=self._kw.get("language", "auto"),
                    size=self._kw.get("size", "balanced"),
                    gpu=bool(self._kw.get("gpu", True)),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            elif self._task == "compose_audio":
                result = compose_audio(
                    self._kw["clips"], self._kw["output_file"],
                    crossfade=self._kw.get("crossfade", 0.0),
                    bitrate=self._kw.get("bitrate"),
                    on_progress=self._cb_progress,
                    on_log=self._cb_log,
                    translate=self._kw.get("translate"),
                )
            else:
                raise RuntimeError(f"Unknown task: {self._task}")
            self.finished.emit(result)
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            if self._task == "probe":
                self.probe_error.emit(str(exc))
            else:
                self.error.emit(str(exc))
