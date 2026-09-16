"""Headless smoke test that constructs the real UI.

Runs only under a virtual X server (CI sets SMOKE_GUI=1 and uses xvfb-run).
Catches CustomTkinter API misuse and layout errors that a plain import misses.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOKE_GUI") != "1",
    reason="set SMOKE_GUI=1 and run under xvfb-run to enable",
)


@pytest.fixture
def app(monkeypatch) -> None:
    # Never hit the real network during the smoke test.
    monkeypatch.setattr(
        "vidgrab.app.check_internet",
        lambda timeout=2.5: type("S", (), {"online": True, "reason": "mock"})(),
    )


def test_app_constructs_and_destroys(app) -> None:
    from vidgrab.app import VidGrabApp

    instance = VidGrabApp()
    try:
        assert instance.title() == "VidGrab"
        assert instance.source_seg.get() == "YouTube URL"
        # toggle to local-file mode and back
        instance.source_seg.set("Local File")
        instance._refresh_source_row()
        instance.source_seg.set("YouTube URL")
        instance._refresh_source_row()
    finally:
        instance.destroy()


def test_app_toggles_theme(app) -> None:
    from vidgrab import app as appmod

    instance = appmod.VidGrabApp()
    try:
        instance._set_theme("Light")
        assert appmod.ctk.get_appearance_mode() == "Light"
    finally:
        instance.destroy()