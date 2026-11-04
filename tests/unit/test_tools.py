"""Tools engine and Library scan, with real ffmpeg where it matters."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from vidgrab import library, studio, tools

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg / ffprobe not on PATH")


def test_bitrate_for_a_target_size() -> None:
    assert tools.video_kbps(25, 100) == int(25 * 8192 * 0.95 / 100 - 128)
    assert tools.video_kbps(1, 3600) == tools.MIN_VIDEO_KBPS  # never absurdly low
    assert tools.suggested_height(25, 60) == 0 and tools.suggested_height(8, 600) == 360


def test_convert_checks_the_extension() -> None:
    assert tools.convert_command("a.mp4", "b.mp3", "mp3")[-1] == "b.mp3"
    with pytest.raises(ValueError):
        tools.convert_command("a.mp4", "b.mkv", "mp3")


def test_output_names_are_free(tmp_path) -> None:
    (tmp_path / "v (small).mp4").write_bytes(b"x")
    assert tools.output_for(tmp_path / "v.mp4", "small", ".mp4").name == "v (small) (2).mp4"


def _clip(tmp_path, secs=4):
    p = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(secs), str(p)], check=True)
    return p


@needs_ffmpeg
def test_compress_lands_near_the_target(tmp_path) -> None:
    src = _clip(tmp_path, 6)
    out = tmp_path / "o.mp4"
    seen = []
    tools.run_tool(tools.compress_command(str(src), str(out), 0.25, 6), 6, label="x",
                   on_progress=lambda m, p: seen.append(p))
    assert out.is_file() and out.stat().st_size < 0.25 * 1024 * 1024 * 1.4 and seen[-1] == 100.0


@needs_ffmpeg
def test_convert_gif_and_audio(tmp_path) -> None:
    src = _clip(tmp_path)
    mp3 = tmp_path / "a.mp3"
    tools.run_tool(tools.convert_command(str(src), str(mp3), "mp3"), 4, label="x")
    assert studio.probe_media(mp3)["has_video"] is False
    gif = tmp_path / "g.gif"
    tools.run_tool(tools.gif_command(str(src), str(gif), 1, 2, 160), 2, label="x")
    assert gif.read_bytes()[:3] == b"GIF"


@needs_ffmpeg
def test_failed_tool_leaves_no_output(tmp_path) -> None:
    out = tmp_path / "bad.mp4"
    with pytest.raises(RuntimeError):
        tools.run_tool(tools.convert_command(str(tmp_path / "missing.mp4"), str(out), "mp4"), 1, label="x")
    assert not out.exists()


def test_library_scan_and_filter(tmp_path) -> None:
    (tmp_path / "pl").mkdir()
    (tmp_path / "pl" / "deep").mkdir()
    (tmp_path / "pl" / "deep" / "too.mp4").write_bytes(b"x")  # three levels down
    for name in ("a.mp4", "b song.mp3", "c.gif", "pl/d.webm", "e.part", "notes.txt"):
        (tmp_path / name).write_bytes(b"12345")
    old = time.time() - 1000
    os.utime(tmp_path / "a.mp4", (old, old))
    entries = library.scan(tmp_path)
    assert sorted(e.name for e in entries) == ["a", "b song", "c", "d"]
    assert entries[-1].name == "a"  # oldest last
    assert [e.name for e in library.filter_entries(entries, "audio")] == ["b song"]
    assert [e.name for e in library.filter_entries(entries, "all", "SONG b")] == ["b song"]
    assert library.scan(tmp_path / "nope") == []


def test_library_finder_is_fuzzy_and_ranked(tmp_path) -> None:
    for name in ("Interview with Ada.mp4", "Mountain hike.mp4", "Lo-fi beats.mp3", "adaptive notes.png"):
        (tmp_path / name).write_bytes(b"x")
    f = library.Finder(library.scan(tmp_path))
    assert [e.name for e in f.filter("all", "intervew")] == ["Interview with Ada"]  # a dropped letter
    assert f.filter("all", "ada")[0].name == "Interview with Ada"  # the whole word beats a longer one
    assert [e.name for e in f.filter("audio", "beat")] == ["Lo-fi beats"]
    assert f.suggest("moun")[0] == "Mountain hike" and f.did_you_mean("mountin") == "mountain"
    assert len(f.filter("all", "")) == 4
