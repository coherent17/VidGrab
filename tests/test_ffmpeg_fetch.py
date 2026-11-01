"""Fetching the pinned ffmpeg for builds that do not carry it."""

from __future__ import annotations

import gzip
import hashlib
import io
import sys
import tarfile
import zipfile

import pytest

from vidgrab import ffmpeg_fetch as ff


def _gz_pin(tmp_path, ffmpeg=b"FFMPEG", ffprobe=b"FFPROBE", bad_sha=False):
    for name, blob in (("ffmpeg-darwin-arm64.gz", ffmpeg), ("ffprobe-darwin-arm64.gz", ffprobe)):
        (tmp_path / name).write_bytes(gzip.compress(blob))

    def entry(name):
        sha = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        return {"name": name, "sha256": "0" * 64 if bad_sha else sha}

    return {"version": "9", "release": "r", "files": {"mac-arm64": {
        "url_base": tmp_path.as_uri() + "/", "version": "6.1.1",
        "ffmpeg": entry("ffmpeg-darwin-arm64.gz"), "ffprobe": entry("ffprobe-darwin-arm64.gz")}}}


def test_one_gzip_per_program_is_unpacked_once(tmp_path):
    pin = _gz_pin(tmp_path)
    dest = tmp_path / "out"
    ff.fetch("mac-arm64", dest, pin=pin, log=lambda _m: None)
    assert (dest / "ffmpeg").read_bytes() == b"FFMPEG" and (dest / "ffprobe").read_bytes() == b"FFPROBE"
    if sys.platform != "win32":
        assert (dest / "ffmpeg").stat().st_mode & 0o111  # runnable
    assert (dest / "VERSION").read_text().strip() == "ffmpeg-darwin-arm64.gz"
    (dest / "ffmpeg").write_bytes(b"changed")
    logs = []
    ff.fetch("mac-arm64", dest, pin=pin, log=logs.append)  # the pinned version is there: no download
    assert (dest / "ffmpeg").read_bytes() == b"changed" and "already" in logs[0]


def test_a_download_that_does_not_match_the_pin_is_refused(tmp_path):
    dest = tmp_path / "out"
    with pytest.raises(RuntimeError, match="checksum"):
        ff.fetch("mac-arm64", dest, pin=_gz_pin(tmp_path, bad_sha=True), log=lambda _m: None)
    assert not dest.exists() or not any(dest.iterdir())


def test_an_unreachable_server_is_a_plain_error(tmp_path):
    pin = _gz_pin(tmp_path)
    pin["files"]["mac-arm64"]["url_base"] = (tmp_path / "nowhere").as_uri() + "/"
    with pytest.raises(RuntimeError, match="could not download"):
        ff.fetch("mac-arm64", tmp_path / "out", pin=pin, log=lambda _m: None)


@pytest.mark.parametrize("archive", ["zip", "tar.xz"])
def test_the_btbn_archives_give_up_their_bin_folder(tmp_path, monkeypatch, archive):
    buf = io.BytesIO()
    members = {"ffmpeg-x/bin/ffmpeg": b"A", "ffmpeg-x/bin/ffprobe": b"B", "ffmpeg-x/doc/ffmpeg": b"no"}
    if archive == "zip":
        with zipfile.ZipFile(buf, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
    else:
        with tarfile.open(fileobj=buf, mode="w:xz") as t:
            for n, b in members.items():
                info = tarfile.TarInfo(n)
                info.size = len(b)
                t.addfile(info, io.BytesIO(b))
    data = buf.getvalue()
    monkeypatch.setattr(ff, "_download", lambda url, sha, progress: data)
    pin = {"version": "9", "release": "r", "files": {"linux": {"name": f"x.{archive}", "sha256": "s"}}}
    dest = ff.fetch("linux", tmp_path / "bin", pin=pin, log=lambda _m: None)
    assert (dest / "ffmpeg").read_bytes() == b"A" and (dest / "ffprobe").read_bytes() == b"B"


def test_a_platform_without_a_pin_says_which_exist(tmp_path):
    with pytest.raises(RuntimeError, match="mac-arm64"):
        ff.fetch("beos", tmp_path, pin=_gz_pin(tmp_path), log=lambda _m: None)


@pytest.mark.parametrize("plat,machine,key", [
    ("linux", "x86_64", "linux"), ("linux", "aarch64", None),
    ("win32", "AMD64", "win"), ("win32", "ARM64", None),
    ("darwin", "arm64", "mac-arm64"), ("darwin", "x86_64", "mac-x64")])
def test_the_right_build_for_each_computer(monkeypatch, plat, machine, key):
    monkeypatch.setattr(ff.sys, "platform", plat)
    monkeypatch.setattr(ff.platform, "machine", lambda: machine)
    assert ff.platform_key() == key


def test_the_real_pin_lists_every_platform_with_a_checksum():
    pin = ff.load_pin()
    assert set(pin["files"]) == {"linux", "win", "mac-arm64", "mac-x64"}
    for key, spec in pin["files"].items():
        shas = [spec["sha256"]] if "sha256" in spec else [spec["ffmpeg"]["sha256"], spec["ffprobe"]["sha256"]]
        assert all(len(s) == 64 for s in shas), key


def test_ensure_puts_ffmpeg_in_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(ff, "platform_key", lambda: "mac-arm64")
    monkeypatch.setattr(ff, "sys", type("S", (), {"platform": "linux"}))  # cache_dir(): XDG branch
    monkeypatch.setattr(ff, "load_pin", lambda: _gz_pin(tmp_path))
    path = ff.ensure()
    assert path == str(tmp_path / "cache" / "vidgrab" / "ffmpeg" / "ffmpeg")
    assert ff.cached_ffmpeg() == path
