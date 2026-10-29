"""Headless smoke test that constructs the real PySide6 UI.

Runs only when SMOKE_GUI=1 (e.g. QT_QPA_PLATFORM=offscreen).
Catches PySide6 API misuse and layout errors that a plain import misses.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOKE_GUI") != "1",
    reason="set SMOKE_GUI=1 to enable",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_window_constructs_and_destroys(qapp, monkeypatch) -> None:
    monkeypatch.setattr(
        "vidgrab.app.check_internet",
        lambda timeout=2.5: type("S", (), {"online": True, "reason": "mock"})(),
    )
    from vidgrab import app as appmod

    win = appmod.VidGrabWindow()
    try:
        assert win.windowTitle() == "VidGrab"
        assert win._stack.count() == 3  # Download, Studio, Settings
        assert win._stack.currentIndex() == appmod.PAGE_DOWNLOAD
        assert not win._bottom.isHidden()
        win._switch_page(appmod.PAGE_STUDIO)
        assert win._stack.currentIndex() == appmod.PAGE_STUDIO
        # the Studio has its own toolbar; the download log/button panel hides
        assert win._bottom.isHidden()
        win._switch_page(appmod.PAGE_DOWNLOAD)
        assert not win._bottom.isHidden()
    finally:
        win.close()


def test_theme_toggle(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    appmod._save_config("dark")
    win = appmod.VidGrabWindow()
    try:
        assert win._theme == "dark"
        win._toggle_theme()
        assert win._theme == "light"
        assert appmod._load_config()["theme"] == "light"
        win._toggle_theme()
        assert win._theme == "dark"
    finally:
        win.close()


def test_lang_toggle(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    appmod._save_config("dark", "en")
    win = appmod.VidGrabWindow()
    try:
        assert win._lang == "en"
        assert win._theme_btn.text() in ("\u2600 Light", "\u2600 \u6dfa\u8272")
        win._lang_combo.setCurrentIndex(win._lang_combo.findData("zh"))  # 繁體中文
        assert win._lang == "zh"
        assert "\u6dfa\u8272" in win._theme_btn.text()  # 淺色
        assert "\u5916\u89c0" in win._settings_title.text()  # 外觀
        assert "\u4e0b\u8f09\u6e05\u55ae" in win._log_title.text()  # 下載清單
        cfg = appmod._load_config()
        assert cfg["lang"] == "zh"
        assert cfg["theme"] == "dark"
    finally:
        win.close()


def test_bundled_fonts_register(qapp) -> None:
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    from vidgrab import app as appmod

    appmod._register_bundled_fonts()
    families = set(QFontDatabase.families())
    assert "Noto Sans CJK TC" in families, "bundled font not registered"

    assets = Path(appmod.__file__).resolve().parent.parent / "assets"
    assert (assets / "NotoSansTC-Regular.otf").is_file(), "font asset missing"

def test_studio_page(qapp, tmp_path, monkeypatch) -> None:
    """Studio: one timeline row per clip, trimming with the start / end
    handles, reordering, subtitles placed at the playhead and positioned by
    dragging in the preview."""
    import shutil
    import subprocess

    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    win = appmod.VidGrabWindow()
    try:
        win._switch_page(appmod.PAGE_STUDIO)
        st = win._studio
        assert win._page_title.text() == "Studio"
        assert "Render" in st.render_btn.text()

        st.mode_audio.setChecked(True)
        assert st.add_sub_btn.isHidden() and st.xfade.isVisibleTo(st)
        st.mode_video.setChecked(True)
        assert not st.add_sub_btn.isHidden() and st.res.isVisibleTo(st)

        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            return
        clip = tmp_path / "c.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "testsrc=size=160x120:rate=10", "-t", "4", str(clip)],
            check=True,
        )
        st.add_clips([str(clip), str(clip)])
        assert len(st.clips()) == 2
        rows = [r for r in st.track._rows() if r[0] == "clip"]
        assert len(rows) == 2  # every clip gets its own row
        assert st.clips()[0].thumb is not None  # thumbnail in the block

        # dragging handles: live preview, then commit
        st.track.clip_trimming.emit(0, 1.0, 4.0, "start")
        assert abs(st.preview.position() - 0.0) < 0.05  # clip 0 starts the montage
        st.track.clip_trimmed.emit(0, 1.0, 3.0)
        assert st.clips()[0].span() == (1.0, 3.0)
        assert st.track.total() == 2.0 + 4.0
        assert abs(st.preview.duration() - 6.0) < 1e-6

        # reorder by dragging the block to the other row
        st.track.clip_moved.emit(0, 1)
        assert st._sel == ("clip", 1) and st.clips()[1].span() == (1.0, 3.0)

        # subtitle at the playhead
        st.preview.seek(2.0)
        st._add_cue()
        assert st._sel == ("cue", 0)
        st.cue_text.setPlainText("\u4f60\u597d hello")
        cue = st.cues()[0]
        assert (cue.start, cue.end, cue.text) == (2.0, 5.0, "\u4f60\u597d hello")

        # drag in the preview -> custom position, used for every line on request
        st._on_cue_moved(0, 0.25, 0.1)
        assert (st.cues()[0].x, st.cues()[0].y) == (0.25, 0.1)
        st.preview.seek(5.5)
        st._add_cue()
        st.select_cue(0)
        st._apply_pos_all()
        assert all((c.x, c.y) == (0.25, 0.1) for c in st._cues)
        st._reset_cue_pos()
        assert st._cues[0].x is None

        # text colour + background box (or none) reach the render request
        st.sub_color.setCurrentIndex(st.sub_color.findData("#FFE500"))
        st._color_picked(st.sub_color)
        st.sub_bg.setCurrentIndex(st.sub_bg.findData(""))
        st._color_picked(st.sub_bg)
        assert st._style().background is None and not st.sub_bg_opacity.isEnabled()
        st.sub_bg.setCurrentIndex(st.sub_bg.findData("#000000"))
        st._color_picked(st.sub_bg)
        st.sub_bg_opacity.setValue(80)
        style = st._style()
        assert (style.color, style.background, style.bg_opacity) == ("#FFE500", "#000000", 0.8)

        # quick position grid, split at playhead, duplicate, shared style
        st.select_cue(0)
        st._set_anchor(9)
        cue0 = st._cues[0]
        assert (cue0.anchor, cue0.x, cue0.y) == (9, 0.95, 0.05)
        assert st._anchor_btns[9].isChecked() and not st._anchor_btns[5].isChecked()
        n = len(st._cues)
        st.preview.seek(cue0.start + 1.0)
        st._split_cue()
        assert len(st._cues) == n + 1
        first, second = sorted(st._cues, key=lambda c: c.start)[:2]
        assert first.end == second.start and second.anchor == 9
        st._duplicate_cue()
        assert len(st._cues) == n + 2
        st.sub_bold.setChecked(True)
        st.sub_fade.setValue(0.3)
        assert st._style().bold and st._style().fade == 0.3
        assert st.sub_font.itemData(0) == "Noto Sans CJK TC"
        st.deselect()
        st._cues[:] = sorted(st._cues, key=lambda c: c.start)[:1] + [
            c for c in st._cues if c.start >= 5.5][:n - 1]
        st._cues_changed()

        # dragging a subtitle block on the timeline changes its timing
        st._on_cue_dragged(0, 0.5, 1.5)
        assert (st._cues[0].start, st._cues[0].end) == (0.5, 1.5)

        # render request carries clips, subtitles and output settings
        got = {}
        st.render_requested.connect(lambda task, kw: got.update(task=task, **kw))
        monkeypatch.setattr(win, "_start_studio", lambda *_a: None)
        st.render()
        assert got["task"] == "compose_video"
        assert [c.start for c in got["clips"]] == [None, "1.0"]
        assert len(got["subtitles"]) == 2

        win._lang_combo.setCurrentIndex(win._lang_combo.findData("zh"))
        assert win._page_title.text() == "\u526a\u8f2f\u5de5\u4f5c\u5ba4"
    finally:
        win.close()


def test_timeline_handles_trim_clip(qapp) -> None:
    """Mouse-dragging a clip's right handle in the timeline shortens it."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from vidgrab.studio_page import TrackTimeline, _MediaClip

    tl = TrackTimeline()
    tl.resize(900, 300)
    clip = _MediaClip("a.mp4", {"duration": 10.0, "has_video": True})
    tl.set_data([clip], [], None)
    tl.show()
    done = []
    tl.clip_trimmed.connect(lambda row, s, e: done.append((row, s, e)))
    rect = tl._clip_rect(0)
    y = int(rect.center().y())
    start = QPoint(int(rect.right()) - 2, y)
    end = QPoint(int(rect.left() + rect.width() * 0.5), y)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(tl, end)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, end)
    assert done and done[0][0] == 0 and done[0][1] == 0.0
    assert 4.5 < done[0][2] < 5.5  # dragged to about half way
    tl.close()


def test_preview_canvas_drag_positions_subtitle(qapp) -> None:
    """Dragging a subtitle on the canvas emits its new centre as fractions."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from vidgrab.preview import VideoCanvas
    from vidgrab.studio import SubtitleCue

    canvas = VideoCanvas()
    canvas.resize(640, 360)
    canvas.set_aspect(1280, 720)
    canvas.set_cues([(3, SubtitleCue(0, 5, "drag me"))], None)
    canvas.show()
    canvas.grab()  # paint once so the text's hit box exists
    moved = []
    canvas.cue_moved.connect(lambda row, x, y: moved.append((row, x, y)))
    _row, box = canvas._hits[0]
    start = box.center().toPoint()
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(canvas, QPoint(160, 90))
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(160, 90))
    assert moved and moved[0][0] == 3
    _, x, y = moved[0]
    assert abs(x - 0.25) < 0.03 and abs(y - 0.25) < 0.03
    canvas.close()


def test_dialogs_follow_theme(qapp, tmp_path, monkeypatch) -> None:
    """Qt's own dialogs (file picker, message boxes) take colors from the app
    palette, which must track the theme or they render half dark / half light."""
    from PySide6.QtGui import QPalette

    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    win = appmod.VidGrabWindow()
    try:
        for theme in ("dark", "light"):
            win._set_theme(theme)
            pal = qapp.palette()
            colors = appmod._PALETTES[theme]
            assert pal.color(QPalette.Window).name() == colors["SURFACE"]
            assert pal.color(QPalette.Base).name() == colors["FIELD"]
            assert pal.color(QPalette.Text).name() == colors["TEXT"]
        assert win._start_dir() != str(appmod.get_app_dir())
    finally:
        win.close()


def test_download_queue_history_and_send_to_studio(qapp, tmp_path, monkeypatch) -> None:
    """Several pasted links queue up, run one by one, land in the saved
    history, and a finished video can be sent to the Studio."""
    import shutil
    import subprocess

    from vidgrab import app as appmod
    from vidgrab.downloads_panel import DONE, load_history

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "vidgrab.app.check_internet",
        lambda timeout=2.5: type("S", (), {"online": True, "reason": "mock"})(),
    )
    have_ff = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    clip = tmp_path / "video.mp4"
    if have_ff:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=160x120:rate=10", "-t", "2", str(clip)], check=True)
    else:
        clip.write_bytes(b"x")
    seen = []

    def fake_run_job(job, *, on_progress=None, on_log=None, translate=None):
        seen.append(job)
        on_progress("Downloading", 50.0)
        return [clip]

    monkeypatch.setattr(appmod, "run_job", fake_run_job)
    monkeypatch.setattr(appmod, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(appmod.VidGrabWindow, "_probe_item", lambda self, item: None)
    win = appmod.VidGrabWindow()
    try:
        win._apply_internet(type("S", (), {"online": True, "reason": "mock"})())
        win._url.setText("https://youtu.be/aaa https://youtu.be/bbb")
        assert len(win._links()) == 2
        win._sub_cb.setChecked(True)
        win._start_download()
        assert win._url.text() == ""
        assert len(win._queue) == 2
        for _ in range(200):  # let the worker threads finish
            qapp.processEvents()
            if all(i.status == DONE for i in win._queue):
                break
            win._dl_worker and win._dl_worker.wait(50)
        assert all(i.status == DONE for i in win._queue)
        assert [j.url for j in seen] == ["https://youtu.be/aaa", "https://youtu.be/bbb"]
        assert seen[0].subtitles == "zh-Hant" and not seen[0].burn_subtitles
        assert len(load_history(tmp_path / "history.json")) == 2

        row = win._downloads.row(win._queue[0].id)
        assert row._btns["studio"].isVisibleTo(row)
        if have_ff:
            win._on_download_action(win._queue[0].id, "studio")
            assert win._stack.currentIndex() == appmod.PAGE_STUDIO
            assert len(win._studio.clips()) == 1

        win._clear_finished()
        assert win._queue == [] and load_history(tmp_path / "history.json") == []
    finally:
        win.close()


def test_connection_is_rechecked(qapp, tmp_path, monkeypatch) -> None:
    """The online check repeats: fast while offline, slower while online."""
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    win = appmod.VidGrabWindow()
    try:
        status = type("S", (), {"reason": "mock"})
        status.online = False
        win._apply_internet(status())
        assert win._recheck.isActive()
        assert win._recheck.interval() == win._RECHECK_OFFLINE_MS
        assert not win._action.isEnabled()
        status.online = True
        win._apply_internet(status())
        assert win._recheck.interval() == win._RECHECK_ONLINE_MS
        assert win._action.isEnabled()
    finally:
        win.close()


def test_multiple_links_preview_and_queue(qapp, tmp_path, monkeypatch) -> None:
    """Pasting several links lists each one (details fetched once, cached),
    a link can be dropped with its \u2715, and Download queues the rest
    using the cached titles and each playlist's own choice."""
    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(appmod, "find_ffmpeg", lambda: "ffmpeg")
    looked_up = []
    infos = {
        "https://youtu.be/a": {"title": "Video A", "duration": 65, "is_playlist": False},
        "https://youtu.be/b": {"title": "Video B", "duration": 5, "is_playlist": False},
        "https://youtube.com/playlist?list=P": {"title": "My list", "is_playlist": True,
                                                "playlist_count": 3},
    }

    def fake_probe_link(self, url):
        looked_up.append(url)
        self._probe_cache[url] = infos[url]
        self._link_rows[url][1].set_info(infos[url])

    monkeypatch.setattr(appmod.VidGrabWindow, "_probe_link", fake_probe_link)
    monkeypatch.setattr(appmod.VidGrabWindow, "_run_next_job", lambda self: None)
    win = appmod.VidGrabWindow()
    try:
        win._apply_internet(type("S", (), {"online": True, "reason": "m"})())
        win._url.setText("https://youtu.be/a\nhttps://youtu.be/b\nhttps://youtube.com/playlist?list=P")
        assert "\n" not in win._url.text()  # pasted line breaks become spaces
        win._start_probe()
        assert win._info_stack.currentIndex() == 1
        assert win._link_list.count() == 3
        assert "3" in win._multi_lbl.text()
        pl_row = win._link_rows["https://youtube.com/playlist?list=P"][1]
        assert pl_row.playlist_cb.isVisibleTo(pl_row) and pl_row.whole_playlist()

        win._remove_link("https://youtu.be/b")
        assert win._links() == ["https://youtu.be/a", "https://youtube.com/playlist?list=P"]
        assert win._link_list.count() == 2
        win._start_probe()  # re-rendering uses the cache, no new lookups
        assert looked_up.count("https://youtu.be/a") == 1

        pl_row.playlist_cb.setChecked(False)
        win._start_download()
        jobs = [(i.title, i.job.playlist) for i in win._queue]
        assert jobs == [("Video A", False), ("My list", False)]
        assert win._info_stack.currentIndex() == 0 and win._link_list.count() == 0
    finally:
        win.close()


def test_settings_defaults_presets_and_storage(qapp, tmp_path, monkeypatch) -> None:
    """Old config files keep working; Settings drive the Download page and
    the Studio; subtitle presets round-trip; storage tools work."""
    import json

    from vidgrab import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"theme": "light", "lang": "en"}))
    cfg = appmod._load_config()
    assert cfg["theme"] == "light" and cfg["fmt"] == "mp4" and cfg["notify"] is True
    appmod._save_config("light", "en", {"render_quality": "high"})
    assert appmod._load_config()["render_quality"] == "high"
    appmod._save_config("dark", "en")  # theme-only saves keep the other settings
    assert appmod._load_config()["render_quality"] == "high"

    win = appmod.VidGrabWindow()
    try:
        # format default -> Download page checkboxes + quality list
        win._set_fmt.setCurrentIndex(win._set_fmt.findData("mp3"))
        win._default_changed("fmt", win._set_fmt)
        assert win._mp3.isChecked() and not win._mp4.isChecked()
        assert win._quality.currentData() == "192"
        # subtitles + file-name pattern
        win._set_sub.setChecked(True)
        assert win._sub_cb.isChecked()
        win._set_name.setCurrentIndex(win._set_name.findData("uploader_title"))
        win._default_changed("name_template", win._set_name)
        assert "jawed - Me at the zoo" in win._set_name_example.text()
        # studio defaults
        win._set_res.setCurrentIndex(win._set_res.findData("720p"))
        win._default_changed("studio_resolution", win._set_res)
        assert win._studio.res.currentData() == "720p"
        assert appmod._load_config()["studio_resolution"] == "720p"

        # subtitle presets: save from the Studio, apply, delete from Settings
        st = win._studio
        st.sub_size.setValue(40)
        st.sub_bold.setChecked(True)
        win.save_subtitle_preset("Big titles", st._style_dict())
        assert win._set_presets.count() == 1
        st.sub_size.setValue(20)
        st.sub_bold.setChecked(False)
        st.apply_preset("Big titles")
        assert st.sub_size.value() == 40 and st.sub_bold.isChecked()
        win._set_presets.setCurrentRow(0)
        win._delete_preset_from_settings()
        assert win.subtitle_presets() == {}

        # storage
        (tmp_path / "cache").mkdir(exist_ok=True)
        (tmp_path / "cache" / "t.jpg").write_bytes(b"x" * 2048)
        win._refresh_storage()
        assert "2.0 KB" in win._cache_lbl.text()
        win._clear_cache()
        assert not (tmp_path / "cache").exists()

        # 'downloads finished' fires once the queue empties
        seen = []
        monkeypatch.setattr(win, "_notify_downloads_done", lambda n: seen.append(n))
        win._finished_since_idle = 2
        win._run_next_job()
        assert seen == [2] and win._finished_since_idle == 0
    finally:
        win.close()
