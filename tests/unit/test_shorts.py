from __future__ import annotations

import shutil
import subprocess

import pytest

from vidgrab.ai import highlights, shorts
from vidgrab.media import studio

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def test_plan_keeps_a_short_video_whole_and_caps_at_a_minute() -> None:
    assert shorts.plan(12, 30) == (0.0, 12)
    assert shorts.plan(300, 30) == (0.0, 30)
    assert shorts.plan(300, 500) == (0.0, 60.0)  # Shorts stop at 60 s


def test_cues_get_the_highlight_look_in_the_lower_middle() -> None:
    timed = studio.SubtitleCue(0, 2, "hello there", words=[[0, 5, 0.0, 0.5], [6, 11, 0.6, 1.0]])
    plain = studio.SubtitleCue(2, 3, "no timing")
    shorts.style_cues([timed, plain])
    assert timed.animation == "highlight" and plain.animation == "pop"
    assert (timed.x, timed.y) == (0.5, shorts.CAPTION_Y)


@needs_ffmpeg
def test_make_short_finds_the_loud_part_and_renders_vertical(tmp_path) -> None:
    src = tmp_path / "long.mp4"
    # 70 s of picture; sound only from 40 s to 55 s: the best 15 s must sit on it
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=70",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=15", "-filter_complex",
         "[1:a]adelay=40000|40000,apad=whole_dur=70[a]", "-map", "0:v", "-map", "[a]", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
    seen: list[float] = []
    out = shorts.make_short(src, tmp_path / "short.mp4", seconds=15, follow=False, with_captions=False,
                            models_dir=tmp_path, on_progress=lambda _l, p: p is not None and seen.append(p))
    info = studio.probe_media(out)
    assert out.is_file() and 14 <= info["duration"] <= 16
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True,
                           check=True)
    assert probe.stdout.strip() == "1080,1920"
    levels = highlights.loudness_profile(str(out), 0, info["duration"])
    assert sum(v > -40 for v in levels) > 0.8 * len(levels)  # the part with sound, not the quiet start
    assert seen and seen[-1] > 90 and seen == sorted(seen)  # progress runs forward to the end


@needs_ffmpeg
def test_make_short_can_be_cancelled(tmp_path) -> None:
    from vidgrab.core.downloader import DownloadCancelled

    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=5",
                    "-f", "lavfi", "-i", "sine=duration=5", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                    str(src)], check=True)
    with pytest.raises(DownloadCancelled):
        shorts.make_short(src, tmp_path / "x.mp4", follow=False, with_captions=False, models_dir=tmp_path,
                          cancelled=lambda: True, on_progress=lambda *_a: None)
