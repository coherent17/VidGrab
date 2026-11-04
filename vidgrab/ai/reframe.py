"""Auto-reframe: find the face in a clip and work out where the crop window
should be, second by second, so a wide video can be cut to a tall one without
losing the speaker. Qt-free.

Faces come from the 1 MB "Ultra-Light" RFB-320 detector (MIT licence), run with
onnxruntime (already there for the speech engine's voice filter); the model is
downloaded once into the models folder, like the speech models. The result is
a handful of keys [[source seconds, x, y], ...] (`effects` "follow"), which
`studio._frame_filter` turns into a moving crop."""
from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path

from vidgrab.core.downloader import DownloadCancelled
from vidgrab.media import studio

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy comes with faster-whisper
    np = None

MODEL_NAME = "face-rfb-320.onnx"
MODEL_URL = ("https://github.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB/"
             "raw/master/models/onnx/version-RFB-320.onnx")
MODEL_SHA256 = "34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017"
MODEL_SIZE_LABEL = "1.2 MB"
IN_W, IN_H = 320, 240
SCORE_MIN = 0.7
SAMPLE_FPS = 4

ProgressCallback = Callable[[str, int], None]


def available() -> bool:
    """Can the face finder run here (numpy + onnxruntime installed)?"""
    if np is None:
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def model_path(models_dir: str | Path) -> Path:
    return Path(models_dir) / "face" / MODEL_NAME


def model_ready(models_dir: str | Path) -> bool:
    return model_path(models_dir).is_file()


def ensure_model(models_dir: str | Path, translate: studio.TranslateFn | None = None) -> Path:
    """The face model, downloaded (and checked) the first time."""
    tr = translate or (lambda text, **kw: text.format(**kw) if kw else text)
    dest = model_path(models_dir)
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    offline = tr("The face model could not be downloaded. Check your internet connection.")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as resp, open(part, "wb") as fh:
            digest = hashlib.sha256()
            while chunk := resp.read(1 << 18):
                fh.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise OSError("the downloaded file is not the expected model")
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{offline} ({exc})") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    return dest


# ── finding faces ─────────────────────────────────────────────────────────


def _nms(boxes, scores, iou_max: float = 0.3) -> list[int]:
    order = list(np.argsort(-scores))
    keep: list[int] = []
    while order:
        i = order.pop(0)
        keep.append(i)
        rest = []
        for j in order:
            x1, y1 = max(boxes[i][0], boxes[j][0]), max(boxes[i][1], boxes[j][1])
            x2, y2 = min(boxes[i][2], boxes[j][2]), min(boxes[i][3], boxes[j][3])
            inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            area_i = (boxes[i][2] - boxes[i][0]) * (boxes[i][3] - boxes[i][1])
            area_j = (boxes[j][2] - boxes[j][0]) * (boxes[j][3] - boxes[j][1])
            if inter / max(area_i + area_j - inter, 1e-9) <= iou_max:
                rest.append(j)
        order = rest
    return keep


def decode(scores, boxes, threshold: float = SCORE_MIN) -> list[tuple[float, float, float, float, float]]:
    """The detector's raw output -> faces as (x1, y1, x2, y2, score), 0..1."""
    conf = scores.reshape(-1, 2)[:, 1]
    box = boxes.reshape(-1, 4)
    ok = conf > threshold
    if not ok.any():
        return []
    conf, box = conf[ok], np.clip(box[ok], 0.0, 1.0)
    return [(*map(float, box[i]), float(conf[i])) for i in _nms(box, conf)]


class FaceFinder:
    def __init__(self, path: str | Path) -> None:
        import onnxruntime as ort

        ort.set_default_logger_severity(3)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def find(self, rgb) -> list[tuple[float, float, float, float, float]]:
        """*rgb*: uint8 array (240, 320, 3)."""
        x = (rgb.astype(np.float32) - 127.0) / 128.0
        scores, boxes = self._session.run(None, {self._input: x.transpose(2, 0, 1)[None]})
        return decode(scores, boxes)


def _frames(path: str | Path, start: float, end: float, fps: int):
    """RGB frames (240, 320, 3) of [start, end] at *fps*, from ffmpeg."""
    ffmpeg = studio.find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    proc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(path),
         "-an", "-vf", f"fps={fps},scale={IN_W}:{IN_H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **studio._no_window())
    size = IN_W * IN_H * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                return
            yield np.frombuffer(buf, np.uint8).reshape(IN_H, IN_W, 3)
    finally:
        proc.kill()
        proc.wait()


# ── turning faces into a camera path ──────────────────────────────────────


def pick_face(faces, previous: tuple[float, float] | None):
    """The face to follow: a big one, near where we were looking."""
    def score(f):
        cx, cy = (f[0] + f[2]) / 2, (f[1] + f[3]) / 2
        size = (f[2] - f[0]) * (f[3] - f[1])
        near = 0.0 if previous is None else ((cx - previous[0]) ** 2 + (cy - previous[1]) ** 2) ** 0.5
        return size * 4 - near
    return max(faces, key=score) if faces else None


def smooth_path(points: list[tuple[float, float, float] | None], fps: float,
                dead: float = 0.04) -> list[list[float]]:
    """Camera positions from per-frame face centres (None = no face seen):
    gaps are bridged, tiny movements are ignored (the camera holds still) and
    bigger ones are followed smoothly. Returns [t, x, y] for every sample."""
    seen = [p for p in points if p is not None]
    if not seen:
        return []
    filled: list[tuple[float, float]] = []
    last = (seen[0][1], seen[0][2])
    for p in points:
        if p is not None:
            last = (p[1], p[2])
        filled.append(last)
    # a median of five takes out one-frame jumps
    med = []
    for i in range(len(filled)):
        win = filled[max(0, i - 2): i + 3]
        med.append((sorted(w[0] for w in win)[len(win) // 2], sorted(w[1] for w in win)[len(win) // 2]))
    out = []
    cam = list(med[0])
    moving = [False, False]  # a move starts past *dead* and runs until the camera has caught up
    for i, target in enumerate(med):
        for axis in (0, 1):
            gap = abs(target[axis] - cam[axis])
            if gap > dead:
                moving[axis] = True
            elif gap < dead / 4:
                moving[axis] = False
            if moving[axis]:
                cam[axis] += (target[axis] - cam[axis]) * 0.6
        out.append([round(i / fps, 3), round(cam[0], 4), round(cam[1], 4)])
    return out


def simplify(keys: list[list[float]], tol: float = 0.01, limit: int = 150) -> list[list[float]]:
    """Fewest keys that stay within *tol* of the path (Ramer-Douglas-Peucker);
    the tolerance grows until there are at most *limit*."""
    def rdp(lo: int, hi: int, eps: float) -> set[int]:
        if hi <= lo + 1:
            return {lo, hi}
        a, b = keys[lo], keys[hi]
        worst, at = 0.0, lo
        for i in range(lo + 1, hi):
            f = (keys[i][0] - a[0]) / max(b[0] - a[0], 1e-6)
            err = max(abs(keys[i][1] - (a[1] + (b[1] - a[1]) * f)),
                      abs(keys[i][2] - (a[2] + (b[2] - a[2]) * f)))
            if err > worst:
                worst, at = err, i
        if worst <= eps:
            return {lo, hi}
        return rdp(lo, at, eps) | rdp(at, hi, eps)

    if len(keys) < 3:
        return keys
    eps = tol
    while True:
        keep = sorted(rdp(0, len(keys) - 1, eps))
        if len(keep) <= limit:
            return [keys[i] for i in keep]
        eps *= 1.5


def follow_face(path: str | Path, start: float, end: float, models_dir: str | Path, *,
                on_progress: ProgressCallback | None = None,
                cancelled: Callable[[], bool] | None = None,
                translate: studio.TranslateFn | None = None) -> list[list[float]]:
    """Keys [[source seconds, x, y], ...] that keep the main face in view while
    [start, end] of the video plays; [] when no face was found."""
    tr = translate or (lambda text, **kw: text.format(**kw) if kw else text)
    if not available():
        raise RuntimeError(tr("Face tracking needs the speech add-on (onnxruntime), which this "
                              "installation doesn't have."))
    model = ensure_model(models_dir, translate)
    finder = FaceFinder(model)
    total = max(1, round((end - start) * SAMPLE_FPS))
    points: list[tuple[float, float, float] | None] = []
    previous = None
    for n, frame in enumerate(_frames(path, start, end, SAMPLE_FPS)):
        if cancelled and cancelled():
            raise DownloadCancelled(tr("Cancelled"))
        face = pick_face(finder.find(frame), previous)
        if face is None:
            points.append(None)
        else:
            previous = ((face[0] + face[2]) / 2, (face[1] + face[3]) / 2)
            points.append((n / SAMPLE_FPS, previous[0], previous[1]))
        if on_progress and n % 8 == 0:
            on_progress(tr("Looking for the face…"), min(99, int(n * 100 / total)))
    if sum(p is not None for p in points) < max(2, len(points) * 0.3):
        return []  # a face in under a third of the frames: not a talking head
    keys = simplify(smooth_path(points, SAMPLE_FPS))
    return [[round(start + k[0], 3), k[1], k[2]] for k in keys]


