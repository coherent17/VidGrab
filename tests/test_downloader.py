"""Tests for downloader.py — pure logic, no network (yt-dlp downloads are skipped)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

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


def test_ytdl_options_prefer_h264_at_same_resolution(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp4", ffmpeg=None, quality="720p")
    sort = opts["format_sort"]
    assert sort.index("res") < sort.index("vcodec:h264")


def test_ytdl_options_name_template(tmp_path) -> None:
    opts = downloader._ytdl_options("https://x", tmp_path, "mp4", ffmpeg=None,
                                    name_template=downloader.NAME_TEMPLATES["title_id"])
    assert opts["outtmpl"].endswith("%(title)s [%(id)s].%(ext)s")


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

def test_unreachable_network_retries_over_ipv4() -> None:
    from vidgrab import downloader

    calls = []

    def attempt(client: str, ipv4: bool) -> str:
        calls.append((client, ipv4))
        if not ipv4:
            raise RuntimeError("ERROR: [download] Got error: [Errno 101] Network is unreachable")
        return "ok"

    logs: list[str] = []
    assert downloader._try_clients(attempt, logs.append, lambda t, **kw: t.format(**kw)) == "ok"
    assert calls == [("tv_embedded", False), ("tv_embedded", True)]
    assert "IPv4" in logs[0]

    # other errors still fall through to the next player client, then fail
    calls.clear()

    def forbidden(client: str, ipv4: bool) -> str:
        calls.append((client, ipv4))
        raise RuntimeError("HTTP Error 403: Forbidden")

    with pytest.raises(RuntimeError, match="403"):
        downloader._try_clients(forbidden, logs.append, lambda t, **kw: t.format(**kw))
    assert calls == [("tv_embedded", False), ("android", False)]

    opts = downloader._ytdl_options("u", Path("."), "mp4", ffmpeg=None, ipv4=True)
    assert opts["source_address"] == "0.0.0.0"
    assert "source_address" not in downloader._ytdl_options("u", Path("."), "mp4", ffmpeg=None)


# ── network settings, audio formats, exact formats, live, search ──────────


@pytest.fixture
def fresh_network():
    downloader.configure_network()
    yield
    downloader.configure_network()


def _opts(fmt="mp4", **kw):
    return downloader._ytdl_options("u", Path("."), fmt, ffmpeg=None, **kw)


def test_network_settings_reach_every_download(fresh_network, tmp_path):
    assert "ratelimit" not in _opts() and "proxy" not in _opts()
    downloader.configure_network(rate_limit=500_000, proxy=" http://p:8080 ", retries=3,
                        archive=tmp_path / "a.txt")
    o = _opts()
    assert (o["ratelimit"], o["proxy"], o["retries"], o["fragment_retries"]) == (
        500_000, "http://p:8080", 3, 3)
    assert "download_archive" not in o  # only playlists use the archive
    assert _opts(archive=True)["download_archive"] == str(tmp_path / "a.txt")
    downloader.configure_network(rate_limit=0)
    assert "ratelimit" not in _opts()


@pytest.mark.parametrize("key,codec,quality", [
    ("mp3", "mp3", "128"), ("m4a", "m4a", "128"), ("opus", "opus", "128"),
    ("flac", "flac", None), ("wav", "wav", None)])
def test_audio_formats_choose_the_codec(key, codec, quality):
    pp = _opts("mp3", audio_fmt=key, quality="128")["postprocessors"][0]
    assert pp["preferredcodec"] == codec and pp.get("preferredquality") == quality


def test_unknown_audio_format_is_mp3():
    assert downloader.audio_format("nope")[1] == ".mp3" and downloader.audio_format(None)[1] == ".mp3"


def test_bitrates_are_kilobits():
    assert downloader._bitrate_arg("192") == "192k" and downloader._bitrate_arg(None) == "192k"
    assert downloader._bitrate_arg("320k") == "320k"


def test_an_exact_format_comes_first_with_a_fallback():
    sel = _opts(format_id="137", quality="720p")["format"]
    assert sel.startswith("137+bestaudio") and sel.endswith("best[height<=?720]")
    assert _opts("mp3", format_id="140")["format"] == "140"


def test_live_recording_options():
    o = _opts(live=True)
    assert o["live_from_start"] and o["hls_use_mpegts"]
    assert "live_from_start" not in _opts()


def test_format_list_orders_and_skips_junk():
    fl = downloader._format_options([
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1.64002a", "acodec": "none",
         "height": 1080, "fps": 30, "filesize": 5000},
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2",
         "height": 360, "fps": 25},
    ])
    assert [f["id"] for f in fl] == ["137", "18", "140"]  # video by height, then audio only
    assert fl[0]["vcodec"] == "H.264" and fl[2]["acodec"] == "AAC" and fl[2]["vcodec"] == ""


class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: `calls` lists the options of each use."""

    calls: ClassVar[list[dict]] = []
    behaviour = staticmethod(lambda opts, url: {})

    def __init__(self, opts):
        self.opts = opts
        _FakeYDL.calls.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def extract_info(self, url, download=True):
        return _FakeYDL.behaviour(self.opts, url)


@pytest.fixture
def fake_ydl(monkeypatch):
    _FakeYDL.calls = []
    _FakeYDL.behaviour = staticmethod(lambda opts, url: {})
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _FakeYDL)
    return _FakeYDL


def test_playlist_with_nothing_new_says_so(fake_ydl, fresh_network, tmp_path):
    downloader.configure_network(archive=tmp_path / "archive.txt")
    logs = []
    files = downloader.download_playlist("https://x/list", tmp_path, "mp4", skip_downloaded=True,
                                on_log=logs.append)
    assert files == [] and any("Nothing new" in m for m in logs)
    assert fake_ydl.calls[0]["download_archive"] == str(tmp_path / "archive.txt")
    with pytest.raises(RuntimeError, match="output file was not found"):
        downloader.download_playlist("https://x/list", tmp_path, "mp4")  # no archive: a real failure


def test_search_returns_plain_results(fake_ydl):
    fake_ydl.behaviour = staticmethod(lambda opts, url: {"entries": [
        {"id": "abc", "title": "T", "channel": "C", "duration": 61, "view_count": 5,
         "thumbnails": [{"url": "t1"}, {"url": "t2"}]},
        {"title": "no id"}]})
    res = downloader.search("  lofi  ", 5)
    assert fake_ydl.calls[0]["extract_flat"] and res == [{
        "id": "abc", "title": "T", "uploader": "C", "duration": 61, "views": 5,
        "url": "https://www.youtube.com/watch?v=abc", "thumbnail": "t2"}]
    with pytest.raises(RuntimeError):
        downloader.search("   ")


def test_translated_subtitles_are_asked_again_after_429(fake_ydl, tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(downloader, "_sleep", waits.append)
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)

    def behave(opts, url):
        if len(fake_ydl.calls) == 1:  # the first answer is "too many requests"
            opts["logger"].error("ERROR: Unable to download: HTTP Error 429: Too Many Requests")
        else:
            (tmp_path / "clip.ja.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        return {}

    fake_ydl.behaviour = staticmethod(behave)
    logs = []
    out = downloader.fetch_subtitles("https://x/v", tmp_path, "ja", "clip", on_log=logs.append)
    assert out and out.name == "clip.ja.srt"
    assert waits == [downloader.SUBTITLE_RETRY_WAITS[0]] and len(fake_ydl.calls) == 2


def test_subtitles_give_up_quietly_after_the_retries(fake_ydl, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "_sleep", lambda _s: None)
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    fake_ydl.behaviour = staticmethod(lambda opts, url: opts["logger"].error("HTTP Error 429") or {})
    assert downloader.fetch_subtitles("https://x/v", tmp_path, "ko", "clip") is None
    assert len(fake_ydl.calls) == 1 + len(downloader.SUBTITLE_RETRY_WAITS)


def test_a_missing_language_is_not_retried(fake_ydl, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    assert downloader.fetch_subtitles("https://x/v", tmp_path, "ko", "clip") is None
    assert len(fake_ydl.calls) == 1


def test_waiting_for_a_stream_polls_until_it_starts(monkeypatch):
    states = iter([("is_upcoming", None), ("is_upcoming", None), ("is_live", None)])
    monkeypatch.setattr(downloader, "_stream_status", lambda _u: next(states))
    monkeypatch.setattr(downloader, "_sleep", lambda _s: None)
    shown = []
    downloader._wait_for_stream("u", lambda m, p: shown.append(m), lambda _m: None, downloader._noop_tr)
    assert len(shown) == 2 * downloader.STREAM_POLL_S and "Waiting" in shown[0]


def test_waiting_for_a_stream_can_be_cancelled(monkeypatch):
    monkeypatch.setattr(downloader, "_stream_status", lambda _u: ("is_upcoming", None))
    monkeypatch.setattr(downloader, "_sleep", lambda _s: None)

    def progress(_m, _p):
        raise downloader.DownloadCancelled()

    with pytest.raises(downloader.DownloadCancelled):
        downloader._wait_for_stream("u", progress, lambda _m: None, downloader._noop_tr)


def test_a_stream_that_is_already_live_does_not_wait(monkeypatch):
    monkeypatch.setattr(downloader, "_stream_status", lambda _u: ("is_live", None))
    downloader._wait_for_stream("u", lambda *_a: pytest.fail("waited"), lambda _m: None, downloader._noop_tr)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_stopping_a_recording_keeps_what_was_recorded(tmp_path):
    import subprocess
    import time
    part = tmp_path / "Live show.mp4.part"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=10", "-t", "1", "-f", "mpegts", str(part)],
                   check=True)
    out = downloader._keep_recording(tmp_path, time.time() - 5, shutil.which("ffmpeg"),
                            lambda _m: None, downloader._noop_tr)
    assert out == tmp_path / "Live show.mp4" and out.stat().st_size > 0
    assert not part.exists()
    assert downloader._keep_recording(tmp_path, time.time() - 5, None, lambda _m: None, downloader._noop_tr) is None
