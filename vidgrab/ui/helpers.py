"""Small formatting and path helpers."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from vidgrab import __version__
from vidgrab.core.downloader import (
    find_ffmpeg,
)
from vidgrab.ui.config import _config_dir


def _dir_size(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _chime_path() -> Path | None:
    """A short two-note chime (generated once) for 'downloads finished'."""
    path = _config_dir() / "chime.wav"
    if path.is_file():
        return path
    try:
        import struct
        import wave

        rate = 44100
        frames = bytearray()
        for freq, length in ((880.0, 0.13), (1318.5, 0.26)):
            n = int(rate * length)
            for i in range(n):
                env = min(1.0, i / 400) * (1 - i / n) ** 2
                value = int(9000 * env * math.sin(2 * math.pi * freq * i / rate))
                frames += struct.pack("<h", value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        return path
    except OSError:
        return None


def _versions() -> list[tuple[str, str]]:
    import platform

    import PySide6
    import yt_dlp

    ff = find_ffmpeg()
    ff_ver = "—"
    if ff:
        try:
            out = subprocess.run([ff, "-version"], capture_output=True, text=True,
                                 timeout=10, check=False).stdout.split("\n", 1)[0]
            ff_ver = out.split(" version ", 1)[-1].split(" ", 1)[0] if out else "—"
        except (OSError, subprocess.SubprocessError):
            pass
    return [
        ("VidGrab", __version__),
        ("yt-dlp", yt_dlp.version.__version__),
        ("ffmpeg", ff_ver),
        ("Qt / PySide6", PySide6.__version__),
        ("Python", platform.python_version()),
    ]


def _thumb_cache_dir() -> Path:
    d = _config_dir() / "cache"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _fmt_duration(seconds: float) -> str:
    """Render a duration in seconds as M:SS or H:MM:SS."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fmt_count(n: int) -> str:
    """Compact count for metric-style numbers: 19393948 -> 19.4M."""
    value = float(n)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(int(value))
