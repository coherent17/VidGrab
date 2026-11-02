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
