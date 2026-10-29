"""Tests for studio.py — SRT round-trips, command building, real renders."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidgrab.studio import (
    BackgroundMusic,
    Clip,
    SubtitleCue,
    SubtitleStyle,
    _ResolvedClip,
    build_audio_command,
    build_video_command,
    compose_audio,
    compose_video,
    format_ass,
    format_srt,
    parse_srt,
    parse_timecode,
    probe_media,
    unique_path,
)

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _clip(name: str, dur: float, *, video: bool = True, audio: bool = True,
          start: float = 0.0, w: int = 640, h: int = 360) -> _ResolvedClip:
    return _ResolvedClip(Path(name), start, dur, video, audio, w, h)


def test_srt_round_trip() -> None:
    cues = [SubtitleCue(61.5, 63.25, "第二句"), SubtitleCue(0.5, 2, "Hello\nworld")]
    text = format_srt(cues)
    assert text.startswith("1\n00:00:00,500 --> 00:00:02,000\nHello\nworld\n")
    assert "00:01:01,500 --> 00:01:03,250" in text
    back = parse_srt(text)
    assert [(c.start, c.end, c.text) for c in back] == [
        (0.5, 2.0, "Hello\nworld"), (61.5, 63.25, "第二句"),
    ]


def test_parse_srt_is_lenient() -> None:
    raw = "﻿1\r\n00:00:01.5 --> 00:00:03,0\r\nA\r\n\r\n\r\n00:00:04,000 --> 00:00:05,000\r\nB\r\n"
    cues = parse_srt(raw)
    assert [(c.start, c.text) for c in cues] == [(1.5, "A"), (4.0, "B")]


def test_format_ass_positions_and_scaling() -> None:
    style = SubtitleStyle(size=24, color="yellow", position="top")
    text = format_ass(
        [SubtitleCue(1.5, 3, "pinned {x}\n第二行", 0.25, 0.1), SubtitleCue(0, 1, "default")],
        1280, 720, style,
    )
    assert "PlayResX: 1280" in text and "PlayResY: 720" in text
    # 24 at the 288-line reference scales to 60 at 720p; yellow; top-centre (8)
    assert "Style: Default,Noto Sans CJK TC,60,&H0000E5FF," in text
    assert ",8,70,70,70,1" in text
    lines = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
    assert lines[0].endswith(",,default")  # sorted by start, no override
    assert "0:00:01.50,0:00:03.00" in lines[1]
    assert lines[1].endswith("{\\an5\\pos(320,72)}pinned (x)\\N第二行")


def test_format_ass_background_box() -> None:
    style = SubtitleStyle(color="#00FF00", background="#000000", bg_opacity=0.6)
    text = format_ass([SubtitleCue(0, 1, "x")], 1280, 720, style)
    line = next(ln for ln in text.splitlines() if ln.startswith("Style:"))
    fields = line.split(",")
    # text colour is &HAABBGGRR; opaque-box mode (BorderStyle 3) draws the
    # box in OutlineColour, 60 % opacity -> alpha 0x66
    assert fields[3] == "&H0000FF00"
    assert fields[5] == "&H66000000"
    assert fields[15] == "3" and int(fields[16]) > 0 and fields[17] == "0"
    plain = format_ass([SubtitleCue(0, 1, "x")], 1280, 720, SubtitleStyle())
    assert next(ln for ln in plain.splitlines() if ln.startswith("Style:")).split(",")[15] == "1"


def test_format_ass_anchor_fade_bold_font() -> None:
    style = SubtitleStyle(bold=True, fade=0.4, font="DejaVu Sans")
    text = format_ass([SubtitleCue(0, 0.5, "short", 0.05, 0.95, 1),
                       SubtitleCue(1, 5, "long", 0.95, 0.05, 9)], 1000, 500, style)
    fields = next(ln for ln in text.splitlines() if ln.startswith("Style:")).split(",")
    assert fields[1] == "DejaVu Sans" and fields[7] == "-1"  # font + bold
    events = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
    # bottom-left anchor; fade capped at half of a 0.5 s line
    assert events[0].endswith("{\\an1\\pos(50,475)\\fad(250,250)}short")
    assert events[1].endswith("{\\an9\\pos(950,25)\\fad(400,400)}long")


def test_system_fonts_maps_families_to_files() -> None:
    from vidgrab.studio import system_fonts

    for family, path in system_fonts().items():
        assert family and path.is_file()


def test_render_quality_presets() -> None:
    clips = [_clip("a.mp4", 2)]
    fast, _ = build_video_command("ffmpeg", clips, Path("o.mp4"), quality="fast")
    high, _ = build_video_command("ffmpeg", clips, Path("o.mp4"), quality="high")
    assert fast[fast.index("-preset") + 1] == "veryfast" and fast[fast.index("-crf") + 1] == "23"
    assert high[high.index("-preset") + 1] == "slow" and high[high.index("-crf") + 1] == "17"


def test_parse_timecode() -> None:
    assert parse_timecode("90") == 90
    assert parse_timecode("1:30") == 90
    assert parse_timecode("1:02:03.5") == 3723.5
    assert parse_timecode("") is None
    assert parse_timecode("abc") is None


def test_unique_path(tmp_path: Path) -> None:
    p = tmp_path / "out.mp4"
    assert unique_path(p) == p
    p.touch()
    assert unique_path(p).name == "out (2).mp4"


def test_audio_command_concat_vs_crossfade() -> None:
    clips = [_clip("a.mp3", 10, video=False), _clip("b.mp3", 6, video=False, start=5)]
    cmd, total = build_audio_command("ffmpeg", clips, Path("o.mp3"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=0:a=1" in graph and total == 16
    assert cmd[cmd.index("-ss") + 1] == "5.000"

    cmd, total = build_audio_command("ffmpeg", clips, Path("o.m4a"), crossfade=2)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "acrossfade=d=2.000" in graph and total == 14
    assert "aac" in cmd

    # crossfade is clamped to half the shortest clip
    cmd, _ = build_audio_command("ffmpeg", clips, Path("o.mp3"), crossfade=9)
    assert "acrossfade=d=3.000" in cmd[cmd.index("-filter_complex") + 1]


def test_video_command_fills_silence_and_mixes_music() -> None:
    clips = [_clip("a.mp4", 4), _clip("b.mp4", 3, audio=False, w=480, h=640)]
    cmd, total = build_video_command(
        "ffmpeg", clips, Path("o.mp4"), resolution="720p",
        subtitles_file="subs.ass", fonts_dir="fonts",
        music=BackgroundMusic("m.mp3", volume=0.5),
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert total == 7
    assert "anullsrc" in " ".join(cmd)
    assert "[2:a]" in graph  # silent stand-in feeds clip 2's audio
    assert "scale=1280:720" in graph
    assert "subtitles=filename=subs.ass:fontsdir=fonts" in graph
    assert "amix=inputs=2" in graph and "volume=0.500" in graph
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert cmd[-1] == "o.mp4"


def test_video_command_auto_resolution_uses_first_clip() -> None:
    cmd, _ = build_video_command("ffmpeg", [_clip("a.mp4", 1, w=3840, h=2160)], Path("o.mp4"))
    assert "scale=1920:1080" in cmd[cmd.index("-filter_complex") + 1]


def _make(path: Path, *args: str) -> Path:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args, str(path)], check=True)
    return path


@requires_ffmpeg
def test_compose_video_end_to_end(tmp_path: Path) -> None:
    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-shortest")
    b = _make(tmp_path / "b.mp4", "-f", "lavfi", "-i", "testsrc2=size=240x320:rate=30", "-t", "2")
    m = _make(tmp_path / "m.mp3", "-f", "lavfi", "-i", "sine=frequency=660", "-t", "1")
    progress: list[float] = []
    out = compose_video(
        [Clip(str(a), None, "1.5"), Clip(str(b))],
        tmp_path / "out" / "montage.mp4",
        resolution="480p",
        subtitles=[SubtitleCue(0.2, 1.0, "你好")],
        music=BackgroundMusic(str(m)),
        on_progress=lambda _m, p: progress.append(p) if p is not None else None,
    )
    info = probe_media(out)
    assert info["has_video"] and info["has_audio"]
    assert (info["width"], info["height"]) == (854, 480)
    assert abs(info["duration"] - 3.5) < 0.3
    assert progress and progress[-1] == 100.0


@requires_ffmpeg
def test_compose_audio_end_to_end(tmp_path: Path) -> None:
    a = _make(tmp_path / "a.mp3", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4")
    b = _make(tmp_path / "b.wav", "-f", "lavfi", "-i", "sine=frequency=550", "-t", "3")
    out = compose_audio([Clip(str(a), "1"), Clip(str(b))], tmp_path / "medley.mp3", crossfade=1)
    info = probe_media(out)
    assert info["has_audio"] and not info["has_video"]
    assert abs(info["duration"] - 5.0) < 0.3


@requires_ffmpeg
def test_compose_rejects_bad_input(tmp_path: Path) -> None:
    song = _make(tmp_path / "s.mp3", "-f", "lavfi", "-i", "sine", "-t", "1")
    with pytest.raises(RuntimeError, match="no video stream"):
        compose_video([Clip(str(song))], tmp_path / "o.mp4")
    with pytest.raises(RuntimeError, match="past the end"):
        compose_audio([Clip(str(song), "5")], tmp_path / "o.mp3")
    with pytest.raises(RuntimeError, match="at least one clip"):
        compose_audio([], tmp_path / "o.mp3")
