"""Background tasks (thumbnails, effects frames, follow-the-face, best moment, beats)."""
from __future__ import annotations

import threading
from collections import OrderedDict

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QImage,
)

from vidgrab.ai import beats, highlights, reframe
from vidgrab.core.downloader import DownloadCancelled
from vidgrab.media.studio import (
    effect_frame_png,
    thumbnail_png,
)


class _ThumbRelay(QObject):
    done = Signal(str, float, QImage)


class _ThumbTask(QRunnable):
    def __init__(self, relay: _ThumbRelay, path: str, at: float) -> None:
        super().__init__()
        self._relay, self._path, self._at = relay, path, at

    def run(self) -> None:
        png = thumbnail_png(self._path, self._at)
        self._relay.done.emit(self._path, self._at, QImage.fromData(png) if png else QImage())


class _FxRelay(QObject):
    done = Signal(int, bytes, bytes)


class _FxTask(QRunnable):
    """The clip's frame before and after its effects (for the Effects tab)."""

    def __init__(self, relay: _FxRelay, gen: int, path: str, at: float, fx: dict) -> None:
        super().__init__()
        self._relay, self._gen, self._path, self._at, self._fx = relay, gen, path, at, fx

    def run(self) -> None:
        before = thumbnail_png(self._path, self._at, 150) or b""
        after = effect_frame_png(self._path, self._at, self._fx, 150) or b""
        self._relay.done.emit(self._gen, before, after)


class _FollowRelay(QObject):
    done = Signal(int, object, str)  # generation, keys, error text
    progress = Signal(int, str, int)


class _FollowTask(QRunnable):
    """Look for the face in a clip's part (Follow the face)."""

    def __init__(self, relay: _FollowRelay, gen: int, path: str, start: float, end: float,
                 models_dir: str, cancel: threading.Event, tr) -> None:
        super().__init__()
        self._relay, self._gen, self._path = relay, gen, path
        self._start, self._end, self._dir, self._cancel, self._tr = start, end, models_dir, cancel, tr

    def run(self) -> None:
        try:
            keys = reframe.follow_face(
                self._path, self._start, self._end, self._dir,
                on_progress=lambda text, pct: self._relay.progress.emit(self._gen, text, pct),
                cancelled=self._cancel.is_set, translate=self._tr)
        except DownloadCancelled:
            return
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._relay.done.emit(self._gen, [], str(exc))
            return
        self._relay.done.emit(self._gen, keys, "")


class _BestRelay(QObject):
    done = Signal(int, float, float, str)  # clip index, start, end, error


class _BestTask(QRunnable):
    """Find the liveliest stretch of a clip (Best moment)."""

    def __init__(self, relay: _BestRelay, i: int, path: str, start: float, end: float, length: float) -> None:
        super().__init__()
        self._relay, self._i, self._args = relay, i, (path, start, end, length)

    def run(self) -> None:
        try:
            a, b = highlights.find_best(*self._args)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._relay.done.emit(self._i, 0.0, 0.0, str(exc))
            return
        self._relay.done.emit(self._i, a, b, "")


class _BeatRelay(QObject):
    done = Signal(float, list, str)  # BPM, beat times on the montage timeline, error


class _BeatTask(QRunnable):
    """Find the beats of a song (Cut to the beat)."""

    def __init__(self, relay: _BeatRelay, path: str, start: float, end: float | None, offset: float) -> None:
        super().__init__()
        self._relay, self._args, self._offset = relay, (path, start, end), offset

    def run(self) -> None:
        try:
            found = beats.detect(*self._args)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._relay.done.emit(0.0, [], str(exc))
            return
        if found is None:
            self._relay.done.emit(0.0, [], "")
            return
        self._relay.done.emit(found.bpm, [round(self._offset + t, 3) for t in found.times], "")


class ThumbCache(QObject):
    """Timeline frames, extracted on demand in the background so every tile
    shows the frame at its own time (and zooming in shows finer detail)."""

    updated = Signal()
    LIMIT = 1200  # frames kept (~10 KB each)
    MAX_PENDING = 48

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._relay = _ThumbRelay(self)
        self._relay.done.connect(self._done)
        self._images: OrderedDict[tuple[str, float], QImage] = OrderedDict()
        self._by_path: dict[str, dict[float, QImage]] = {}
        self._pending: set[tuple[str, float]] = set()

    def frame(self, path: str, at: float, step: float) -> QImage | None:
        """The frame for *at* rounded to *step*; queued (None) if not ready."""
        key = (path, round(round(at / step) * step, 3))
        img = self._images.get(key)
        if img is not None:
            self._images.move_to_end(key)
            return img
        if key not in self._pending and len(self._pending) < self.MAX_PENDING:
            self._pending.add(key)
            self._pool.start(_ThumbTask(self._relay, path, key[1]))
        return None

    def nearest(self, path: str, at: float) -> QImage | None:
        frames = self._by_path.get(path)
        if not frames:
            return None
        return frames[min(frames, key=lambda t: abs(t - at))]

    def _done(self, path: str, at: float, img: QImage) -> None:
        self._pending.discard((path, at))
        if img.isNull():
            return
        self._images[(path, at)] = img
        self._by_path.setdefault(path, {})[at] = img
        while len(self._images) > self.LIMIT:
            (old_path, old_at), _img = self._images.popitem(last=False)
            self._by_path.get(old_path, {}).pop(old_at, None)
        self.updated.emit()

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(3000)
