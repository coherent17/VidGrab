"""Library, Tools and Subscriptions pages in the window."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    from vidgrab import app as m

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    cfg = tmp_path / "cfg"
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(m, "_config_dir", lambda: cfg)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15",
                    "-f", "lavfi", "-i", "sine", "-t", "3", str(media / "clip one.mp4")], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine", "-t", "2",
                    str(media / "song.mp3")], check=True)
    w = m.VidGrabWindow()
    w._settings["out_dir"] = str(media)
    try:
        yield w, m, media
    finally:
        w._studio.clear_autosave()
        w._studio.shutdown()
        for page in (w._library, w._tools, w._subs):
            page.shutdown()
        w.close()


def _wait(app, cond, seconds=20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


def test_library_lists_filters_and_sends_to_studio(win, qapp) -> None:
    w, m, _media = win
    w._sidebar.select(m.PAGE_LIBRARY)
    lib = w._library
    assert lib.list.count() == 2 and not lib.actions["open"].isEnabled()
    lib.chips.buttons["audio"].click()
    assert lib.list.count() == 1 and lib.list.item(0).text().startswith("song")
    lib.chips.buttons["all"].click()
    lib.search.setText("clip")
    assert lib.list.count() == 1
    lib.list.setCurrentRow(0)
    assert lib.actions["open"].isEnabled()
    lib.actions["studio"].click()
    assert w._stack.currentIndex() == m.PAGE_STUDIO and len(w._studio.clips()) == 1
    lib.search.setText("zzz")
    assert lib.list.count() == 0 and lib.empty.isVisibleTo(lib)


def test_library_delete_asks_first(win, monkeypatch) -> None:
    w, m, media = win
    w._sidebar.select(m.PAGE_LIBRARY)
    lib = w._library
    lib.search.setText("song")
    lib.list.setCurrentRow(0)
    monkeypatch.setattr(m.QMessageBox, "question", staticmethod(lambda *_a, **_k: m.QMessageBox.No))
    lib.actions["delete"].click()
    assert (media / "song.mp3").exists()
    monkeypatch.setattr(m.QMessageBox, "question", staticmethod(lambda *_a, **_k: m.QMessageBox.Yes))
    lib.actions["delete"].click()
    assert not (media / "song.mp3").exists()


def test_tools_shrink_runs_in_the_background(win, qapp) -> None:
    w, _m, media = win
    tp = w._tools
    tp.set_file(str(media / "clip one.mp4"))
    tp.select_tool("compress")
    assert tp.run_btn.isEnabled() and tp.info.text().endswith("3 s")
    tp.size_combo.setCurrentIndex(0)  # 8 MB
    tp.run_btn.click()
    assert tp.run_btn.text() == "Cancel"
    assert _wait(qapp, lambda: not tp._running)
    out = media / "clip one (8 MB).mp4"
    assert out.is_file() and tp.status.text().startswith("Done") and tp.show_btn.isVisibleTo(tp)


def test_tools_make_a_short_renders_vertical_and_reports_progress(win, qapp, monkeypatch) -> None:
    w, _m, media = win
    monkeypatch.setattr(w, "models_dir", lambda: media)
    tp = w._tools
    assert tp._tool == "short"  # the first tile
    tp.set_file(str(media / "clip one.mp4"))
    tp.short_follow.setChecked(False)
    tp.short_caps.setChecked(False)
    tp.run_btn.click()
    assert tp.run_btn.text() == "Cancel"
    assert _wait(qapp, lambda: not tp._running, 60)
    out = media / "clip one (short).mp4"
    assert out.is_file() and tp.status.text().startswith("Done")
    from vidgrab import studio

    assert studio.probe_media(out)["duration"] > 2


def test_tools_convert_gif_audio_and_thumbnail(win, qapp) -> None:
    w, _m, media = win
    tp = w._tools
    tp.set_file(str(media / "clip one.mp4"))
    tp.select_tool("audio")
    tp.run_btn.click()
    assert _wait(qapp, lambda: not tp._running) and (media / "clip one (audio).mp3").is_file()
    tp.select_tool("gif")
    tp.gif_len.setValue(1)
    tp.run_btn.click()
    assert _wait(qapp, lambda: not tp._running) and (media / "clip one (gif).gif").is_file()
    tp.select_tool("thumbnail")
    tp.th_text.setText("HELLO")
    tp.run_btn.click()
    png = media / "clip one (thumbnail).png"
    assert png.is_file()
    from PySide6.QtGui import QImage

    img = QImage(str(png))
    assert img.height() == 720 and img.width() >= 1000


def test_tools_cancel_and_errors(win, qapp) -> None:
    w, _m, media = win
    tp = w._tools
    tp.set_file(str(media / "clip one.mp4"))
    tp.select_tool("convert")
    tp.convert_fmt.setCurrentIndex(tp.convert_fmt.findData("webm"))  # slow VP9: time to press Cancel
    tp.run_btn.click()
    tp.run_btn.click()
    assert _wait(qapp, lambda: not tp._running)
    assert tp.status.text() in ("Cancelled",) or tp.status.text().startswith("Done")
    tp.set_file(str(media / "nothing.mp4"))
    assert not (media / "nothing (converted).webm").exists()


def test_library_opens_the_tool(win) -> None:
    w, m, media = win
    w.open_tool(str(media / "song.mp3"))
    assert w._stack.currentIndex() == m.PAGE_TOOLS and w._tools.file.text().endswith("song.mp3")


def test_subscriptions_follow_feed_and_download(win, qapp, monkeypatch) -> None:
    from vidgrab import subscriptions as sb

    w, m, _media = win
    items = [sb.FeedItem("a2", "New one", "https://y/a2", 65), sb.FeedItem("a1", "Old one", "https://y/a1", 5)]
    monkeypatch.setattr(sb, "fetch", lambda url, limit=15: ("Ada", items))
    w._subs_loaded = True
    s = w._subs
    s.url.setText("https://www.youtube.com/@ada")
    s.add_btn.click()
    assert _wait(qapp, lambda: s.feed.count() == 2)
    assert s.title.text() == "Ada" and "0 new" in s.status.text()  # first look: nothing is "new"
    # a later look finds one more
    items.insert(0, sb.FeedItem("a3", "Fresh", "https://y/a3", 10))
    s.refresh_current()
    assert _wait(qapp, lambda: s.feed.count() == 3)
    assert "1 new" in s.status.text() and s.sub_list.item(0).text().endswith("● 1")
    s._tick_new()
    assert s.ticked() == ["https://y/a3"]
    got = []
    monkeypatch.setattr(w, "_start_download", lambda: got.append(w._url.text()))
    s.get_btn.click()
    assert got == ["https://y/a3"] and w._stack.currentIndex() == m.PAGE_DOWNLOAD
    assert sb.load(w._subs._path)[0].seen == ["a2", "a1", "a3"]
    s.remove_btn.click()
    assert not s.subs and sb.load(w._subs._path) == []


def test_help_buttons_reach_the_new_pages(win) -> None:
    w, m, _media = win
    for name, page in (("library", m.PAGE_LIBRARY), ("tools", m.PAGE_TOOLS), ("subscriptions", m.PAGE_SUBS)):
        w._go_page(name)
        assert w._stack.currentIndex() == page


def test_subscriptions_guides_the_user_and_does_not_retry_forever(win, qapp, monkeypatch) -> None:
    from vidgrab import subscriptions as sb

    w, _m, _media = win
    s = w._subs
    calls = []

    def boom(url, limit=15):
        calls.append(url)
        raise RuntimeError("HTTP 404")

    monkeypatch.setattr(sb, "fetch", boom)
    assert "Paste a channel" in s.status.text() or "How it works" in s.status.text()
    s.add_btn.click()  # empty box
    assert "https://" in s.status.text() and not s.subs
    s.url.setText("https://www.youtube.com/watch?v=abc")
    s.add_btn.click()
    assert "one video" in s.status.text() and not s.subs
    s.url.setText("https://www.youtube.com/@x")
    s.add_btn.click()
    assert _wait(qapp, lambda: "HTTP 404" in s.status.text())
    qapp.processEvents()
    assert len(calls) == 1  # no automatic retry loop
    s.url.setText("https://www.youtube.com/@x")
    s.add_btn.click()
    assert "already" in s.status.text()
    s.refresh_current()
    assert _wait(qapp, lambda: len(calls) == 2)


def test_ctrl_v_pastes_into_the_focused_box_not_the_download_link(win, qapp) -> None:
    w, m, _media = win
    w.show()
    w._sidebar.select(m.PAGE_SUBS)
    w._url.setText("keep me")
    qapp.clipboard().setText("https://www.youtube.com/@pasted")
    w._subs.url.setFocus()
    qapp.processEvents()
    w._paste_url()
    assert w._subs.url.text() == "https://www.youtube.com/@pasted" and w._url.text() == "keep me"
    w._subs.url.clearFocus()
    w._subs.url.clear()
    w._sidebar.select(m.PAGE_SETTINGS)
    w._paste_url()
    assert w._url.text() == "keep me"  # other pages leave the link box alone


def test_fuzzy_search_in_help_library_and_download_box(win, qapp) -> None:
    from vidgrab.downloads_panel import DONE, DownloadItem
    from vidgrab.jobs import DownloadJob

    w, m, _media = win
    # Library: a typo still finds the file, the popup offers the best names
    w._sidebar.select(m.PAGE_LIBRARY)
    w._library.search.setText("cilp on")
    assert w._library.list.count() == 1 and w._library.list.item(0).text().startswith("clip one")
    w._library.search.setText("sogn")
    assert w._library.list.count() == 1 and w._library.list.item(0).text().startswith("song")
    w._library.search.setText("qqqqqq")
    assert w._library.list.count() == 0
    # Help: ranked, with a "did you mean" when nothing matches
    h = w._help
    h.home_search.setText("captoins")
    assert h.current_id() == "captions_auto" and h.topic_list.item(0).text() == "BEST MATCHES"
    h.search.setText("shrnk")
    assert h.current_id() == "tools_shrink"
    h.search.setText("zzzzqqq")
    assert h.current_id() is None
    # the download box: earlier searches and downloaded titles
    w._remember_search("lofi hip hop radio")
    w._remember_search("Lofi Hip Hop Radio")  # the same one: kept once
    assert w.setting("recent_searches") == ["Lofi Hip Hop Radio"]
    item = DownloadItem(job=DownloadJob(url="https://y/1", output_dir="/tmp", fmt="mp4"), title="Hip hop beats mix",
                        status=DONE)
    w._queue.append(item)
    assert w._url_suggestions("hip hopp")[:2] == ["Lofi Hip Hop Radio", "Hip hop beats mix"] or \
        set(w._url_suggestions("hip hopp")) == {"Lofi Hip Hop Radio", "Hip hop beats mix"}
    assert w._url_suggestions("https://youtube.com/watch?v=x") == [] and w._url_suggestions("a") == []
    w._queue.remove(item)


def test_suggestions_pop_up_while_typing(win, qapp) -> None:
    w, m, _media = win
    w.show()
    w._sidebar.select(m.PAGE_DOWNLOAD)
    w._remember_search("lofi hip hop radio")
    w._remember_search("lofi girl study")
    box = w._url
    box.setFocus()
    qapp.processEvents()
    box.setText("lof")
    box.textEdited.emit("lof")  # what typing does
    qapp.processEvents()
    popup = box.suggestions.popup
    assert popup.isVisible() and popup.model().rowCount() == 2
    box.setText("zzzzz")
    box.textEdited.emit("zzzzz")
    qapp.processEvents()
    assert not popup.isVisible()
    box.setText("https://youtube.com/watch?v=x")
    box.textEdited.emit("https://youtube.com/watch?v=x")
    qapp.processEvents()
    assert not popup.isVisible()  # a link gets no suggestions
