"""Qt-free **Remove background** (Effects tab): a see-through matte for a clip.

`make_matte()` decodes the clip's part at `MATTE_FPS` and a square `SIZE`, runs the
small U²-Net-P model (4.6 MB, Apache-2.0, through onnxruntime on the CPU) on every
frame, steadies the result over time and writes the mattes as a grey video. The
render lines that video up with the picture (same crop / zoom / speed) and uses it as
the alpha channel (`studio.build_video_command`, `fx["cutout"]`), so the person
stays and whatever was behind them is replaced by the clip's background picture or
black. It works best on one person or object filling a good part of the frame; the
render, not the live preview, shows it."""
from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path

from vidgrab.core.downloader import DownloadCancelled, find_ffmpeg
from vidgrab.media import studio

try:
    import numpy as np
except ImportError:  # the speech add-on brings it; without it the button explains
    np = None

MODEL_NAME = "u2netp.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
MODEL_SHA256 = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"
SIZE = 320  # the model's input
MATTE_FPS = 15  # the matte video; the render repeats frames up to the clip's own rate
SMOOTH = 0.55  # how much of the new frame's matte replaces the last one (less flicker)
_MEAN = (0.485, 0.456, 0.406)
_STD = (0.229, 0.224, 0.225)


def available() -> bool:
    if np is None:
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def model_path(models_dir: str | Path) -> Path:
    return Path(models_dir) / "matte" / MODEL_NAME


def model_ready(models_dir: str | Path) -> bool:
    return model_path(models_dir).is_file()


def ensure_model(models_dir: str | Path, translate: studio.TranslateFn | None = None) -> Path:
    """The model, downloaded (and checked against its SHA-256) the first time."""
    tr = translate or (lambda text, **kw: text.format(**kw) if kw else text)
    dest = model_path(models_dir)
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    offline = tr("The background model could not be downloaded. Check your internet connection.")
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


class Matter:
    """The model: a square RGB frame in, a 0..1 matte of the same size out."""

    def __init__(self, model: str | Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def matte(self, rgb) -> np.ndarray:
        """*rgb*: SIZE x SIZE x 3 uint8 -> SIZE x SIZE float32 in 0..1."""
        x = rgb.astype("float32") / 255.0
        x = (x - np.array(_MEAN, dtype="float32")) / np.array(_STD, dtype="float32")
        out = self._session.run(None, {self._input: x.transpose(2, 0, 1)[None]})[0]
        m = out.reshape(SIZE, SIZE)
        lo, hi = float(m.min()), float(m.max())
        return (m - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(m)


def steady(previous, current, weight: float = SMOOTH):
    """Blend a frame's matte with the last one: less flicker, edges still follow the motion."""
    if previous is None:
        return current
    return weight * current + (1.0 - weight) * previous


def make_matte(src: str | Path, start: float, end: float, out_file: str | Path, models_dir: str | Path, *,
               on_progress: Callable[[str, float | None], None] | None = None,
               cancelled: Callable[[], bool] | None = None,
               translate: studio.TranslateFn | None = None) -> Path:
    """Write the matte of *src* between *start* and *end* seconds as a grey video."""
    tr = translate or (lambda text, **kw: text.format(**kw) if kw else text)
    if not available():
        raise RuntimeError(tr("Removing the background needs the speech add-on (onnxruntime), which this "
                              "installation doesn't have."))
    ffmpeg = find_ffmpeg() or "ffmpeg"
    model = ensure_model(models_dir, translate)
    matter = Matter(model)
    frame_bytes = SIZE * SIZE * 3
    total = max(1, round((end - start) * MATTE_FPS))
    out_file = Path(out_file)
    reader = subprocess.Popen(
        [ffmpeg, "-v", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{max(end - start, 0.1):.3f}", "-i", str(src),
         "-an", "-vf", f"fps={MATTE_FPS},scale={SIZE}:{SIZE}:flags=bilinear", "-pix_fmt", "rgb24",
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **studio._no_window())
    writer = subprocess.Popen(
        [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{SIZE}x{SIZE}",
         "-r", str(MATTE_FPS), "-i", "-", "-c:v", "ffv1", str(out_file)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, **studio._no_window())
    previous = None
    done = 0
    try:
        while True:
            if cancelled and cancelled():
                raise DownloadCancelled(tr("Cancelled"))
            raw = reader.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            rgb = np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3)
            previous = steady(previous, matter.matte(rgb))
            writer.stdin.write((previous * 255).clip(0, 255).astype(np.uint8).tobytes())
            done += 1
            if on_progress and done % 5 == 0:
                on_progress(tr("Cutting out the background…"), min(99.0, done * 100 / total))
        writer.stdin.close()
        if writer.wait(timeout=120) != 0 or done == 0 or not out_file.is_file():
            raise RuntimeError(tr("Could not cut out the background of this clip."))
    except BaseException:
        _stop(reader, writer)  # Windows can't delete a file ffmpeg still has open
        out_file.unlink(missing_ok=True)
        raise
    finally:
        _stop(reader, writer)
    return out_file


def _stop(*procs: subprocess.Popen) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
