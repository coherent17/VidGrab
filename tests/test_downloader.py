"""Tests for downloader.py — pure logic, no network (yt-dlp downloads are skipped)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import downloader


# ── helpers ───────────────────────────────────────────────────────────────

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _make_video(path: Path, seconds: str = "1") -> None:
    """Create a tiny 64x64 color video for processing tests."""
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", seconds, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


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


# ── misc ──────────────────────────────────────────────────────────────────

def test_locate_output_no_double_dot_bug(tmp_path) -> None:
    """Regression: _locate_output used to build '*..mp3' and never match."""
    d = tmp_path
    (d / "song.mp3").write_bytes(b"audio")
    assert downloader._locate_output(d, "song", "mp3", "") == d / "song.mp3"