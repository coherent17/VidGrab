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


def test_a_toast_goes_away_by_itself(win, monkeypatch) -> None:
    from vidgrab.ui import toast

    monkeypatch.setattr(toast, "LINGER_MS", {"ok": 250, "info": 250, "error": 250})
    t = win.toast("done", "ok")
    _pump(0.2)
    assert t.isVisible()
    _pump(1.0)
    assert not win._toasts.active()
    try:
        gone = not t.isVisible()
    except RuntimeError:  # already deleted, which is what closing does
        gone = True
    assert gone


def test_the_command_palette_finds_and_runs_things(win) -> None:
    win.open_palette()
    dlg = win._palette_dlg
    dlg.box.setText("libr")  # a page by a few letters
    assert dlg.list.count() >= 1 and "ibrary" in dlg.list.item(0).text()
    dlg._run(dlg.list.item(0))
    _pump(0.3)
    assert win._stack.currentIndex() == 2

    win.open_palette()
    dlg = win._palette_dlg
    dlg.box.setText("short")  # a tool, by name: opens the Tools page on it
    assert any("Short" in dlg.list.item(i).text() for i in range(dlg.list.count()))
    first = next(i for i in range(dlg.list.count()) if "Short" in dlg.list.item(i).text())
    dlg._run(dlg.list.item(first))
    _pump(0.3)
    assert win._stack.currentIndex() == 3 and win._tools._tool == "short"


def test_the_theme_list_can_follow_the_system(win, monkeypatch) -> None:
    from vidgrab.ui import app as m

    monkeypatch.setattr(m.VidGrabWindow, "_system_theme", staticmethod(lambda: "light"))
    win._theme_chosen("auto")
    assert win.setting("theme_auto") is True and win._theme == "light"
    assert win._theme_combo.currentData() == "auto"
    win._theme_chosen("dark")  # picking one by hand ends it
    assert win.setting("theme_auto") is False and win._theme == "dark"
    assert win._theme_combo.currentData() == "dark"


def test_the_title_bar_names_the_open_project(win, tmp_path) -> None:
    assert win.windowTitle() == "VidGrab"
    win._studio._project_path = str(tmp_path / "holiday.vgproj")
    win._studio._update_project_ui()
    assert win.windowTitle().startswith("holiday") and win.windowTitle().endswith("VidGrab")


def test_the_first_run_tour_walks_the_pages_and_shows_once(win) -> None:
    assert win.setting("welcome_shown") is False
    win._welcome()
    tour = win._tour
    assert tour.active() and win._stack.currentIndex() == 0
    seen = [win._stack.currentIndex()]
    while tour.active():
        tour.next()
        if tour.active():
            seen.append(win._stack.currentIndex())
    assert seen == [0, 1, 2, 3, 6]  # Download, Studio, Library, Tools, Help
    assert win.setting("welcome_shown") is True and win._stack.currentIndex() == 0
    win._welcome()  # not again
    assert not tour.active()


def test_the_tour_can_be_skipped_and_restarted_from_the_palette(win) -> None:
    win.start_tour()
    assert win._tour.active()
    win._tour.skip_btn.click()
    assert not win._tour.active() and win.setting("welcome_shown") is True
    win.open_palette()
    dlg = win._palette_dlg
    dlg.box.setText("tour")
    dlg._run(dlg.list.item(0))
    assert win._tour.active() and win._tour.ring.isVisible()
