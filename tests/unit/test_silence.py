import shutil
import subprocess

import pytest

from vidgrab.media import studio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def test_speech_ranges_cut_the_middle_of_each_pause():
    keeps = studio.speech_ranges(0, 10, [(2, 4), (6, 9)], pad=0.1)
    assert keeps == [(0, 2.1), (3.9, 6.1), (8.9, 10)]


def test_speech_ranges_without_pauses_keep_everything():
    assert studio.speech_ranges(1, 5, []) == [(1, 5)]


def test_speech_ranges_ignore_a_pause_too_short_to_cut():
    assert studio.speech_ranges(0, 5, [(2, 2.2)], pad=0.12) == [(0, 5)]


def test_speech_ranges_pause_at_the_edges():
    keeps = studio.speech_ranges(0, 6, [(0, 2), (4, 6)], pad=0.1)
    assert keeps == [(1.9, 4.1)]


def test_finds_the_quiet_part_of_a_real_file(tmp_path):
    # 2 s tone, 2 s silence, 2 s tone
    wav = tmp_path / "a.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2", "-f", "lavfi", "-i",
         "sine=f=440:d=2", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(wav)],
        check=True)
    found = studio.detect_silences(wav, 0, 6)
    assert len(found) == 1 and abs(found[0][0] - 2) < 0.2 and abs(found[0][1] - 4) < 0.2
    # a part that starts inside the file still reports file time
    part = studio.detect_silences(wav, 1, 6)
    assert len(part) == 1 and abs(part[0][0] - 2) < 0.2
    # nothing quiet in a plain tone, and a file without sound gives nothing
    assert studio.detect_silences(wav, 0, 1.8) == []
    assert studio.detect_silences(tmp_path / "missing.wav", 0, 5) == []
