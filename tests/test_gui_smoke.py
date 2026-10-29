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
        st.sub_color._pick("#FFE500")
        st.sub_bg._pick("")
        assert st._style().background is None and not st.sub_bg_opacity.isEnabled()
        st.sub_bg._pick("#000000")
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


def test_studio_undo_projects_split_zoom(qapp, tmp_path, monkeypatch) -> None:
    """Undo / redo, project save + open, split / I / O at the playhead,
    timeline zoom + snapping, and the wheel never changing a dropdown."""
    import json
    import shutil
    import subprocess

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10", "-t", "4", str(clip)], check=True)
    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        assert not st.can_undo() and not st.is_dirty()

        # undo / redo across adding, trimming and subtitle edits
        st.add_clips([str(clip)])
        st.set_trim(0, 1.0, 3.0)
        assert st.clips()[0].span() == (1.0, 3.0) and st.is_dirty()
        st.undo()
        assert st.clips()[0].span() == (0.0, 4.0)
        st.undo()
        assert st.clips() == [] and not st.can_undo()
        st.redo()
        st.redo()
        assert st.clips()[0].span() == (1.0, 3.0) and not st.can_redo()
        st.preview.seek(0.5)
        st._add_cue()
        for text in ("h", "he", "hello"):  # typing merges into one undo step
            st.cue_text.setPlainText(text)
        st.undo()  # the typing is one step...
        assert [c.text for c in st.cues()] == ["New subtitle"]
        st.undo()  # ...adding the line another
        assert st.cues() == []
        st.redo()
        st.redo()
        assert [c.text for c in st.cues()] == ["hello"]
        st.sub_size.setValue(30)
        st.undo()
        assert st.sub_size.value() == 24

        # split the clip under the playhead; both halves keep the source times
        st.preview.seek(0.5)
        st.split_clip()
        assert [c.span() for c in st.clips()] == [(1.0, 1.5), (1.5, 3.0)]
        st.undo()
        assert len(st.clips()) == 1
        st.preview.seek(0.5)  # I / O: trim the clip under the playhead
        st.trim_at_playhead("end")
        assert st.clips()[0].span() == (1.0, 1.5)
        st.undo()
        st.preview.seek(1.0)
        st.trim_at_playhead("start")
        assert st.clips()[0].span() == (2.0, 3.0)

        # save, start a new project, reopen
        st.add_clips([str(clip)])
        st.sub_color._pick("#FFE500")
        proj = tmp_path / "demo.vgproj"
        monkeypatch.setattr(win, "pick_save", lambda *_a: str(proj))
        assert st.save_project() and proj.is_file() and not st.is_dirty()
        data = json.loads(proj.read_text(encoding="utf-8"))
        assert data["app"] == "VidGrab" and len(data["clips"]) == 2
        assert data["clips"][0]["rel"] == "c.mp4" and data["style"]["color"] == "#FFE500"
        assert win.setting("recent_projects") == [str(proj)]
        st.new_project()
        assert st.clips() == [] and st.cues() == [] and st.sub_color.color() == "#FFE500"
        st.sub_color._pick("#FFFFFF")
        monkeypatch.setattr(appmod.QMessageBox, "question",
                            staticmethod(lambda *_a, **_k: appmod.QMessageBox.Discard))
        assert st.open_project(str(proj))
        assert [c.span() for c in st.clips()] == [(2.0, 3.0), (0.0, 4.0)]
        assert len(st.cues()) == 1 and st.sub_color.color() == "#FFE500"
        assert not st.is_dirty() and not st.can_undo()
        bad = tmp_path / "bad.vgproj"
        bad.write_text("nope", encoding="utf-8")
        warned = []
        monkeypatch.setattr(appmod.QMessageBox, "warning",
                            staticmethod(lambda *a, **_k: warned.append(a[2])))
        assert not st.open_project(str(bad)) and warned

        # zoom keeps the anchor in place; edges snap to the playhead
        tl = st.track
        tl.resize(1000, tl.height())
        st.fit_timeline()
        tl.set_playhead(2.0)
        x_before = tl._x(2.0)
        st.zoom_timeline(4.0)
        assert tl.zoom() == 4.0 and abs(tl._x(2.0) - x_before) < 1
        assert st.hscroll.isVisibleTo(st)
        st.fit_timeline()
        assert tl.zoom() == 1.0 and tl.view_start() == 0.0
        assert tl._snap(2.0 + 3 / tl._pps(), [2.0], free=False) == (2.0, 2.0)
        assert tl._snap(2.0 + 3 / tl._pps(), [2.0], free=True)[1] is None
        assert tl._snap(2.0 + 30 / tl._pps(), [2.0], free=False)[1] is None

        # the wheel scrolls past a dropdown instead of changing it
        combo = st.res
        idx = combo.currentIndex()
        pos = QPointF(5, 5)
        ev = QWheelEvent(pos, combo.mapToGlobal(QPoint(5, 5)).toPointF(), QPoint(0, 0),
                         QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(combo, ev)
        assert combo.currentIndex() == idx
    finally:
        win.close()


def test_trim_is_clamped_to_the_source(qapp, tmp_path, monkeypatch) -> None:
    import shutil
    import subprocess

    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10", "-t", "4", str(clip)], check=True)
    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        st.add_clips([str(clip)])
        st.set_trim(0, 40.0, 52.0)  # past the end of a 4 s source
        s, e = st.clips()[0].span()
        assert e - s >= 0.2 and e <= 4.0
    finally:
        win.close()


def test_studio_transitions_and_framing(qapp, tmp_path, monkeypatch) -> None:
    import json
    import shutil
    import subprocess

    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10", "-f", "lavfi", "-i", "sine", "-t", "4",
                    str(clip)], check=True)
    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        st.add_clips([str(clip), str(clip), str(clip)])
        assert len(st.clips()[0].thumbs) >= 2  # a filmstrip, not one repeated frame
        st.select_clip(0)
        assert st.insp.currentIndex() == st.INSP_CLIP
        assert st.trans_first.isVisibleTo(st) and not st.trans_box.isVisibleTo(st)

        # a 1 s crossfade into clip 2 overlaps it with clip 1
        st.select_clip(1)
        st.trans_btns["fade"].click()
        st.trans_len.setValue(1.0)
        assert st.track.overlaps() == [0.0, 1.0, 0.0]
        assert st.track.offsets() == [0.0, 3.0, 7.0] and st.track.total() == 11.0
        assert st.total_lbl.text().endswith("0:11.0")  # the label subtracts the overlap too
        assert abs(st.preview.duration() - 11.0) < 1e-6
        segs = st._segments()
        assert (segs[0].duration, segs[1].start, segs[1].duration) == (3.5, 0.5, 3.5)
        st._transition_for_all()
        assert [c.transition for c in st.clips()] == ["none", "fade", "fade"]
        assert st.track.total() == 10.0
        st.undo()
        assert st.track.total() == 11.0

        # framing: fill + zoom + pan reach the render request
        st.fit_btns["fill"].click()
        st.clip_zoom.setValue(150)
        st._on_pan_dragged(1, 0.1, 0.9)
        assert st.preview.canvas._pannable is (st.preview._seg_idx == 1)
        got = {}
        st.render_requested.connect(lambda task, kw: got.update(kw))
        monkeypatch.setattr(win, "_start_studio", lambda *_a: None)
        st.render()
        c1 = got["clips"][1]
        assert (c1.transition, c1.transition_duration) == ("fade", 1.0)
        assert (c1.fit, c1.zoom, c1.pan_x, c1.pan_y) == ("fill", 1.5, 0.1, 0.9)

        # ...and survive a project save / open
        proj = tmp_path / "p.vgproj"
        monkeypatch.setattr(win, "pick_save", lambda *_a: str(proj))
        st.save_project()
        saved = json.loads(proj.read_text(encoding="utf-8"))["clips"][1]
        assert saved["transition"] == "fade" and saved["fit"] == "fill"
        st.new_project()
        st.open_project(str(proj))
        c = st.clips()[1]
        assert (c.transition, c.fit, c.zoom, c.pan_x) == ("fade", "fill", 1.5, 0.1)

        # mute from the timeline header, volume from the clip panel
        st.toggle_mute(0)
        assert st.clips()[0].muted and st._segments()[0].volume == 0.0
        st.undo()
        assert not st.clips()[0].muted
        st.select_clip(2)
        st.clip_vol.setValue(50)
        st.clip_mute.setChecked(True)
        assert not st.clip_vol.isEnabled()
        got.clear()
        st.render()
        assert (got["clips"][2].volume, got["clips"][2].muted) == (0.5, True)
        assert st.project_data()["clips"][2]["muted"] is True

        # the music medley ignores per-clip transitions (it has one crossfade)
        st.mode_audio.setChecked(True)
        assert st.track.overlaps() == [0.0, 0.0, 0.0]
        assert st.insp.currentIndex() != st.INSP_CLIP
    finally:
        win.close()


def test_precise_trimming(qapp, tmp_path, monkeypatch) -> None:
    """Nudges by frame / second, typed in/out points, Shift = fine drag,
    dragging past the edge keeps extending, zoom to clip, on-demand frames."""
    import shutil
    import subprocess

    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
    from PySide6.QtTest import QTest

    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=25", "-t", "60", str(clip)], check=True)

    def wait(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        st.add_clips([str(clip)])
        assert st.clips()[0].info["fps"] == 25.0
        st.set_trim(0, 10.0, 20.0)
        st.select_clip(0)
        st._nudge("end", 0.01)  # one frame at 25 fps
        st._nudge("start", -1.0)
        assert st.clips()[0].span() == (9.0, 20.04)
        assert st.trim_fields["end"].text() == "0:20.04"
        st.trim_fields["start"].setText("0:05.5")
        st._trim_typed("start")
        assert st.clips()[0].span()[0] == 5.5
        st.undo()
        assert st.clips()[0].span()[0] == 9.0

        tl = st.track
        tl.resize(900, tl.height())
        st.fit_timeline()
        r = tl._clip_rect(0)
        y, x = int(r.center().y()), int(r.right()) - 3
        QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
        tl._trim_move(x - 100, Qt.ShiftModifier)  # a tenth as far with Shift
        pps = tl._pps()
        assert abs((20.04 - tl._drag["e"]) - 10 / pps) < 0.02
        tl._trim_move(tl.width() + 80, Qt.KeyboardModifier.NoModifier)  # past the edge
        assert tl._edge_timer.isActive()  # keeps extending while held there
        before = tl._drag["e"]
        for _ in range(15):  # step the timer by hand: CI machines tick unevenly
            tl._edge_tick()
        assert tl._drag["e"] > before + 1
        assert tl._x(tl._drag["offsets"][0] - tl._drag["s0"] + tl._drag["e"]) <= tl.width()
        QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(tl.width() + 80, y))
        assert st.clips()[0].span()[1] > before + 1

        st.zoom_to_clip()
        assert tl.zoom() >= 1.0
        assert tl._tooltip(("clip", 0, "header")).startswith("c.mp4\n")
        # tiles ask the cache for the frame at their own time
        assert tl._thumbs is st.thumbs
        assert st.thumbs.frame(str(clip), 12.3, 1.0) is None  # queued
        for _ in range(50):
            wait(100)
            if st.thumbs.frame(str(clip), 12.3, 1.0) is not None:
                break
        assert st.thumbs.frame(str(clip), 12.3, 1.0) is not None
        assert st.thumbs.nearest(str(clip), 12.9) is not None
    finally:
        win.close()


def test_preview_waits_for_the_new_source_before_seeking(qapp) -> None:
    """A stale "loaded" status from the previous file must not use up the
    seek for the new one (the playhead then sat still while the source
    played from 0:00)."""
    from vidgrab.preview import QT_MULTIMEDIA_OK, QMediaPlayer, StudioPreview

    if not QT_MULTIMEDIA_OK:
        pytest.skip("QtMultimedia not available")
    pv = StudioPreview()
    calls: list[int] = []
    pv.player.setPosition = calls.append  # type: ignore[method-assign]
    pv._pending_seek, pv._awaiting_source = 22.5, True
    pv._on_status(QMediaPlayer.MediaStatus.LoadedMedia)  # stale, from the old file
    assert pv._pending_seek == 22.5 and calls == []
    pv._awaiting_source = False
    pv._on_status(QMediaPlayer.MediaStatus.LoadedMedia)
    assert calls == [22500] and pv._seek_target == 22.5
    # reloading resets the position: the seek is queued again
    pv._on_status(QMediaPlayer.MediaStatus.LoadingMedia)
    assert pv._pending_seek == 22.5
    pv.close()


def test_preview_newest_seek_wins_while_loading(qapp, tmp_path) -> None:
    """Two quick jumps while a file is still loading: the second must win."""
    from vidgrab.preview import QT_MULTIMEDIA_OK, Segment, StudioPreview

    if not QT_MULTIMEDIA_OK:
        pytest.skip("QtMultimedia not available")
    pv = StudioPreview()
    a, b = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    pv.load_timeline([Segment(a, 0.0, 10.0, True), Segment(b, 5.0, 10.0, True)], 0.0)
    pv.seek(12.0)  # switches to b: queued until b has loaded
    assert pv._pending_seek == 7.0
    pv.seek(18.0)  # still loading b
    assert pv._pending_seek == 13.0 and abs(pv.position() - 18.0) < 1e-6
    pv.close()


def test_music_cut_offset_and_preview_bed(qapp, tmp_path, monkeypatch) -> None:
    import json
    import shutil
    import subprocess

    from PySide6.QtCore import QPointF

    from vidgrab import app as appmod
    from vidgrab.preview import MusicBed

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip, song = tmp_path / "c.mp4", tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10", "-f", "lavfi", "-i", "sine", "-t", "8",
                    str(clip)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=330", "-t", "30", str(song)], check=True)
    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        st.preview.set_muted(True)
        st.add_clips([str(clip)])
        st.set_music(str(song))
        assert st.preview.music_bed() == MusicBed(str(song), 0.0, 30.0, 0.0, True, 0.35, True)
        st.orig_vol.setValue(50)  # the clip's own sound plays at half under the music
        assert st.preview._segments[0].volume == 0.5

        # dragging the block's handles / body arrives here
        st.track.music_changed.emit(0, 10.0, 14.0, 2.0)
        bed = st.preview.music_bed()
        assert (bed.start, bed.end, bed.offset) == (10.0, 14.0, 2.0)
        assert bed.position(1.0) is None and bed.position(3.0) == 11.0
        assert bed.position(7.0) == 11.0  # looped: 2 + 4 s later it starts over
        assert st.music_fields["start"].text() == "0:10.00"
        st.music_loop.setChecked(False)
        assert st.preview.music_bed().position(7.0) is None
        st.music_fields["offset"].setText("0:01.5")
        st._music_typed("offset")
        assert st._music_cut == (10.0, 14.0, 1.5)
        st.undo()
        assert st._music_cut == (10.0, 14.0, 2.0)

        got = {}
        st.render_requested.connect(lambda task, kw: got.update(kw))
        monkeypatch.setattr(win, "_start_studio", lambda *_a: None)
        st.render()
        m = got["music"][0]
        assert (m.start, m.end, m.offset, m.loop) == (10.0, 14.0, 2.0, False)

        proj = tmp_path / "p.vgproj"
        monkeypatch.setattr(win, "pick_save", lambda *_a: str(proj))
        st.save_project()
        assert json.loads(proj.read_text(encoding="utf-8"))["music"][0]["start"] == 10.0
        st.new_project()
        assert st.preview.music_bed() is None
        st.open_project(str(proj))
        assert st._music_cut == (10.0, 14.0, 2.0)

        # the timeline: handles at the song part's edges, body moves it
        tl = st.track
        tl.resize(900, tl.height())
        st.fit_timeline()
        _block, first = tl._music_rects()
        y = first.center().y()
        assert tl._hit(QPointF(first.left() + 2, y)) == ("music", 0, "start")
        assert tl._hit(QPointF(first.right() - 2, y)) == ("music", 0, "end")
    finally:
        win.close()


def test_several_background_songs(qapp, tmp_path, monkeypatch) -> None:
    """Songs one after another (or overlapping with fades), each with its own
    part, start time and level; only the last one loops."""
    import json
    import shutil
    import subprocess

    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10", "-t", "20", str(clip)], check=True)
    songs = []
    for name, freq in (("a.wav", 330), ("b.wav", 550)):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}", "-t", "12", str(tmp_path / name)], check=True)
        songs.append(str(tmp_path / name))
    win = appmod.VidGrabWindow()
    try:
        st = win._studio
        st.preview.set_muted(True)
        st.add_clips([str(clip)])
        st.add_song(songs[0])
        st._set_song_cut(0, 0.0, 8.0, 0.0)
        st.add_song(songs[1])  # lands right after the first song's part
        assert [s.offset for s in st.songs()] == [0.0, 8.0]
        assert st._sel == ("music", 1)
        st.music_vol.setValue(80)
        st.song_fade.setValue(1.5)
        assert (st.songs()[1].volume, st.songs()[1].fade) == (80, 1.5)
        beds = st.preview.music_beds()
        assert [b.loop for b in beds] == [False, True]  # only the last song loops
        assert beds[0].position(9.0) is None and beds[1].position(9.0) == 1.0
        assert beds[1].gain(8.75, 20.0) == pytest.approx(0.8 * 0.5)  # halfway into its fade

        # the timeline shows one block per song; clicking selects that song
        assert len(st.track._music) == 2
        st.track.music_selected.emit(0)
        assert st._sel == ("music", 0) and st.music_fields["end"].text() == "0:08.00"
        st.track.music_changed.emit(1, 2.0, 12.0, 7.0)  # drag song 2 to overlap song 1
        assert (st.songs()[1].start, st.songs()[1].offset) == (2.0, 7.0)
        st.undo()
        assert st.songs()[1].offset == 8.0

        got = {}
        st.render_requested.connect(lambda task, kw: got.update(kw))
        monkeypatch.setattr(win, "_start_studio", lambda *_a: None)
        st.render()
        music = got["music"]
        assert [(m.offset, m.loop, m.volume, m.fade) for m in music] == [
            (0.0, False, 0.35, 0.0), (8.0, True, 0.8, 1.5)]

        proj = tmp_path / "p.vgproj"
        monkeypatch.setattr(win, "pick_save", lambda *_a: str(proj))
        st.save_project()
        data = json.loads(proj.read_text(encoding="utf-8"))
        assert len(data["music"]) == 2 and data["music_options"]["loop_last"] is True
        st.new_project()
        st.open_project(str(proj))
        assert [(s.offset, s.volume) for s in st.songs()] == [(0.0, 35), (8.0, 80)]

        # a 3.2 project (one song, options on it) still opens
        old = dict(data, music={**data["music"][0], "volume": 50, "original_volume": 40,
                                "loop": False, "fade_out": False})
        old.pop("music_options")
        legacy = tmp_path / "old.vgproj"
        legacy.write_text(json.dumps(old), encoding="utf-8")
        st.open_project(str(legacy))
        assert len(st.songs()) == 1 and st.songs()[0].volume == 50
        assert st.orig_vol.value() == 40 and not st.music_loop.isChecked()

        st.select_music(0)
        st._delete_selected()
        assert st.songs() == []
    finally:
        win.close()
