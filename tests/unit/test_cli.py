"""The `vidgrab` command's text options (no window)."""

from __future__ import annotations

import sys

import pytest

from vidgrab import cli
from vidgrab._version import __version__


def test_version_and_help_print_and_exit(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"VidGrab {__version__}"

    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "python -m vidgrab" in out and "from vidgrab.app import main" in out
    assert "pip install -U yt-dlp" in out and "--selftest" not in out  # the test flag is hidden


def test_info_reports_this_installation(capsys, monkeypatch):
    monkeypatch.setattr("vidgrab.core.downloader.find_ffmpeg", lambda: None)
    monkeypatch.setattr("vidgrab.ai.captions.installed", lambda: False)
    cli.main(["--info"])
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["VidGrab", __version__]
    assert "not found" in out and "vidgrab-studio[captions]" in out and "yt-dlp" in out


def test_anything_else_starts_the_app_with_qt_options_kept(monkeypatch):
    started = {}
    monkeypatch.setattr("vidgrab.ui.app.main", lambda: started.update(argv=list(sys.argv)))
    monkeypatch.setattr(sys, "argv", ["vidgrab"])
    cli.main(["--selftest", "-platform", "offscreen"])
    assert started["argv"] == ["vidgrab", "--selftest", "-platform", "offscreen"]
    cli.main([])
    assert started["argv"] == ["vidgrab"]


def test_command_line_tools(tmp_path, capsys, monkeypatch) -> None:
    import shutil
    import subprocess

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    clip = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15",
                    "-f", "lavfi", "-i", "sine", "-t", "3", str(clip)], check=True)
    for argv, name in ((["shrink", str(clip), "--mb", "1"], "v (1 MB).mp4"),
                       (["convert", str(clip), "--to", "mp3"], "v (converted).mp3"),
                       (["gif", str(clip), "--length", "1"], "v (gif).gif")):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 0 and (tmp_path / name).is_file()
        assert str(tmp_path / name) in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["best", str(clip), "--seconds", "2"])
    assert e.value.code == 0 and len(capsys.readouterr().out.split()) == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["shrink", str(tmp_path / "missing.mp4"), "--mb", "1"])
    assert e.value.code == 2


def test_get_command_downloads_each_link(tmp_path, capsys, monkeypatch) -> None:
    from vidgrab.core import downloader

    calls = []
    monkeypatch.setattr(downloader, "download", lambda url, out, fmt, **kw: calls.append((url, str(out), fmt, kw.get("quality")))
                        or tmp_path / "x.mp3")
    with pytest.raises(SystemExit) as e:
        cli.main(["get", "https://a/1", "https://a/2", "--mp3", "--quality", "720", "--out", str(tmp_path)])
    assert e.value.code == 0
    assert calls == [("https://a/1", str(tmp_path), "mp3", "720"), ("https://a/2", str(tmp_path), "mp3", "720")]


def test_short_command_makes_a_vertical_file(tmp_path) -> None:
    import shutil
    import subprocess

    import pytest

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("needs ffmpeg")
    from vidgrab import cli

    src = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
                   check=True)
    assert "short" in cli.COMMANDS
    assert cli.run_command(["short", str(src), "--seconds", "3", "--no-face", "--no-captions"]) == 0
    assert (tmp_path / "in (short).mp4").is_file()
