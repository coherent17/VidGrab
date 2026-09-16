"""Minimal import/structure tests for the tkinter UI (no display required)."""

from __future__ import annotations

import importlib.util
import pytest

_HAS_TK = importlib.util.find_spec("tkinter") is not None


@pytest.mark.skipif(not _HAS_TK, reason="tkinter not available")
def test_app_module_imports() -> None:
    import app

    assert hasattr(app, "VidGrabApp")
    assert hasattr(app, "BG")
    assert hasattr(app, "ACCENT")

    from downloader import get_app_dir

    assert get_app_dir().is_dir()