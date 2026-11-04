"""ffprobe, thumbnails, silences and waveforms."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from array import array
from pathlib import Path

from vidgrab.core.downloader import (
    TranslateFn,
    _noop_tr,
    find_ffmpeg,
)
from vidgrab.media import effects

# ── ffprobe ───────────────────────────────────────────────────────────────


def find_ffprobe() -> str | None:
    """Locate ffprobe beside ffmpeg (bundled or not), then PATH."""
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        peer = Path(ffmpeg).parent / name
        if peer.is_file():
            return str(peer)
    return shutil.which(name)


def probe_media(path: str | Path, *, translate: TranslateFn | None = None) -> dict:
    """Return duration and stream facts for a local media file."""
    tr = translate or _noop_tr
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise RuntimeError(tr("ffprobe is required to read media files."))
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            ("format=duration:stream=codec_type,width,height,duration,avg_frame_rate"
             ":stream_disposition=attached_pic"),
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=False, timeout=30,
        **_no_window(),
    )
    if proc.returncode != 0:
        raise RuntimeError(tr("Could not read media file: {name}", name=Path(path).name))
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    # cover art in MP3/M4A shows up as a 1-frame "video" stream — ignore it
    video = [
        s for s in streams
        if s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
    ]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = _to_float((data.get("format") or {}).get("duration"))
    if duration is None:
        for s in video + audio:
            duration = _to_float(s.get("duration"))
            if duration:
                break
    return {
        "duration": duration or 0.0,
        "has_video": bool(video),
        "has_audio": bool(audio),
        "width": int(video[0].get("width") or 0) if video else 0,
        "height": int(video[0].get("height") or 0) if video else 0,
        "fps": _frame_rate(video[0].get("avg_frame_rate")) if video else 0.0,
    }


def _frame_rate(value: object) -> float:
    """ffprobe's "30000/1001" → 29.97 (0.0 if unknown)."""
    num, _, den = str(value or "").partition("/")
    try:
        rate = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return rate if 1 <= rate <= 240 else 0.0


def thumbnail_png(path: str | Path, at: float = 0.0, height: int = 72) -> bytes | None:
    """One video frame at *at* seconds as PNG bytes (None if it can't be read)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    proc = subprocess.run(
        [
            ffmpeg, "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale=-2:{height}", "-f", "image2pipe",
            "-vcodec", "png", "-",
        ],
        capture_output=True, check=False, timeout=30, **_no_window(),
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def effect_frame_png(path: str | Path, at: float, fx: dict, height: int = 150) -> bytes | None:
    """One frame with the clip's picture effects applied (what the Effects tab
    shows beside the original). Stabilising and slow motion need the whole
    clip, so they are left out here."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    fx = effects.sanitize(fx)
    lut = Path(fx["lut"]) if fx.get("lut") and Path(fx["lut"]).is_file() else None
    chain = effects.source_chain(fx, lut_name=lut.name if lut else None)
    key = effects.key_filter(fx)
    scale = f"scale=-2:{height}"
    cmd = [ffmpeg, "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(path)]
    if key:  # show it over a grey card, or the chosen picture
        bg = fx.get("key_bg")
        if bg and Path(bg).is_file():
            cmd += ["-i", str(bg)]
            back = f"[1:v]{scale},crop=trunc(iw/2)*2:{height},format=yuv420p[b]"
        else:
            cmd += ["-f", "lavfi", "-i", "color=c=0x303030:s=640x360"]
            back = f"[1:v]{scale},format=yuv420p[b]"
        graph = (f"[0:v]{chain}{key},format=yuva420p,{scale}[k];{back};"
                 "[b][k]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p")
        cmd += ["-filter_complex", graph]
    else:
        cmd += ["-vf", f"{chain}{scale}"]
    cmd += ["-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=30,
                              cwd=str(lut.parent) if lut else None, **_no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


# ── silence removal ────────────────────────────────────────────────────────

SILENCE_LEVELS = {"silence": -46, "quiet": -38, "faint": -30}  # dB below which it is "quiet"
SILENCE_PAD = 0.12  # breathing room kept on each side of a pause (s)


def detect_silences(path: str | Path, start: float, end: float, *, noise_db: float = -38,
                    min_len: float = 0.6) -> list[tuple[float, float]]:
    """Quiet stretches of at least *min_len* seconds inside [start, end] of the
    file, as (from, to) in the file's own time. Nothing for a file without sound."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or end <= start:
        return []
    try:
        proc = subprocess.run(
            [ffmpeg, "-nostats", "-hide_banner", "-ss", f"{max(0.0, start):.3f}",
             "-t", f"{end - start:.3f}", "-i", str(path), "-vn",
             "-af", f"silencedetect=noise={noise_db:g}dB:d={min_len:g}", "-f", "null", "-"],
            capture_output=True, check=False, timeout=600, text=True, errors="replace",
            **_no_window())
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    found: list[tuple[float, float]] = []
    begin: float | None = None
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            begin = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end: (-?[\d.]+)", line)
        if m and begin is not None:
            found.append((start + begin, start + float(m.group(1))))
            begin = None
    if begin is not None:  # quiet until the end of the part
        found.append((start + begin, end))
    return [(a, min(b, end)) for a, b in found if min(b, end) - a >= min_len - 1e-6]


def speech_ranges(start: float, end: float, silences: list[tuple[float, float]], *,
                  pad: float = SILENCE_PAD, min_keep: float = 0.1) -> list[tuple[float, float]]:
    """The parts of [start, end] to keep once each pause is cut out, leaving *pad*
    seconds of the pause on both sides so words don't start or stop abruptly."""
    keeps: list[tuple[float, float]] = []
    here = start
    for a, b in sorted(silences):
        a = a + pad if a > start + 0.02 else a  # a pause at the very start / end goes whole
        b = b - pad if b < end - 0.02 else b
        if b - a <= 0.02 or b <= here:  # nothing left of this pause to cut
            continue
        if a - here >= min_keep:
            keeps.append((round(here, 3), round(a, 3)))
        here = max(here, b)
    if end - here >= min_keep:
        keeps.append((round(here, 3), round(end, 3)))
    return keeps or [(start, end)]


def waveform(path: str | Path, buckets: int = 600, rate: int = 2000) -> list[float]:
    """Peak level (0..1) of the audio in *buckets* equal slices of the file."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
         "-f", "s16le", "-"],
        capture_output=True, check=False, timeout=120, **_no_window(),
    )
    if proc.returncode != 0 or not proc.stdout:
        return []
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    n = len(samples)
    if not n:
        return []
    buckets = max(1, min(buckets, n))
    step = n / buckets
    peaks = [
        max(abs(v) for v in samples[int(i * step): max(int((i + 1) * step), int(i * step) + 1)])
        / 32768
        for i in range(buckets)
    ]
    top = max(peaks) or 1.0
    return [p / top for p in peaks]


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _no_window() -> dict:
    """subprocess kwargs that keep a console window from flashing on Windows."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}
