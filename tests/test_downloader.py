"""Tests for downloader.py — pure logic, no network (yt-dlp downloads are skipped)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidgrab import downloader

# ── helpers ───────────────────────────────────────────────────────────────

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _make_video(path: Path, seconds: str = "1", with_audio: bool = False) -> None:
    """Create a tiny 64x64 color video for processing tests."""
    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    cmd += ["-t", seconds, str(path)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


# ── default_output_dir ────────────────────────────────────────────────────

def test_default_output_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    out = downloader.default_output_dir()
    assert out == tmp_path / "Downloads" / "VidGrab"
    assert out.is_dir()


# ── find_ffmpeg ───────────────────────────────────────────────────────────

def test_find_ffmpeg_returns_none_or_existing_file() -> None:
    ff = downloader.find_ffmpeg()
    if ff is None:
        return  # acceptable when no ffmpeg is installed
    assert Path(ff).is_file()


# ── _locate_output ────────────────────────────────────────────────────────

def test_locate_output_finds_newest_regular(tmp_path) -> None:
    d = tmp_path
    (d / "old.mp4").write_bytes(b"a")
    (d / "new.mp4").write_bytes(b"bb")
    out = downloader._locate_output(d, "", "mp4", "")
    assert out is not None
    assert out.name == "new.mp4"


def test_locate_output_suffix_pattern(tmp_path) -> None:
    d = tmp_path
    (d / "x.mp3tmp.mp3").write_bytes(b"audio")
    out = downloader._locate_output(d, "x", "mp3", ".mp3tmp")
    assert out is not None
    assert out.name == "x.mp3tmp.mp3"


def test_locate_output_ignores_partial_files(tmp_path) -> None:
    d = tmp_path
    (d / "video.mp4.part").write_bytes(b"partial")
    (d / "video.mp4.ytdl").write_bytes(b"meta")
    assert downloader._locate_output(d, "", "mp4", "") is None


def test_locate_output_missing(tmp_path) -> None:
    assert downloader._locate_output(tmp_path, "", "mp4", "") is None


# ── process_local_file ────────────────────────────────────────────────────

def test_process_local_file_missing_input_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        downloader.process_local_file(tmp_path / "nope.mp4", tmp_path)


def test_process_local_file_invalid_start_raises(tmp_path) -> None:
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="Invalid start time"):
        downloader.process_local_file(src, tmp_path, section_start="bogus")


def test_invalid_time_reported_before_ffmpeg_requirement(tmp_path, monkeypatch) -> None:
    """Bad times are validated even when ffmpeg is unavailable."""
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="Invalid start time"):
        downloader.process_local_file(src, tmp_path, section_start="bogus")


def test_process_local_file_end_not_after_start(tmp_path) -> None:
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="after the start"):
        downloader.process_local_file(
            src, tmp_path, section_start="0:10", section_end="0:05"
        )


@requires_ffmpeg
def test_process_local_file_copy_without_options(tmp_path) -> None:
    src = tmp_path / "clip.mp4"
    _make_video(src)
    out = downloader.process_local_file(src, tmp_path)
    assert out == tmp_path / "clip_processed.mp4"
    assert out.is_file()
    assert out.read_bytes() == src.read_bytes()


@requires_ffmpeg
def test_process_local_file_flip(tmp_path) -> None:
    src = tmp_path / "clip.mp4"
    _make_video(src)
    out = downloader.process_local_file(src, tmp_path, video_filter="hflip")
    assert out.is_file()
    assert out.stat().st_size > 0


@requires_ffmpeg
def test_process_local_file_trim(tmp_path) -> None:
    src = tmp_path / "clip.mp4"
    _make_video(src, seconds="2")
    out = downloader.process_local_file(
        src, tmp_path, section_start="0", section_end="1"
    )
    assert out.is_file()


@requires_ffmpeg
def test_derive_mp3_from_mp4(tmp_path) -> None:
    src = tmp_path / "clip.mp4"
    _make_video(src, seconds="1", with_audio=True)
    out = downloader.derive_mp3(src, tmp_path)
    assert out == tmp_path / "clip.mp3"
    assert out.is_file()
    assert out.stat().st_size > 0


def test_derive_mp3_missing_source(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        downloader.derive_mp3(tmp_path / "nope.mp4", tmp_path)


def test_version_is_importable() -> None:
    from vidgrab import __version__

    assert __version__.count(".") == 2


# ── speed ────────────────────────────────────────────────────────────────

def test_atempo_chain_single() -> None:
    assert downloader._atempo_chain(1.5) == ["atempo=1.5"]


def test_atempo_chain_fast() -> None:
    assert downloader._atempo_chain(4.0) == ["atempo=2.0", "atempo=2"]


def test_atempo_chain_odd_fast() -> None:
    assert downloader._atempo_chain(3.0) == ["atempo=2.0", "atempo=1.5"]


def test_atempo_chain_slow() -> None:
    assert downloader._atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]


def test_validate_speed_normalizes_identity() -> None:
    assert downloader._validate_speed(None) is None
    assert downloader._validate_speed(1.0) is None
    assert downloader._validate_speed(1.75) == 1.75


def test_validate_speed_out_of_range_raises() -> None:
    with pytest.raises(RuntimeError, match="Speed must be between"):
        downloader._validate_speed(8.0)


def test_speed_marker() -> None:
    assert downloader._speed_marker(None) == ""
    assert downloader._speed_marker(1.5) == "_1.5x"
    assert downloader._speed_marker(2.0) == "_2x"


def test_process_local_file_speed_builds_ffmpeg_args(tmp_path, monkeypatch) -> None:
    """Speed on a video re-encodes with setpts + atempo, and tags the name."""
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return Proc()

    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(downloader.subprocess, "run", fake_run)

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    out = downloader.process_local_file(src, tmp_path, speed=2.0)
    assert out.name == "clip_processed_2x.mp4"
    assert calls
    cmd = calls[0]
    joined = " ".join(str(a) for a in cmd)
    assert "setpts=(PTS-STARTPTS)/2.0+STARTPTS" in joined
    assert "atempo=2" in joined and "-af" in cmd
    assert "-c:v" in cmd and "libx264" in cmd


def test_process_local_file_speed_audio_only(tmp_path, monkeypatch) -> None:
    """Speed on an audio file only applies atempo, no video encode."""
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return Proc()

    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(downloader.subprocess, "run", fake_run)

    src = tmp_path / "song.mp3"
    src.write_bytes(b"fake")
    out = downloader.process_local_file(src, tmp_path, speed=0.75)
    assert out.name == "song_processed_0.75x.mp3"
    cmd = calls[0]
    assert "-vn" in cmd and "-af" in cmd and "atempo=0.75" in cmd
    assert "-vf" not in cmd


@requires_ffmpeg
def test_process_local_file_speed_real(tmp_path) -> None:
    """A 2 s clip at 2.0x comes out ~1 s long."""
    import json
    import subprocess as sp

    src = tmp_path / "clip.mp4"
    _make_video(src, seconds="2", with_audio=True)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe not installed")
    out = downloader.process_local_file(src, tmp_path, speed=2.0)
    assert out.is_file()
    data = json.loads(
        sp.run(
            [ffprobe, "-v", "quiet", "-show_format", "-print_format", "json", str(out)],
            check=True, capture_output=True, text=True,
        ).stdout
    )
    duration = float(data["format"]["duration"])
    assert 0.4 < duration < 1.4


# ── quality selection ───────────────────────────────────────────────────

def test_ytdl_options_video_quality_best(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp4", ffmpeg=None)
    assert opts["format"] == "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


def test_ytdl_options_video_quality_1080p(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp4",
                                    ffmpeg=None, quality="1080p")
    assert "[height<=1080]" in opts["format"]


def test_ytdl_options_audio_quality_bitrate(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp3",
                                    ffmpeg=None, quality="320")
    pp = opts["postprocessors"][0]
    assert pp["preferredcodec"] == "mp3" and pp["preferredquality"] == "320"


def test_ytdl_options_audio_default_bitrate(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp3", ffmpeg=None)
    assert opts["postprocessors"][0]["preferredquality"] == "192"


# ── preview args ────────────────────────────────────────────────────────

def test_preview_args_plain() -> None:
    args = downloader.preview_args("clip.mp4", 0.0, float("inf"), None, None)
    assert args == ["-autoexit", "-t", "6.0", "clip.mp4"]


def test_preview_args_filters() -> None:
    args = downloader.preview_args("clip.mp4", 5.0, 20.0, "hflip", 2.0)
    assert args[0:6] == ["-autoexit", "-ss", "5.0", "-t", "6.0", "-vf"]
    joined = " ".join(args)
    assert "hflip,setpts=(PTS-STARTPTS)/2.0+STARTPTS" in joined
    assert "-af" in args and "atempo=2" in joined


def test_find_ffplay_falls_back_to_path(monkeypatch) -> None:
    class FakeFFmpeg:
        parent = None
        is_file = lambda self: False

    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/usr/bin/ffplay")
    assert downloader.find_ffplay() == "/usr/bin/ffplay"


# ── misc ──────────────────────────────────────────────────────────────────

def test_locate_output_no_double_dot_bug(tmp_path) -> None:
    """Regression: _locate_output used to build '*..mp3' and never match."""
    d = tmp_path
    (d / "song.mp3").write_bytes(b"audio")
    assert downloader._locate_output(d, "song", "mp3", "") == d / "song.mp3"