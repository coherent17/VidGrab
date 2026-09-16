"""Minimal import/structure tests for the UI (no display required)."""

from __future__ import annotations


def test_app_module_imports() -> None:
    from vidgrab import app

    assert hasattr(app, "VidGrabWindow")
    assert hasattr(app, "DARK_QSS")
    assert hasattr(app, "LIGHT_QSS")


def test_package_and_version() -> None:
    import vidgrab
    from vidgrab.downloader import get_app_dir

    assert isinstance(vidgrab.__version__, str)
    assert get_app_dir().is_dir()
