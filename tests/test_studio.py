"""Tests for studio.py — SRT round-trips, command building, real renders."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from vidgrab import studio
from vidgrab.studio import (
    BackgroundMusic,
    Clip,
    ImageOverlay,
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
    transition_overlaps,
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


def test_transition_overlaps_are_clamped() -> None:
    durs = [4.0, 1.0, 6.0, 6.0]
    trans = [("fade", 1.0), ("fade", 2.0), ("none", 1.0), ("wipeleft", 1.5)]
    # first clip never overlaps; a transition takes at most half a neighbour; cuts are 0
    assert transition_overlaps(durs, trans) == [0.0, 0.5, 0.0, 1.5]


def test_video_command_transitions_and_cuts() -> None:
    clips = [_clip("a.mp4", 4), _clip("b.mp4", 3), _clip("c.mp4", 5)]
    clips[1].transition, clips[1].transition_duration = "fadeblack", 1.0
    clips[2].transition, clips[2].transition_duration = "none", 1.0
    cmd, total = build_video_command("ffmpeg", clips, Path("o.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert total == 4 + 3 + 5 - 1.0
    # clip b starts 1 s before a ends; c is cut on straight after b
    assert "[v0][v1]xfade=transition=fadeblack:duration=1.000:offset=3.000[vx1]" in graph
    assert "[a0][a1]acrossfade=d=1.000" in graph
    assert "acrossfade=d=1.000:c1=tri:c2=tri,aformat=sample_fmts=fltp" in graph
    assert graph.endswith("asetnsamples=n=1024:p=0[aenc]") and cmd[cmd.index("[vc]") + 2] == "[aenc]"
    assert "[vx1][v2]concat=n=2:v=1:a=0,fps=30,settb=AVTB[vc]" in graph
    plain, _ = build_video_command("ffmpeg", [_clip("a.mp4", 4), _clip("b.mp4", 3)], Path("o.mp4"))
    assert "concat=n=2:v=1:a=1[vc][ac]" in plain[plain.index("-filter_complex") + 1]


def test_video_command_framing() -> None:
    fit = _clip("a.mp4", 2)
    fill = _clip("b.mp4", 2)
    fill.fit, fill.zoom, fill.pan_x = "fill", 1.5, 0.0
    cmd, _ = build_video_command("ffmpeg", [fit, fill], Path("o.mp4"), resolution="vertical")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v:0]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920" in graph
    assert ("[1:v:0]scale=1620:2880:force_original_aspect_ratio=increase" in graph
            and "x='(iw-ow)*0.0000'" in graph)


@requires_ffmpeg
def test_compose_video_with_transitions_and_fill(tmp_path: Path) -> None:
    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-shortest")
    b = _make(tmp_path / "b.mp4", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "3")
    c = _make(tmp_path / "c.mp4", "-f", "lavfi", "-i", "smptebars=size=320x240:rate=25", "-t", "2")
    out = compose_video(
        [Clip(str(a)),
         Clip(str(b), transition="fade", transition_duration=1.0, fit="fill", pan_x=0.2),
         Clip(str(c), transition="none"),
         Clip(str(a), transition="slideleft", transition_duration=0.5, zoom=1.4)],
        tmp_path / "t.mp4", resolution="square",
        subtitles=[SubtitleCue(0.5, 6.0, "轉場")],
    )
    info = probe_media(out)
    assert (info["width"], info["height"]) == (1080, 1080)
    assert abs(info["duration"] - (3 + 3 + 2 + 3 - 1.0 - 0.5)) < 0.3


def test_clip_volume_and_mute_in_commands() -> None:
    loud, muted, plain = _clip("a.mp4", 2), _clip("b.mp4", 2), _clip("c.mp4", 2)
    loud.gain, muted.gain = 1.5, 0.0
    cmd, _ = build_video_command("ffmpeg", [loud, muted, plain], Path("o.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    a0, a1, a2 = (part for part in graph.split(";") if part.endswith(("[a0]", "[a1]", "[a2]")))
    assert a0.endswith("volume=1.500[a0]") and a1.endswith("volume=0.000[a1]")
    assert "volume=" not in a2
    audio, _ = build_audio_command("ffmpeg", [muted, plain], Path("o.mp3"))
    assert "volume=0.000[a0]" in audio[audio.index("-filter_complex") + 1]
    assert Clip("x.mp4", volume=0.5, muted=True).gain() == 0.0


@requires_ffmpeg
def test_compose_video_mutes_a_clip(tmp_path: Path) -> None:
    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-shortest")
    out = compose_video([Clip(str(a)), Clip(str(a), muted=True)], tmp_path / "m.mp4")
    levels = []
    for start in (0.5, 2.5):
        proc = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", str(start), "-t", "1", "-i", str(out),
             "-af", "volumedetect", "-vn", "-f", "null", "-"],
            capture_output=True, text=True, check=True)
        line = next(x for x in proc.stderr.splitlines() if "max_volume" in x)
        levels.append(float(line.split("max_volume:")[1].split("dB")[0]))
    assert levels[0] > -30 and levels[1] < -80  # first clip audible, second silent


@requires_ffmpeg
def test_render_error_includes_ffmpeg_message(tmp_path: Path) -> None:
    from vidgrab.studio import _run_with_progress

    with pytest.raises(RuntimeError) as err:
        _run_with_progress(["ffmpeg", "-v", "error", "-i", str(tmp_path / "missing.mp4"),
                            str(tmp_path / "o.mp4")], 1.0, label="x", on_progress=None,
                           on_log=None, translate=None)
    assert "missing.mp4" in str(err.value)


def test_music_bed_trim_loop_and_offset_in_command() -> None:
    clips = [_clip("a.mp4", 10)]
    music = BackgroundMusic("m.mp3", start=12.0, end=20.0, offset=2.5, length=180.0)
    cmd, _ = build_video_command("ffmpeg", clips, Path("o.mp4"), music=music)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "-stream_loop" not in cmd  # a trimmed part loops inside the graph
    assert "atrim=start=12.000:end=20.000,asetpts=PTS-STARTPTS" in graph
    assert "aloop=loop=-1:size=384000" in graph  # 8 s x 48 kHz
    assert "atrim=0:7.500,asetpts=PTS-STARTPTS,adelay=2500:all=1,asetpts=N/SR/TB" in graph
    whole, _ = build_video_command("ffmpeg", clips, Path("o.mp4"), music=BackgroundMusic("m.mp3"))
    assert "-stream_loop" in whole and "atrim=start" not in whole[whole.index("-filter_complex") + 1]


def _peak_db(path: Path, start: float, length: float) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path),
         "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    line = next(x for x in proc.stderr.splitlines() if "max_volume" in x)
    return float(line.split("max_volume:")[1].split("dB")[0])


@requires_ffmpeg
def test_compose_video_music_comes_in_at_offset(tmp_path: Path) -> None:
    video = _make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                  "-t", "6")
    # a song that is silent for 3 s, then a tone: cut to the tone, bring it in at 2 s
    song = _make(tmp_path / "s.wav", "-f", "lavfi", "-i",
                 "aevalsrc='if(lt(t,3),0,0.5*sin(2*PI*440*t))':s=48000:d=10")
    out = compose_video([Clip(str(video))], tmp_path / "o.mp4",
                        music=BackgroundMusic(str(song), volume=1.0, start=3.0, end=6.0,
                                              offset=2.0, fade_out=False))
    assert abs(probe_media(out)["duration"] - 6.0) < 0.3
    assert _peak_db(out, 0.2, 1.5) < -60  # before the offset: silence
    assert _peak_db(out, 2.5, 1.5) > -20  # the cut-in part of the song (the tone)


@requires_ffmpeg
def test_compose_video_two_songs_in_sequence(tmp_path: Path) -> None:
    video = _make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                  "-t", "6")
    low = _make(tmp_path / "a.wav", "-f", "lavfi", "-i", "sine=frequency=300", "-t", "10")
    high = _make(tmp_path / "b.wav", "-f", "lavfi", "-i", "sine=frequency=3000", "-t", "10")
    out = compose_video(
        [Clip(str(video))], tmp_path / "o.mp4",
        music=[BackgroundMusic(str(low), volume=1.0, end=3.0, loop=False, fade_out=False),
               BackgroundMusic(str(high), volume=1.0, offset=3.0, fade_out=False)])
    assert abs(probe_media(out)["duration"] - 6.0) < 0.3

    def dominant(start: float) -> str:
        """Which song is playing: compare energy below / above 1 kHz."""
        lo = _peak_db_filtered(out, start, "lowpass=f=1000")
        hi = _peak_db_filtered(out, start, "highpass=f=1000")
        return "low" if lo > hi else "high"

    assert dominant(1.0) == "low" and dominant(4.5) == "high"


def _peak_db_filtered(path: Path, start: float, filt: str) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-t", "1", "-i", str(path),
         "-af", f"{filt},volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    line = next(x for x in proc.stderr.splitlines() if "max_volume" in x)
    return float(line.split("max_volume:")[1].split("dB")[0])


def test_video_command_image_overlays() -> None:
    clips = [_clip("a.mp4", 10, w=1280, h=720)]
    imgs = [ImageOverlay("logo.png", 1.0, 4.0, x=0.85, y=0.15, width=0.2, opacity=0.8, fade=0.5),
            ImageOverlay("b.png", 5.0, 30.0)]
    cmd, _ = build_video_command("ffmpeg", clips, Path("o.mp4"), images=imgs,
                                 subtitles_file="subs.ass")
    graph = cmd[cmd.index("-filter_complex") + 1]
    # looped stills, cut to what the montage needs (the second ends with the video)
    assert cmd[cmd.index("logo.png") - 7:cmd.index("logo.png") + 1] == [
        "-loop", "1", "-framerate", "30", "-t", "4.000", "-i", "logo.png"]
    assert "-t" == cmd[cmd.index("b.png") - 3] and cmd[cmd.index("b.png") - 2] == "10.000"
    assert "format=rgba,scale=256:-2,colorchannelmixer=aa=0.800" in graph
    assert "fade=t=in:st=1.000:d=0.500:alpha=1,fade=t=out:st=3.500:d=0.500:alpha=1" in graph
    assert "[vc][im0]overlay=x='main_w*0.8500-overlay_w/2'" in graph
    assert "enable='between(t,1.000,4.000)'" in graph
    assert "[vo0][im1]overlay" in graph and "[vo1]subtitles=filename=subs.ass" in graph


@requires_ffmpeg
def test_compose_video_with_an_image(tmp_path: Path) -> None:
    video = _make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25",
                  "-t", "4")
    red = _make(tmp_path / "red.png", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1")
    out = compose_video([Clip(str(video))], tmp_path / "o.mp4",
                        images=[ImageOverlay(str(red), 1.0, 3.0, x=0.5, y=0.5, width=0.5)])

    def centre_red(t: float) -> int:
        png = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1",
             "-vf", "crop=8:8:156:116,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True).stdout
        return png[0]

    assert centre_red(0.5) < 40 and centre_red(2.0) > 180 and centre_red(3.5) < 40


def test_image_rotation_in_command() -> None:
    clips = [_clip("a.mp4", 5, w=1280, h=720)]
    cmd, _ = build_video_command("ffmpeg", clips, Path("o.mp4"),
                                 images=[ImageOverlay("i.png", 0, 5, rotation=-30.0)])
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "rotate=a=330.000*PI/180:c=none:ow=rotw(330.000*PI/180):oh=roth(330.000*PI/180)" in graph
    plain, _ = build_video_command("ffmpeg", clips, Path("o.mp4"),
                                   images=[ImageOverlay("i.png", 0, 5)])
    assert "rotate=" not in plain[plain.index("-filter_complex") + 1]


@requires_ffmpeg
def test_compose_video_rotated_image(tmp_path: Path) -> None:
    video = _make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "color=c=black:s=320x320:r=25",
                  "-t", "2")
    bar = _make(tmp_path / "bar.png", "-f", "lavfi", "-i", "color=c=red:s=200x20", "-frames:v", "1")
    out = compose_video([Clip(str(video))], tmp_path / "o.mp4",
                        images=[ImageOverlay(str(bar), 0.0, 2.0, width=0.6, rotation=90.0)])

    def red_at(x: int, y: int) -> int:
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1",
             "-vf", f"crop=4:4:{x}:{y},scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True).stdout[0]

    # a horizontal bar turned 90 degrees is vertical: red above the centre, not beside it
    assert red_at(158, 70) > 150 and red_at(60, 158) < 60


def test_format_ass_per_line_look_and_animations() -> None:
    style = SubtitleStyle(size=24, color="#FFFFFF", background="#000000")
    cues = [SubtitleCue(0, 2, "same"), SubtitleCue(2, 4, "red", look={"color": "#FF0000"}),
            SubtitleCue(4, 6, "again red", look={"color": "#FF0000"}),
            SubtitleCue(6, 8, "pop", animation="pop"), SubtitleCue(8, 10, "ab", animation="typewriter"),
            SubtitleCue(10, 12, "up", animation="slide"), SubtitleCue(12, 14, "k", animation="karaoke")]
    text = format_ass(cues, 1280, 720, style)
    styles = [ln for ln in text.splitlines() if ln.startswith("Style: ")]
    assert [ln.split(",")[0] for ln in styles] == ["Style: Default", "Style: Look1"]  # one per look
    assert "&H000000FF" in styles[1].split(",")[3]  # red, as ASS BGR
    dialogue = [ln for ln in text.splitlines() if ln.startswith("Dialogue")]
    events = {key: next(ln for ln in dialogue if ln.endswith(key))
              for key in ("same", "red", "again red", "pop", "up")}
    assert ",Look1," in events["red"] and ",Look1," in events["again red"] and ",Default," in events["same"]
    assert "\\fscx40\\fscy40\\t(0,250,\\fscx100\\fscy100)" in events["pop"]
    tw = next(ln for ln in text.splitlines() if "Dialogue" in ln and "\\alpha&HFF&" in ln)
    assert tw.count("\\alpha&HFF&") == 2  # one reveal per character
    # revealed back to the box's own see-through alpha, not \alpha&H00& (an opaque box)
    assert "\\alpha&H00&" not in tw and tw.count("\\3a&H66&") == 2
    assert "\\move(640,686,640,650,0,300)" in events["up"]  # rises 36 px into its usual place
    assert "{\\kf" in next(ln for ln in text.splitlines() if "\\kf" in ln)


def _text_pixels(path: Path, t: float, level: int = 150) -> tuple[int, float, int]:
    """(bright pixels, their mean row, how many are yellow) in one frame."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    w, h = 320, 180
    count, rows, yellow = 0, 0, 0
    for i in range(0, w * h * 3, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if r > level and g > level:
            count += 1
            rows += (i // 3) // w
            if b < 100:
                yellow += 1
    return count, rows / max(1, count), yellow


@requires_ffmpeg
def test_compose_video_text_animations(tmp_path: Path) -> None:
    video = _make(tmp_path / "v.mp4", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25", "-t", "8")
    style = SubtitleStyle(size=40, color="#FFFFFF", outline=False)
    out = compose_video([Clip(str(video))], tmp_path / "o.mp4", subtitle_style=style, subtitles=[
        SubtitleCue(0.0, 2.0, "POP", animation="pop"),
        SubtitleCue(2.0, 4.0, "WRITE", animation="typewriter"),
        SubtitleCue(4.0, 6.0, "UP", animation="slide"),
        SubtitleCue(6.0, 8.0, "SING", look={"color": "#FFE500"}, animation="karaoke"),
    ])
    pop_early, pop_late = _text_pixels(out, 0.05)[0], _text_pixels(out, 1.0)[0]
    assert pop_early < pop_late * 0.6  # still scaling up
    tw = [_text_pixels(out, 2.0 + d)[0] for d in (0.15, 0.6, 1.5)]
    assert tw[0] < tw[1] < tw[2]  # letters appear one after another
    slide_early, slide_late = _text_pixels(out, 4.12, 40)[1], _text_pixels(out, 5.0, 40)[1]
    assert slide_early > slide_late  # comes up from lower down
    k_early, k_late = _text_pixels(out, 6.2)[2], _text_pixels(out, 7.6)[2]
    assert k_early < k_late  # the yellow (this line's own colour) sweeps across


def test_speed_in_commands() -> None:
    from vidgrab.studio import _atempo

    assert _atempo(2.0) == "atempo=2" and _atempo(0.25) == "atempo=0.5,atempo=0.5"
    assert _atempo(4.0) == "atempo=2,atempo=2" and _atempo(1.5) == "atempo=1.5"
    fast, slow = _clip("a.mp4", 4), _clip("b.mp4", 2)
    fast.speed, slow.speed = 2.0, 0.5
    cmd, total = build_video_command("ffmpeg", [fast, slow], Path("o.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert total == 4 / 2 + 2 / 0.5  # 2 s + 4 s in the output
    assert "setsar=1,setpts=(PTS-STARTPTS)/2,fps=30" in graph
    assert "atempo=2[a0]" in graph and "atempo=0.5[a1]" in graph


@requires_ffmpeg
def test_compose_video_speed_and_export_formats(tmp_path: Path) -> None:
    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4", "-shortest")
    out = compose_video([Clip(str(a), speed=2.0), Clip(str(a), "0", "1", speed=0.25)],
                        tmp_path / "o.mp4")
    info = probe_media(out)
    assert abs(info["duration"] - (2.0 + 4.0)) < 0.3  # 4 s at 2x + 1 s at 0.25x
    gif = compose_video([Clip(str(a), "0", "1")], tmp_path / "o.gif", gif_width=200)
    g = probe_media(gif)
    assert gif.read_bytes()[:6] == b"GIF89a" and g["width"] == 200 and not g["has_audio"]
    mp3 = compose_video([Clip(str(a), "0", "2")], tmp_path / "o.mp3")
    m = probe_media(mp3)
    assert m["has_audio"] and not m["has_video"] and abs(m["duration"] - 2.0) < 0.2


def test_video_command_uses_the_chosen_encoder() -> None:
    from vidgrab.gpu import CANDIDATES

    qsv = next(e for e in CANDIDATES if e.key == "qsv")
    cmd, _ = build_video_command("ffmpeg", [_clip("a.mp4", 4)], Path("o.mp4"), encoder=qsv,
                                 quality="high")
    assert cmd[cmd.index("-c:v") + 1] == "h264_qsv" and "libx264" not in cmd
    assert cmd[cmd.index("-global_quality") + 1] == "17"
    cpu, _ = build_video_command("ffmpeg", [_clip("a.mp4", 4)], Path("o.mp4"))
    assert cpu[cpu.index("-c:v") + 1] == "libx264" and "-crf" in cpu


@requires_ffmpeg
def test_compose_video_hardware_encoder_falls_back_to_the_cpu(tmp_path: Path, monkeypatch) -> None:
    from vidgrab import studio
    from vidgrab.gpu import HwEncoder

    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-shortest")
    asked: list[str] = []
    # a card whose driver doesn't answer: ffmpeg refuses the (unknown) encoder mid-render
    monkeypatch.setattr(studio, "detect_encoder",
                        lambda ffmpeg: asked.append(ffmpeg) or HwEncoder("fake", "h264_nope", "Fake GPU"))
    log: list[str] = []
    out = compose_video([Clip(str(a))], tmp_path / "gpu.mp4", hardware=True, on_log=log.append)
    assert probe_media(out)["has_video"] and abs(probe_media(out)["duration"] - 2.0) < 0.3
    assert any("Encoding on the graphics card (Fake GPU)" in line for line in log)
    assert any("rendering on the CPU instead" in line for line in log)
    # the switch off: the card is not even asked about
    asked.clear()
    cpu = compose_video([Clip(str(a))], tmp_path / "cpu.mp4", hardware=False)
    assert probe_media(cpu)["has_video"] and asked == []


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in ffmpeg is a shell script")
def test_a_render_that_stops_answering_is_killed_not_waited_for(tmp_path: Path) -> None:
    import time

    from vidgrab.studio import _run_with_progress

    fake = tmp_path / "fake_ffmpeg"
    fake.write_text("#!/bin/sh\necho out_time_us=1000\nexec sleep 60\n")  # one line of progress, then silence
    fake.chmod(0o755)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="stopped responding"):
        _run_with_progress([str(fake)], 10.0, label="x", on_progress=None, on_log=None,
                           translate=None, stall_s=1.5)
    assert time.monotonic() - t0 < 15  # not the 60 s the "driver" would have taken


@requires_ffmpeg
def test_only_the_graphics_card_attempt_has_a_stall_limit(tmp_path: Path, monkeypatch) -> None:
    from vidgrab import studio
    from vidgrab.gpu import HwEncoder

    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-shortest")
    monkeypatch.setattr(studio, "detect_encoder", lambda ffmpeg: HwEncoder("fake", "h264_nope", "Fake GPU"))
    seen: list[tuple[str, float | None]] = []

    def run(cmd, total, **kw):
        seen.append((cmd[cmd.index("-c:v") + 1], kw.get("stall_s")))
        if len(seen) == 1:  # the card hangs and is given up on
            raise RuntimeError("ffmpeg stopped responding (no progress for 120 s).")

    monkeypatch.setattr(studio, "_run_with_progress", run)
    log: list[str] = []
    compose_video([Clip(str(a))], tmp_path / "o.mp4", hardware=True, on_log=log.append)
    assert seen == [("h264_nope", studio.HW_STALL_S), ("libx264", None)]
    assert any("rendering on the CPU instead" in line and "stopped responding" in line for line in log)


def test_subtitle_size_follows_the_shorter_side_of_the_frame() -> None:
    from vidgrab.studio import subtitle_scale

    assert subtitle_scale(1920, 1080) == subtitle_scale(1080, 1920) == subtitle_scale(1080, 1080)
    assert subtitle_scale(1280, 720) == 720 / 288  # landscape is unchanged
    # a Shorts frame gets the text size a 1080p landscape video gets, not twice that
    style = SubtitleStyle(size=24)
    wide = format_ass([SubtitleCue(0, 2, "字幕")], 1920, 1080, style)
    tall = format_ass([SubtitleCue(0, 2, "字幕")], 1080, 1920, style)
    size = lambda text: next(ln for ln in text.splitlines() if ln.startswith("Style: Default")).split(",")[2]
    assert size(wide) == size(tall) == "90"
    assert "WrapStyle: 2" in tall


@requires_ffmpeg
def test_a_long_caption_wraps_inside_a_vertical_frame(tmp_path: Path) -> None:
    import numpy as np

    a = _make(tmp_path / "a.mp4", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25",
              "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-shortest")
    text = "這是一段很長的字幕，用來確認在直式影片裡會自動換行而不是超出畫面"
    out = compose_video([Clip(str(a), fit="fill")], tmp_path / "v.mp4", resolution="vertical",
                        subtitles=[SubtitleCue(0, 2, text)])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(1920, 1080)
    bright = frame > 200
    cols = np.flatnonzero(bright.any(axis=0))
    rows = np.flatnonzero(bright.any(axis=1))
    assert cols.size and cols.min() > 20 and cols.max() < 1080 - 20  # nothing runs off the sides
    bands = np.flatnonzero(np.diff(rows) > 12).size + 1  # separate text lines
    assert bands >= 2  # it wrapped


def test_wrap_breaks_cjk_and_words_the_same_for_preview_and_render() -> None:
    from vidgrab.studio import text_advance, wrap_cue_text, wrap_line

    width = lambda part: len(part) * 10.0
    assert wrap_line("short", width, 100) == ["short"]
    # Chinese has no spaces: break between characters, but never before a closing mark
    lines = wrap_line("一二三四五六七八九十，一二三", width, 100)
    assert lines == ["一二三四五六七八九十，", "一二三"] or all(not ln.startswith("，") for ln in lines)
    assert all(not ln.startswith(("，", "。")) for ln in wrap_line("一二三四五六七八九，。一二三四", width, 100))
    assert wrap_line("hello big wide world", width, 100) == ["hello big", "wide world"]
    assert wrap_line("supercalifragilistic", width, 100) == ["supercalifragilistic"]  # a word is not cut
    # a cue's own line breaks stay; each line is wrapped on its own
    out = wrap_cue_text("甲乙丙丁戊己庚辛\n短", 30, 100)
    assert out[-1] == "短" and len(out) >= 2 and "\n" not in "".join(out)
    assert text_advance("一", 29) > text_advance("a", 29) > text_advance(" ", 29)
    # the ASS script carries those breaks, so libass never has to wrap
    ass = format_ass([SubtitleCue(0, 2, "一二三四五六七八九十" * 4)], 1080, 1920)
    assert "\\N" in next(ln for ln in ass.splitlines() if ln.startswith("Dialogue"))


# ── two videos at once ────────────────────────────────────────────────────


def test_split_panels_cover_the_frame():
    assert studio.split_panels("side", 1920, 1080, 0) == [(0, 0, 960, 1080), (960, 0, 960, 1080)]
    left, right = studio.split_panels("side", 1920, 1080, 10)
    assert right[0] - (left[0] + left[2]) >= 10
    top, bottom = studio.split_panels("stack", 1080, 1920, 0)
    assert top[3] + bottom[3] == 1920 and bottom[1] == top[3]
    big, small = studio.split_panels("wide", 1920, 1080, 0)
    assert big[2] > small[2] and big[2] + small[2] == 1920
    full, inset = studio.split_panels("pip", 1920, 1080)
    assert full == (0, 0, 1920, 1080)
    assert inset[0] + inset[2] < 1920 and inset[1] + inset[3] < 1080


def test_split_needs_two_videos(tmp_path):
    clip = studio.Clip(str(tmp_path / "x.mp4"))
    with pytest.raises(RuntimeError):
        studio.compose_split([clip], tmp_path / "o.mp4")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg not available")
@pytest.mark.parametrize("layout", studio.SPLIT_LAYOUTS)
def test_split_renders_both_lengths(tmp_path, layout):
    def make(name, spec, secs):
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"{spec}:d={secs}", "-f", "lavfi", "-i", f"sine=d={secs}", "-shortest",
                        str(out)], check=True)
        return str(out)
    a = make("a.mp4", "testsrc2=s=320x180:r=25", 2)
    b = make("b.mp4", "smptebars=s=160x240:r=25", 1)
    clips = [studio.Clip(a, fit="fill"), studio.Clip(b, fit="fill")]
    for length, expect in (("longest", 2.0), ("shortest", 1.0)):
        out = studio.compose_split(clips, tmp_path / f"{layout}-{length}.mp4", layout=layout,
                                   resolution="480p", gap=4, length=length, audio="first")
        info = studio.probe_media(out)
        assert (info["width"], info["height"]) == (854, 480)
        assert info["has_audio"] and abs(info["duration"] - expect) < 0.15


# ── audio cleanup: reduce noise per clip, even out the loudness ─────────


def _clip_for_graph(tmp_path, denoise=False):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    return studio._ResolvedClip(path=src, start=0.0, duration=2.0, has_video=True, has_audio=True,
                                width=320, height=180, denoise=denoise)


def test_denoise_and_loudness_are_only_in_the_graph_when_asked(tmp_path):
    out = tmp_path / "o.mp4"
    cmd, _ = studio.build_video_command("ffmpeg", [_clip_for_graph(tmp_path)], out)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "afftdn" not in graph and "loudnorm" not in graph
    cmd, _ = studio.build_video_command("ffmpeg", [_clip_for_graph(tmp_path, denoise=True)], out,
                                        normalize_loudness=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert studio.DENOISE in graph and graph.count("afftdn") == 1  # that clip only
    assert graph.index("loudnorm") > graph.index("concat")  # on the finished mix, last


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg not available")
def test_cleanup_really_changes_the_sound(tmp_path):
    import re

    noisy = tmp_path / "noisy.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=25:d=8", "-f", "lavfi", "-i",
                    "sine=f=300:d=8,volume='if(lt(mod(t,4),2),0.5,0.0)':eval=frame", "-f", "lavfi",
                    "-i", "anoisesrc=color=pink:amplitude=0.02:d=8", "-filter_complex",
                    "[1][2]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map",
                    "[a]", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(noisy)], check=True)

    def stat(path, args, pattern):
        err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args, "-i", str(path),
                              "-af", pattern[0], "-vn", "-f", "null", "-"],
                             capture_output=True, text=True, check=False).stderr
        return float(re.findall(pattern[1], err)[-1])

    def hiss(path):  # the quiet gap between the tone bursts
        return stat(path, ["-ss", "2.3", "-t", "1.4"], ("volumedetect", r"mean_volume: (-?[\d.]+) dB"))

    def lufs(path):
        return stat(path, [], ("ebur128", r"I:\s+(-?[\d.]+) LUFS"))

    plain = studio.compose_video([studio.Clip(str(noisy))], tmp_path / "plain.mp4", resolution="480p")
    clean = studio.compose_video([studio.Clip(str(noisy), denoise=True)], tmp_path / "clean.mp4",
                                 resolution="480p")
    loud = studio.compose_video([studio.Clip(str(noisy))], tmp_path / "loud.mp4", resolution="480p",
                                normalize_loudness=True)
    assert hiss(clean) < hiss(plain) - 8  # the hiss is clearly quieter (about 16 dB here)
    assert lufs(plain) < -20  # a quiet clip ...
    assert abs(lufs(loud) - (-14)) < 2.5  # ... brought to about -14 LUFS


# ── music ducking ─────────────────────────────────────────────────────────


def test_ducking_is_only_in_the_graph_when_asked(tmp_path):
    clip = _clip_for_graph(tmp_path)
    song = tmp_path / "s.mp3"
    song.write_bytes(b"x")
    out = tmp_path / "o.mp4"
    plain = studio.BackgroundMusic(str(song), length=30.0)
    cmd, _ = studio.build_video_command("ffmpeg", [clip], out, music=[plain])
    assert "sidechaincompress" not in cmd[cmd.index("-filter_complex") + 1]
    ducked = studio.BackgroundMusic(str(song), length=30.0, duck=True)
    cmd, _ = studio.build_video_command("ffmpeg", [clip], out, music=[ducked, ducked])
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.count("sidechaincompress") == 1  # one compressor for all the songs


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg not available")
def test_the_music_really_gets_quieter_under_speech(tmp_path):
    import re

    talk = tmp_path / "talk.mp4"  # "speech" for 2 s, then a pause, then again
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=25:d=8", "-f", "lavfi", "-i",
                    "sine=f=300:d=8,volume='if(lt(mod(t,4),2),0.5,0.0)':eval=frame", "-c:v",
                    "libx264", "-c:a", "aac", "-shortest", str(talk)], check=True)
    music = tmp_path / "music.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=900:d=12",
                    "-af", "volume=0.3", str(music)], check=True)

    def level(path, start):
        err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", "1.2", "-i",
                              str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                             capture_output=True, text=True, check=False).stderr
        return float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1))

    results = {}
    for duck in (False, True):
        # the clips' own sound is silent in the mix (original_volume 0): only the music is heard
        song = studio.BackgroundMusic(str(music), volume=1.0, original_volume=0.0, duck=duck)
        out = studio.compose_video([studio.Clip(str(talk))], tmp_path / f"d{duck}.mp4",
                                   resolution="480p", music=[song])
        results[duck] = (level(out, 0.4), level(out, 2.6))  # (while speaking, in the pause)
    speaking, pause = results[True]
    assert pause - speaking > 10  # pressed down by more than 10 dB while there is speech
    assert abs(results[False][0] - results[False][1]) < 1.5  # without ducking it is steady
