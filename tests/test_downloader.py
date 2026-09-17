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


# ── format labels ──────────────────────────────────────────────────────────

def test_format_label_height_codec_size() -> None:
    label = downloader._format_label(
        {"height": 1080, "vcodec": "avc1.640028", "filesize": 12_000_000}
    )
    assert label == "1080p \u00b7 H.264 \u00b7 11.4 MiB"


def test_format_label_skips_empty_entries() -> None:
    assert downloader._format_label({}) == ""
    assert downloader._format_label({"height": 1080}) == "1080p"


def test_height_key_parses_resolution() -> None:
    assert downloader._height_key("2160p \u00b7 AV1 \u00b7 23.8 MiB") == 2160
    assert downloader._height_key("nothing") == 0


# ── probe ─────────────────────────────────────────────────────────────────

def _video_info() -> dict:
    return {
        "id": "abc123",
        "title": "Cool Video",
        "uploader": "Channel Name",
        "duration": 125,
        "thumbnail": "https://example.com/thumb.jpg",
        "formats": [
            {"height": 720, "vcodec": "avc1.64001f", "filesize": 5_000_000},
            {"height": 2160, "vcodec": "av01.0.05M", "filesize_approx": 25_000_000},
            {"height": 720, "vcodec": "vp09.00.20", "filesize": 9_000_000},
            {"height": 1080, "vcodec": "avc1.6d0028", "filesize": 12_000_000},
        ],
    }


def _fake_ydl(info, monkeypatch):
    calls = {}

    class Fake:
        last_opts = None

        def __init__(self, opts):
            Fake.last_opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            calls["url"] = url
            calls["download"] = download
            return info

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Fake)
    return calls


def test_probe_video_makes_summary(monkeypatch) -> None:
    calls = _fake_ydl(_video_info(), monkeypatch)
    result = downloader.probe("https://youtu.be/abc123")
    assert calls["url"] == "https://youtu.be/abc123"
    assert calls["download"] is False
    assert result["is_playlist"] is False
    assert result["title"] == "Cool Video"
    assert result["uploader"] == "Channel Name"
    assert result["duration"] == 125
    assert result["playlist_count"] is None
    assert result["formats"] == [
        "2160p \u00b7 AV1 \u00b7 23.8 MiB",
        "1080p \u00b7 H.264 \u00b7 11.4 MiB",
        "720p \u00b7 H.264 \u00b7 4.8 MiB",
    ]
    assert "thumbnail_local" not in result


def test_probe_uses_flat_extraction(monkeypatch) -> None:
    _fake_ydl(_video_info(), monkeypatch)
    downloader.probe("https://youtu.be/abc123", thumb_dir=None)
    opts = downloader.yt_dlp.YoutubeDL.last_opts
    assert opts["extract_flat"] == "in_playlist"
    assert opts["noplaylist"] is True


def test_probe_playlist_detects_count(monkeypatch) -> None:
    info = {
        "_type": "playlist",
        "title": "My Mix",
        "entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
    }
    _fake_ydl(info, monkeypatch)
    result = downloader.probe("https://www.youtube.com/playlist?list=PLx")
    assert result["is_playlist"] is True
    assert result["playlist_count"] == 3
    assert result["formats"] == []


def test_probe_empty_url_raises(monkeypatch) -> None:
    _fake_ydl(_video_info(), monkeypatch)
    with pytest.raises(RuntimeError, match="No URL"):
        downloader.probe("   ")


def test_probe_stores_thumbnail_local(tmp_path, monkeypatch) -> None:
    _fake_ydl(_video_info(), monkeypatch)
    thumb = tmp_path / "thumb_cache" / "abc.jpg"
    monkeypatch.setattr(downloader, "_fetch_thumbnail", lambda url, d: str(thumb))
    result = downloader.probe("https://youtu.be/abc123", thumb_dir=tmp_path)
    assert result["thumbnail_local"] == str(thumb)


def test_fetch_thumbnail_caches_by_url(tmp_path, monkeypatch) -> None:
    calls: list = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"j" * 100

    def fake_open(req, timeout=12):
        calls.append(req)
        return FakeResp()

    monkeypatch.setattr(downloader.urllib.request, "urlopen", fake_open)
    path = downloader._fetch_thumbnail("https://example.com/t.jpg", tmp_path)
    assert path is not None
    assert Path(path).is_file()
    again = downloader._fetch_thumbnail("https://example.com/t.jpg", tmp_path)
    assert again == path
    assert len(calls) == 1


def test_fetch_thumbnail_tiny_payload_falls_back_to_url(tmp_path, monkeypatch) -> None:
    class Tiny:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"x" * 10

    monkeypatch.setattr(downloader.urllib.request, "urlopen", lambda req, timeout=12: Tiny())
    out = downloader._fetch_thumbnail("https://example.com/t.jpg", tmp_path)
    assert out == "https://example.com/t.jpg"


def test_fetch_thumbnail_network_error_returns_none(tmp_path, monkeypatch) -> None:
    def boom(req, timeout=12):
        raise OSError("offline")

    monkeypatch.setattr(downloader.urllib.request, "urlopen", boom)
    assert downloader._fetch_thumbnail("https://example.com/t.jpg", tmp_path) is None


# ── playlist download ──────────────────────────────────────────────────────

def test_download_playlist_numbers_and_returns(tmp_path, monkeypatch) -> None:
    created: list[Path] = []

    class Fake:
        last_opts = None

        def __init__(self, opts):
            Fake.last_opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            out_dir = Path(str(Fake.last_opts["outtmpl"]).split("%(")[0])
            for index, title in enumerate((("One", "Two")), 1):
                p: Path = out_dir / f"{index:02d} - {title}.mp4"
                p.write_bytes(b"x")
                created.append(p)
            return {"_type": "playlist", "title": "PL", "entries": [{}, {}]}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Fake)
    result = downloader.download_playlist(
        "https://www.youtube.com/playlist?list=PLx", tmp_path, "mp4"
    )
    assert Fake.last_opts["noplaylist"] is False
    assert Fake.last_opts["outtmpl"].endswith(
        "%(playlist_index)02d - %(title)s.%(ext)s"
    )
    assert result == created
    assert result[0].name == "01 - One.mp4"


def test_download_playlist_no_new_files_raises(tmp_path, monkeypatch) -> None:
    class Fake:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            return {"_type": "playlist", "title": "PL", "entries": []}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Fake)
    with pytest.raises(RuntimeError, match="output file was not found"):
        downloader.download_playlist("https://x/list", tmp_path, "mp4")


def test_download_playlist_mp3_requires_ffmpeg(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        downloader.download_playlist("https://x/list", tmp_path, "mp3")


def test_download_playlist_empty_url_raises(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="No URL"):
        downloader.download_playlist("   ", tmp_path, "mp4")


def test_new_files_filters_partials(tmp_path) -> None:
    import time

    after = time.time()
    (tmp_path / "01 - a.mp4").write_bytes(b"x")
    (tmp_path / "02 - b.mp4.part").write_bytes(b"x")
    (tmp_path / "03 - c.mp4.ytdl").write_bytes(b"x")
    (tmp_path / "04 - d.mp3").write_bytes(b"x")
    assert sorted(downloader._new_files(tmp_path, after)) == sorted(
        [tmp_path / "01 - a.mp4", tmp_path / "04 - d.mp3"]
    )


def test_playlist_order_index() -> None:
    assert downloader._playlist_order(Path("02 - x.mp4")) == 2
    assert downloader._playlist_order(Path("no index.mp4")) == 10**9


def test_ytdl_options_noplaylist_default(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp4", ffmpeg=None)
    assert opts["noplaylist"] is True


def test_ytdl_options_playlist_outtmpl(tmp_path) -> None:
    opts = downloader._ytdl_options(
        "https://x", tmp_path, "mp4", ffmpeg=None,
        noplaylist=False, outtmpl="%(playlist_index)02d - %(title)s.%(ext)s",
    )
    assert opts["noplaylist"] is False
    assert opts["outtmpl"] == "%(playlist_index)02d - %(title)s.%(ext)s"