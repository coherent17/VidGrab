"""Qt-free **beat finder** for *Cut to the beat* (Studio, Music tab).

`detect()` listens to a song (ffmpeg decodes it to 11 kHz mono, numpy does the maths):
the rise in the low / mid spectrum in each ~46 ms frame is the *onset strength*; its
autocorrelation gives the tempo (70-180 BPM) and the best-fitting grid gives the
beat times. A steady beat is assumed, which suits the pop / dance / lo-fi tracks
people cut videos to; a track with a drifting tempo just gets a looser fit.
`snap_durations()` then moves clip boundaries onto those beats."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from vidgrab.downloader import find_ffmpeg

RATE = 11025
HOP = 512  # samples per frame: ~46 ms
WINDOW = 1024
BPM_RANGE = (70.0, 180.0)


@dataclass
class Beats:
    bpm: float
    times: list[float]  # seconds from the start of the part that was analysed


def available() -> bool:
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _decode(path: str, start: float, end: float | None) -> bytes:
    ffmpeg = find_ffmpeg() or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-ss", f"{max(start, 0):.3f}"]
    if end is not None:
        cmd += ["-t", f"{max(end - start, 0.5):.3f}"]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=False, timeout=300)
    return proc.stdout


def onset_strength(samples):
    """Per-frame positive spectral flux (numpy array), 0..1."""
    import numpy as np

    if len(samples) < WINDOW * 4:
        return np.zeros(0)
    n = 1 + (len(samples) - WINDOW) // HOP
    idx = np.arange(WINDOW)[None, :] + HOP * np.arange(n)[:, None]
    frames = samples[idx] * np.hanning(WINDOW)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    lo, hi = 2, int(4000 / (RATE / WINDOW))  # ~40 Hz .. 4 kHz: kick, snare, hats, plucks
    band = np.log1p(30.0 * mag[:, lo:hi])
    flux = np.maximum(band[1:] - band[:-1], 0.0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(9) / 9, mode="same")  # drop the slow level, keep the hits
    flux = np.maximum(flux, 0.0)
    peak = flux.max()
    return flux / peak if peak > 0 else flux


def tempo_and_grid(env, frame_s: float) -> Beats | None:
    """Best (bpm, beat times) for an onset envelope, or None when it has no beat."""
    import numpy as np

    if len(env) < 64 or env.max() <= 0:
        return None
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lo, hi = int(60 / BPM_RANGE[1] / frame_s), int(60 / BPM_RANGE[0] / frame_s)
    hi = min(hi, len(ac) - 1)
    if hi <= lo + 1:
        return None
    lags = np.arange(lo, hi + 1)
    # favour the musical tempo near 120 BPM a little, so half / double time loses ties
    bpm_of = 60.0 / (lags * frame_s)
    weight = np.exp(-0.5 * (np.log2(bpm_of / 120.0) / 0.9) ** 2)
    best_lag = int(lags[np.argmax(ac[lo:hi + 1] * weight)])
    # refine the period with a parabola through the peak
    a, b, c = (ac[best_lag - 1], ac[best_lag], ac[best_lag + 1]) if best_lag + 1 < len(ac) else (0, 1, 0)
    denom = a - 2 * b + c
    period = best_lag + (0.5 * (a - c) / denom if denom else 0.0)
    best_phase, best_score = 0.0, -1.0
    for phase in np.arange(0.0, period, 0.5):
        pos = np.arange(phase, len(env) - 1, period)
        score = float(env[np.round(pos).astype(int)].sum())
        if score > best_score:
            best_phase, best_score = float(phase), score
    best_phase, period = _refine(env, best_phase, period)
    count = int((len(env) - 1 - best_phase) // period) + 1
    times = [round((best_phase + k * period) * frame_s, 3) for k in range(count)]
    return Beats(round(60.0 / (period * frame_s), 1), times)


def _refine(env, phase: float, period: float) -> tuple[float, float]:
    """Fit phase + k * period through the real hit nearest each grid beat (the
    autocorrelation only knows whole frames, which drifts over a minute)."""
    import numpy as np

    for _ in range(3):
        ks, pos = [], []
        half = max(1, int(period * 0.25))
        for k in range(int((len(env) - 1 - phase) // period) + 1):
            centre = round(phase + k * period)
            lo, hi = max(centre - half, 1), min(centre + half + 1, len(env) - 1)
            if hi <= lo:
                continue
            j = lo + int(np.argmax(env[lo:hi]))
            if env[j] < 0.15:
                continue
            a, b, c = env[j - 1], env[j], env[j + 1]
            denom = a - 2 * b + c
            ks.append(k)
            pos.append(j + (0.5 * (a - c) / denom if denom else 0.0))
        if len(ks) < 4:
            break
        slope, intercept = np.polyfit(ks, pos, 1)
        if slope <= 0:
            break
        phase, period = float(intercept), float(slope)
        while phase < 0:
            phase += period
    return phase, period


def detect(path: str, start: float = 0.0, end: float | None = None) -> Beats | None:
    """Beats of *path* between *start* and *end* (None = to the end); times are
    seconds after *start*. None when there is no clear beat."""
    import numpy as np

    raw = _decode(path, start, end)
    samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4")
    return tempo_and_grid(onset_strength(samples), HOP / RATE)


def snap_durations(durations: list[float], beat_times: list[float], *, min_len: float = 0.6) -> list[float]:
    """New clip lengths whose boundaries sit on beats (the nearest beat to each
    old boundary), each at least *min_len* long. The last boundary snaps too."""
    if not durations or len(beat_times) < 2:
        return list(durations)
    out: list[float] = []
    old_edge = 0.0
    new_edge = 0.0
    for d in durations:
        old_edge += d
        later = [b for b in beat_times if b >= new_edge + min_len - 1e-6]
        if not later:
            out.append(d)
            new_edge += d
            continue
        nearest = min(later, key=lambda b: abs(b - old_edge))
        out.append(round(nearest - new_edge, 3))
        new_edge = nearest
    return out
