"""Zoom keyframes: the effects data, the ffmpeg crop and the preview maths."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from vidgrab import effects, studio

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def test_keys_are_cleaned_sorted_and_clamped() -> None:
    fx = effects.sanitize({"keys": [[2, 0.5, 0.5, 9], [0, -1, 2, 1.5], ["x"], [1, 0.3, 0.3]]})
    assert fx["keys"] == [[0.0, 0.0, 1.0, 1.5], [2.0, 0.5, 0.5, 4.0]]  # junk rows are dropped
    assert effects.sanitize({"keys": "nope"}) == {} and effects.sanitize({"keys": []}) == {}
    assert effects.edit_tuple({"keys": [[0, 0.5, 0.5, 2]]}) != effects.edit_tuple({})


def test_values_blend_linearly_and_hold_at_the_ends() -> None:
    keys = [[1.0, 0.2, 0.4, 1.0], [3.0, 0.6, 0.8, 3.0]]
    assert effects.keys_at(keys, 0.0) == (0.2, 0.4, 1.0)  # before the first key
    assert effects.keys_at(keys, 5.0) == (0.6, 0.8, 3.0)  # after the last
    x, y, z = effects.keys_at(keys, 2.0)
    assert (round(x, 3), round(y, 3), round(z, 3)) == (0.4, 0.6, 2.0)
    assert effects.keys_at([], 1.0) is None


@needs_ffmpeg
def test_the_render_zooms_in_over_the_clip(tmp_path) -> None:
    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=4", "-shortest", str(src)], check=True)
    plain, zoomed = tmp_path / "p.mp4", tmp_path / "z.mp4"
    studio.compose_video([studio.Clip(str(src))], plain, resolution="720p")
    studio.compose_video([studio.Clip(str(src), fx=effects.sanitize({"keys": [[0, 0.5, 0.5, 1.0], [3.5, 0.5, 0.5, 3.0]]}))],
                         zoomed, resolution="720p")

    def frame(path, t):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout

    def gap(t):
        a, b = frame(plain, t), frame(zoomed, t)
        return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)

    assert gap(0.0) < 4 and gap(3.4) > 15  # starts like the plain clip, ends clearly zoomed in
    info = studio.probe_media(zoomed)
    assert abs(info["duration"] - 4) < 0.3 and info["width"] == 1280 and info["height"] == 720


def test_the_inspector_adds_edits_and_removes_keyframes_with_undo(tmp_path, monkeypatch) -> None:
    import os

    if os.environ.get("SMOKE_GUI") != "1":
        pytest.skip("set SMOKE_GUI=1 to enable")
    from PySide6.QtWidgets import QApplication

    from vidgrab import app as m

    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=10",
                    "-f", "lavfi", "-i", "sine=duration=10", "-shortest", str(clip)], check=True)
    win = m.VidGrabWindow()
    st = win._studio
    try:
        st.add_clips([str(clip)])
        st.render_requested.disconnect()
        st.select_clip(0)
        st.preview.seek(4.0)
        qapp.processEvents()
        st._add_key()
        keys = st._sel_clip().fx["keys"]
        assert [k[3] for k in keys] == [1.0, 1.6] and abs(keys[1][0] - 4.0) < 0.3  # a start frame and the push
        assert st._sel_clip().fit == "fill" and st.keys_list.count() == 2
        st.keys_list.setCurrentRow(1)
        st.key_zoom.setValue(250)  # edit the second key
        assert st._sel_clip().fx["keys"][1][3] == 2.5
        st.key_x.setValue(30)
        assert abs(st._sel_clip().fx["keys"][1][1] - 0.3) < 1e-6
        st.undo()
        assert abs(st._sel_clip().fx["keys"][1][1] - 0.5) < 1e-6
        st._remove_key()
        assert "keys" not in st._sel_clip().fx  # only the start frame left: the move is gone
        data = st.project_data()
        assert "keys" not in data["clips"][0]["fx"]
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()
