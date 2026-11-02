"""Qt-free **best moment** finder (Trim tab → Best moment…): where in a clip is the
liveliest stretch of a given length? It listens: loudness every `STEP` seconds
(ffmpeg `astats`), scored by how much of each window is clearly above the room
noise — speech, music and cheering score high, a quiet intro scores low."""
from __future__ import annotations

import math
import re
import subprocess

from vidgrab.downloader import find_ffmpeg

STEP = 0.5
FLOOR_DB, TOP_DB = -50.0, -12.0  # quieter than the floor scores 0, as loud as the top 1
ACTIVE_DB = -38.0  # a step above this counts as "something is going on"


def loudness_profile(path: str, start: float, end: float) -> list[float]:
    """RMS level in dB of each `STEP`-second slice of [start, end] of *path*."""
    ffmpeg = find_ffmpeg() or "ffmpeg"
    samples = int(16000 * STEP)
    af = (f"aresample=16000,asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
    proc = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{max(end - start, 0.1):.3f}",
                           "-i", path, "-vn", "-af", af, "-f", "null", "-"],
                          capture_output=True, text=True, check=False, timeout=600)
    levels = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-?inf|nan)", proc.stdout):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        levels.append(v if not math.isnan(v) and v > -200 else -120.0)  # nan / -inf: silence
    return levels


def score(levels: list[float]) -> list[float]:
    """0..1 per slice: loudness, plus a bonus for being clearly active."""
    out = []
    for v in levels:
        loud = min(max((v - FLOOR_DB) / (TOP_DB - FLOOR_DB), 0.0), 1.0)
        out.append(0.7 * loud + (0.3 if v > ACTIVE_DB else 0.0))
    return out


def best_window(levels: list[float], length: float) -> float:
    """Start (seconds into the profile) of the best *length*-second stretch;
    the earliest one wins a tie. A clip shorter than *length* starts at 0."""
    s = score(levels)
    n = max(round(length / STEP), 1)
    if len(s) <= n:
        return 0.0
    run = sum(s[:n])
    best, at = run, 0
    for i in range(1, len(s) - n + 1):
        run += s[i + n - 1] - s[i - 1]
        if run > best + 1e-9:
            best, at = run, i
    return at * STEP


def find_best(path: str, start: float, end: float, length: float) -> tuple[float, float]:
    """(start, end) in the file's own time of the liveliest *length* seconds
    between *start* and *end*."""
    length = min(length, end - start)
    at = best_window(loudness_profile(path, start, end), length)
    return start + at, start + at + length
