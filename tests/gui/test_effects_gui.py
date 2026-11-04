"""The Effects tab, picture movement and text styles in the Studio window."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

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


@pytest.fixture
def studio_win(qapp, tmp_path, monkeypatch):
    from vidgrab import app as appmod

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(appmod.QMessageBox, "question",
                        staticmethod(lambda *_a, **_k: appmod.QMessageBox.Discard))
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=10", "-f", "lavfi", "-i", "sine", "-t", "2",
                    str(clip)], check=True)
    win = appmod.VidGrabWindow()
    st = win._studio
    st.add_clips([str(clip), str(clip)])
    st.render_requested.disconnect()  # (the window would start a real render)
    st.host.ffmpeg_ok = lambda: True
    try:
        yield st, tmp_path
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()


def test_effects_tab_edits_one_clip_undoably(studio_win) -> None:
    st, _tmp = studio_win
    st.select_clip(0)
    assert [b.text() for b in st.clip_tab_btns][-1] == "Effects"
    st.fx_look_btns["warm"].click()
    st.fx_sliders["sharpen"].setValue(40)
    st.fx_stab.setChecked(True)
    assert st._clips[0].fx == {"look": "warm", "sharpen": 0.4, "stabilize": True}
    assert st._clips[1].fx == {}  # only the selected clip
    st.undo()
    st.undo()
    st.undo()
    assert st._clips[0].fx == {}
    st.redo()
    st.redo()
    st.redo()
    assert st._clips[0].fx["look"] == "warm"
    st.fx_look_btns["none"].click()
    st._fx_reset()
    assert st._clips[0].fx == {}


def test_green_screen_controls_follow_the_switch(studio_win) -> None:
    st, _tmp = studio_win
    st.select_clip(0)
    assert not st.fx_key_box.isEnabled() and not st.fx_sliders["key_similarity"].isEnabled()
    st.fx_key.setChecked(True)
    assert st._clips[0].fx["key"] == "#00FF00"
    assert st.fx_key_box.isEnabled() and st.fx_sliders["key_similarity"].isEnabled()
    st.fx_key_btns["#0000FF"].click()
    st._fx_set("key_bg", "/some/where/bg.png")
    assert st._clips[0].fx["key"] == "#0000FF" and st.fx_bg_btn.text() == "bg.png"
    st.fx_key.setChecked(False)
    assert st._clips[0].fx == {}  # the background goes with the key


def test_effects_are_saved_in_the_project_and_sent_to_the_render(studio_win) -> None:
    st, tmp = studio_win
    st.select_clip(1)
    st.fx_look_btns["bw"].click()
    st.fx_smooth.setChecked(True)
    saved = st.project_data()
    assert saved["clips"][0]["fx"] == {} and saved["clips"][1]["fx"] == {"look": "bw", "smooth": True}
    path = tmp / "p.vgproj"
    path.write_text(json.dumps(saved))
    st.new_project()
    assert st.open_project(str(path))
    assert [c.fx for c in st._clips] == [{}, {"look": "bw", "smooth": True}]
    sent = {}
    st.render_requested.connect(lambda task, kw: sent.update(task=task, **kw))
    st.render()
    assert sent["clips"][1].fx == {"look": "bw", "smooth": True} and sent["clips"][0].fx == {}


def test_old_projects_without_effects_still_open(studio_win) -> None:
    st, tmp = studio_win
    data = st.project_data()
    for c in data["clips"]:
        c.pop("fx")
    path = tmp / "old.vgproj"
    path.write_text(json.dumps(data))
    st.new_project()
    assert st.open_project(str(path)) and [c.fx for c in st._clips] == [{}, {}]


def test_before_and_after_pictures_fill_in(studio_win, qapp) -> None:
    import time

    st, _tmp = studio_win
    st.select_clip(0)
    st.fx_look_btns["bw"].click()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and any(s.pixmap().isNull() for s in st.fx_shots):
        qapp.processEvents()
        time.sleep(0.05)
    assert all(not s.pixmap().isNull() for s in st.fx_shots)


def test_picture_movement_is_saved(studio_win) -> None:
    st, tmp = studio_win
    pic = tmp / "p.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64",
                    "-frames:v", "1", str(pic)], check=True)
    st.add_images([str(pic)])
    st.select_image(0)
    st.image_motion_btns["zoom_in"].click()
    assert st._images[0].motion == "zoom_in"
    assert st.project_data()["images"][0]["motion"] == "zoom_in"
    st.undo()
    assert st._images[0].motion == "none"


def test_text_style_buttons_set_look_animation_and_place(studio_win) -> None:
    st, _tmp = studio_win
    st._add_cue()
    st._apply_text_style("lower_third")
    cue = st._cues[0]
    assert cue.text == "Name Surname" and cue.animation == "slide"
    assert cue.look["background"] == "#1E3A8A" and (cue.anchor, cue.x, cue.y) == (1, 0.06, 0.86)
    st.undo()
    assert st._cues[0].animation == "none" and st._cues[0].look is None
    st.redo()
    st.cue_text.setPlainText("Ada Lovelace")
    st._apply_text_style("title")
    assert st._cues[0].text == "Ada Lovelace"  # typed text is kept
    assert st._cues[0].animation == "pop"


def _wait_frame(st, app, ok, seconds: float = 8.0):
    import time

    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        img = st.preview.canvas._frame
        if img is not None and ok(img):
            return img
        time.sleep(0.02)
    return st.preview.canvas._frame


def test_player_shows_colour_effects(studio_win, qapp) -> None:
    from vidgrab import fx_preview

    if not fx_preview.available():
        pytest.skip("numpy not installed")
    st, tmp = studio_win
    red = tmp / "red.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=160x90:r=10:d=3", str(red)], check=True)
    st.add_clips([str(red)])
    st.select_clip(2)
    st.preview.seek(st.track.offsets()[2] + 0.5)
    img = _wait_frame(st, qapp, lambda i: i.width() > 0)
    assert img is not None and img.pixelColor(10, 10).red() > 200 > img.pixelColor(10, 10).green() + 100
    st._fx_set("look", "bw")  # a redraw of the frame that is showing, no reload
    img = _wait_frame(st, qapp, lambda i: abs(i.pixelColor(10, 10).red() - i.pixelColor(10, 10).green()) < 20)
    c = img.pixelColor(10, 10)
    assert abs(c.red() - c.green()) < 20 and abs(c.green() - c.blue()) < 20
    st._fx_set("look", "none")
    img = _wait_frame(st, qapp, lambda i: i.pixelColor(10, 10).red() > 200)
    assert img.pixelColor(10, 10).red() > 200


def test_player_keys_green_over_the_background_picture(studio_win, qapp, tmp_path) -> None:
    from PySide6.QtGui import QColor, QImage

    from vidgrab import fx_preview

    if not fx_preview.available():
        pytest.skip("numpy not installed")
    st, tmp = studio_win
    green = tmp / "green.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=0x00FF00:s=160x90:r=10:d=3", str(green)], check=True)
    bg = QImage(64, 64, QImage.Format_RGB32)
    bg.fill(QColor(20, 40, 220))
    bg_path = tmp_path / "bg.png"
    bg.save(str(bg_path))
    st.add_clips([str(green)])
    st.select_clip(2)
    st._fx_set("key", "#00FF00")
    st._fx_set("key_bg", str(bg_path))
    st.preview.seek(st.track.offsets()[2] + 0.5)
    img = _wait_frame(st, qapp, lambda i: i.pixelColor(10, 10).blue() > 150)
    c = img.pixelColor(10, 10)
    assert c.blue() > 150 and c.green() < 90


def test_follow_the_face_button(studio_win, qapp, monkeypatch) -> None:
    import time

    from PySide6.QtWidgets import QMessageBox

    from vidgrab import reframe

    if not reframe.available():
        pytest.skip("numpy / onnxruntime not installed")
    st, tmp = studio_win
    keys = [[0.0, 0.3, 0.4], [1.0, 0.7, 0.4]]
    monkeypatch.setattr(reframe, "follow_face", lambda *_a, **_k: keys)
    monkeypatch.setattr(reframe, "model_ready", lambda _d: True)
    asked = []
    answer = [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a) or answer[0]))
    st.host.models_dir = lambda: tmp
    st.select_clip(0)
    assert st.follow_btn.text() == "Follow the face"

    def press():
        st.follow_btn.click()
        end = time.time() + 5
        while st.follow_btn.isEnabled() is False and time.time() < end:
            qapp.processEvents()
            time.sleep(0.02)
        qapp.processEvents()

    press()
    clip = st._clips[0]
    assert clip.fx["follow"] == keys and clip.fit == "fill"
    assert asked and st.res.currentData() != "vertical"  # offered the Shorts size, declined
    assert st.follow_btn.text() == "Stop following"
    st.undo()
    assert not st._clips[0].fx.get("follow") and st._clips[0].fit == "fit"
    st.redo()
    assert st._clips[0].fx["follow"] == keys
    st.follow_btn.click()  # on: this turns it off
    assert not st._clips[0].fx.get("follow") and st.follow_btn.text() == "Follow the face"
    answer[0] = QMessageBox.Yes
    press()
    assert st.res.currentData() == "vertical"  # accepted this time


def test_preview_crop_follows_the_keys(studio_win, qapp) -> None:
    from PySide6.QtCore import QRectF

    from vidgrab.preview import frame_geometry

    rect = QRectF(0, 0, 90, 160)
    src, _tgt = frame_geometry(640, 360, rect, "fill", 1.0, 0.5, 0.5, focus=(0.2, 0.5))
    assert abs(src.center().x() - 0.2 * 640) < 1
    src, _tgt = frame_geometry(640, 360, rect, "fill", 1.0, 0.5, 0.5, focus=(0.99, 0.5))
    assert abs(src.right() - 640) < 1  # never past the picture's edge
    src, _tgt = frame_geometry(640, 360, rect, "fill", 1.0, 0.5, 0.5)
    assert abs(src.center().x() - 320) < 1
