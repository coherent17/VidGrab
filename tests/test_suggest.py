from __future__ import annotations

import json
import os
import time

import pytest

from vidgrab import suggest


class _Resp:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> None: ...


def test_youtube_suggestions_parse_and_never_raise(monkeypatch) -> None:
    seen = []

    class FakeOpener:
        def open(self, req, timeout=None):
            seen.append(req.full_url)
            return _Resp(json.dumps(["lofi", ["lofi", "lofi girl", 3, "lofi jazz"], []]).encode())

    monkeypatch.setattr(suggest.urllib.request, "build_opener", lambda *a: FakeOpener())
    out = suggest.youtube_suggestions("lofi", lang="en")
    assert out == ["lofi", "lofi girl", "lofi jazz"] and "q=lofi" in seen[0] and "ds=yt" in seen[0]
    assert suggest.youtube_suggestions("  ") == []

    class Broken:
        def open(self, req, timeout=None):
            raise OSError("offline")

    monkeypatch.setattr(suggest.urllib.request, "build_opener", lambda *a: Broken())
    assert suggest.youtube_suggestions("lofi") == []

    class Junk:
        def open(self, req, timeout=None):
            return _Resp(b"<html>")

    monkeypatch.setattr(suggest.urllib.request, "build_opener", lambda *a: Junk())
    assert suggest.youtube_suggestions("lofi") == []


def test_merge_puts_your_own_searches_first_without_repeats() -> None:
    assert suggest.merge(["Lofi Girl", "lofi cafe"], ["lofi girl", "lofi jazz", "lofi cafe"], 3) == \
        ["Lofi Girl", "lofi cafe", "lofi jazz"]


pytestmark_gui = pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytestmark_gui
def test_download_box_shows_youtube_suggestions_while_typing_and_a_pick_searches(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as m

    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    asked = []
    monkeypatch.setattr(suggest, "youtube_suggestions",
                        lambda q, **kw: asked.append(q) or [f"{q} girl", f"{q} jazz", f"{q} music"])
    w = m.VidGrabWindow()
    try:
        w.show()
        w._sidebar.select(m.PAGE_DOWNLOAD)
        box = w._url
        box.setFocus()
        qapp.processEvents()
        box.setText("lofi")
        box.textEdited.emit("lofi")
        popup = box.suggestions.popup
        end = time.time() + 5
        while time.time() < end and not (popup.isVisible() and popup.model().rowCount() == 3):
            qapp.processEvents()
            time.sleep(0.02)
        assert asked == ["lofi"]
        assert popup.isVisible() and [popup.model().index(i, 0).data() for i in range(3)] == \
            ["lofi girl", "lofi jazz", "lofi music"]
        # picking one is the search: no Enter
        started = []
        monkeypatch.setattr(w, "_start_action", lambda: started.append(box.text()))
        box.suggestions.pick("lofi jazz")
        assert box.text() == "lofi jazz" and started == ["lofi jazz"]
        # a link is never sent, and the switch turns it all off
        asked.clear()
        assert w._online_suggestions("https://youtube.com/watch?v=x") == [] and not asked
        w.set_setting("online_suggest", False)
        assert w._online_suggestions("lofi") == [] and not asked
        assert w._set_suggest is not None
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()


@pytestmark_gui
def test_the_list_goes_away_on_a_choice_and_late_answers_do_not_bring_it_back(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as m

    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)

    def slow(q, **kw):
        time.sleep(0.5)
        return [f"{q} girl", f"{q} jazz"]

    monkeypatch.setattr(suggest, "youtube_suggestions", slow)
    w = m.VidGrabWindow()
    try:
        w.show()
        w._sidebar.select(m.PAGE_DOWNLOAD)
        monkeypatch.setattr(w, "_start_action", lambda: None)
        box = w._url
        box.setFocus()
        qapp.processEvents()
        w._remember_search("lofi girl")
        box.setText("lofi")
        box.textEdited.emit("lofi")
        popup = box.suggestions.popup
        qapp.processEvents()
        assert popup.isVisible()  # your own searches, at once
        box.suggestions.pick("lofi")  # chosen, while YouTube's answer is still coming
        assert not popup.isVisible()
        end = time.time() + 1.5
        while time.time() < end:  # the late answer arrives and must not reopen it
            qapp.processEvents()
            time.sleep(0.02)
        assert not popup.isVisible()
        # typing again brings it back; Enter closes it
        box.textEdited.emit("lofi")
        qapp.processEvents()
        assert popup.isVisible()
        box.returnPressed.emit()
        assert not popup.isVisible()
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()


@pytestmark_gui
def test_keyboard_choice_searches_once_closes_the_list_and_it_comes_back(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vidgrab import app as m

    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(suggest, "youtube_suggestions", lambda q, **kw: [f"{q} girl", f"{q} jazz"])
    w = m.VidGrabWindow()
    try:
        w.show()
        w._sidebar.select(m.PAGE_DOWNLOAD)
        started: list[str] = []
        monkeypatch.setattr(w, "_start_action", lambda: started.append(w._url.text()))
        box = w._url
        box.setFocus()
        pop = box.suggestions.popup

        def settle(ms: int) -> None:
            end = time.time() + ms / 1000
            while time.time() < end:
                qapp.processEvents()
                time.sleep(0.01)

        for _round in range(3):  # it must not be a one-off
            box.clear()
            QTest.keyClicks(box, "kilo")
            settle(600)
            assert pop.isVisible() and pop.count() == 2
            QTest.keyClick(box, Qt.Key_Down)
            QTest.keyClick(box, Qt.Key_Enter)
            settle(500)
            assert not pop.isVisible()
            assert started[-1] == "kilo girl"
        assert len(started) == 3  # Enter on a choice starts exactly one search each time
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()
