from __future__ import annotations

import shutil
import struct
import wave

import pytest

from vidgrab import beats

np = pytest.importorskip("numpy")


def _click_track(path, bpm: float, seconds: float, offset: float = 0.23) -> list[float]:
    """A kick-like thump on every beat over a little noise; returns the true beat times."""
    rate = 22050
    rng = np.random.default_rng(1)
    sig = rng.normal(0, 0.01, int(rate * seconds))
    period = 60.0 / bpm
    truth = []
    t = offset
    while t < seconds - 0.2:
        truth.append(round(t, 3))
        n = int(rate * 0.08)
        i = int(t * rate)
        tt = np.arange(n) / rate
        sig[i:i + n] += (np.sin(2 * np.pi * 70 * tt) * np.exp(-tt * 45))[: len(sig) - i] * 0.9
        t += period
    pcm = struct.pack(f"<{len(sig)}h", *(np.clip(sig, -1, 1) * 32000).astype(int))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return truth


@pytest.mark.skipif(not (shutil.which("ffmpeg")), reason="needs ffmpeg")
@pytest.mark.parametrize("bpm", [100, 128])
def test_detects_the_tempo_and_puts_beats_on_the_hits(tmp_path, bpm) -> None:
    truth = _click_track(tmp_path / "k.wav", bpm, 24)
    found = beats.detect(str(tmp_path / "k.wav"))
    assert found is not None and abs(found.bpm - bpm) < 2.5
    # every found beat lies within 60 ms of a real hit
    off = [min(abs(b - t) for t in truth) for b in found.times[:40]]
    assert sum(o < 0.06 for o in off) >= 0.9 * len(off)


def test_silence_has_no_beat() -> None:
    assert beats.tempo_and_grid(np.zeros(500), 0.046) is None
    assert beats.onset_strength(np.zeros(100, dtype="float32")).size == 0


def test_boundaries_move_onto_beats_and_clips_keep_a_minimum_length() -> None:
    grid = [round(0.5 * k, 3) for k in range(41)]  # a beat every half second
    out = beats.snap_durations([2.2, 3.1, 1.4], grid)
    edges = np.cumsum(out)
    assert all(abs(e / 0.5 - round(e / 0.5)) < 1e-6 for e in edges)
    assert all(d >= 0.6 for d in out) and abs(edges[0] - 2.0) < 0.51
    assert beats.snap_durations([1.0], []) == [1.0]  # no beats: nothing changes
    tight = beats.snap_durations([0.7, 0.7, 0.7], grid, min_len=0.6)
    assert all(d >= 0.6 for d in tight)
