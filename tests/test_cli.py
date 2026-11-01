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
    monkeypatch.setattr("vidgrab.downloader.find_ffmpeg", lambda: None)
    monkeypatch.setattr("vidgrab.captions.installed", lambda: False)
    cli.main(["--info"])
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["VidGrab", __version__]
    assert "not found" in out and "vidgrab-studio[captions]" in out and "yt-dlp" in out


def test_anything_else_starts_the_app_with_qt_options_kept(monkeypatch):
    started = {}
    monkeypatch.setattr("vidgrab.app.main", lambda: started.update(argv=list(sys.argv)))
    monkeypatch.setattr(sys, "argv", ["vidgrab"])
    cli.main(["--selftest", "-platform", "offscreen"])
    assert started["argv"] == ["vidgrab", "--selftest", "-platform", "offscreen"]
    cli.main([])
    assert started["argv"] == ["vidgrab"]
