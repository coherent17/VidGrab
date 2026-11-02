from __future__ import annotations

import shutil
import subprocess

import pytest

from vidgrab import highlights as hl


def test_best_window_picks_the_loud_stretch() -> None:
    levels = [-60.0] * 20 + [-20.0] * 12 + [-60.0] * 20
    assert hl.best_window(levels, 6) == 10.0  # slice 20 = 10 s; the earliest full overlap
    assert hl.best_window(levels, 100) == 0.0  # longer than the clip
    assert hl.best_window([-30.0] * 10, 2) == 0.0  # all alike: the start


def test_quiet_and_dead_audio_scores_low() -> None:
    assert max(hl.score([-120.0, -60.0])) == 0.0 and hl.score([-12.0])[0] == 1.0


@pytest.mark.skipif(not (shutil.which("ffmpeg")), reason="ffmpeg not on PATH")
def test_finds_the_loud_part_of_a_real_file(tmp_path) -> None:
    p = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,8,14),0.5*sin(2*PI*300*t),0.002*sin(2*PI*50*t))':s=16000:d=22",
                    str(p)], check=True)
    a, b = hl.find_best(str(p), 0, 22, 5)
    assert 7.5 <= a <= 9.5 and abs((b - a) - 5) < 1e-6
