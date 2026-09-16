"""Minimal import/structure tests for the UI (no display required)."""

from __future__ import annotations

import importlib.util

import pytest

_HAS_TK = importlib.util.find_spec("tkinter") is not None


@pytest.mark.skipif(not _HAS_TK, reason="tkinter not available")
def test_app_module_imports() -> None:
    from vidgrab import app

    assert hasattr(app, "VidGrabApp")
    assert hasattr(app, "BG")
    assert hasattr(app, "ACCENT")


def test_package_and_version() -> None:
    import vidgrab
    from vidgrab.downloader import get_app_dir

    assert isinstance(vidgrab.__version__, str)
    assert get_app_dir().is_dir()