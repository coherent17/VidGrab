"""Toast notifications."""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")


@pytest.fixture
def win(tmp_path, monkeypatch):
    from conftest import patch_ui
    from PySide6.QtWidgets import QApplication

    from vidgrab.ui import app as m

    QApplication.instance() or QApplication([])
    patch_ui(monkeypatch, "_config_dir", lambda: tmp_path / "cfg")
    w = m.VidGrabWindow()
    w.resize(1180, 820)
    w.show()
    try:
        yield w
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()


def _pump(seconds: float) -> None:
    from PySide6.QtWidgets import QApplication

    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()


def test_a_toast_shows_in_the_corner_runs_its_action_and_goes_away(win) -> None:
    hits: list[int] = []
    t = win.toast("Saved: a.mp4", "ok", ("Show in folder", lambda: hits.append(1)))
    _pump(0.4)
    assert t.isVisible() and t.x() + t.width() <= win.width() and t.y() + t.height() <= win.height()
    t.action_btn.click()
    _pump(0.5)
    assert hits == [1] and not win._toasts.active()


def test_toasts_stack_without_overlapping_and_repeats_merge(win) -> None:
    a = win.toast("one")
    b = win.toast("two", "error")
    again = win.toast("one")
    _pump(0.4)
    assert again is a and len(win._toasts.active()) == 2
    assert b.y() + b.height() <= a.y() or a.y() + a.height() <= b.y()
    for _ in range(8):
        win.toast(f"msg {_}")
    assert len(win._toasts.active()) <= win._toasts.MAX
