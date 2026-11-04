"""Blur / pixelate boxes and stickers over the video."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from vidgrab.media import studio

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def test_cover_overlays_need_no_input_file_and_keep_old_projects_loadable() -> None:
    from dataclasses import astuple

    old_row = ("a.png", 1.0, 3.0, 0.5, 0.5, 0.3, 1.0, 0.0, 0.0, "none")  # saved before covers existed
    img = studio.ImageOverlay(*old_row)
    assert img.is_picture() and img.kind == "image"
    cover = studio.ImageOverlay("", 1.0, 2.0, kind="blur", height=0.3, strength=0.9)
    assert not cover.is_picture() and studio.ImageOverlay(*astuple(cover)) == cover
    graph = studio._cover_graph(cover, 0, "[vc]", 1280, 720)
    assert any("gblur" in g for g in graph) and graph[-1].endswith("[vo0]")
    pix = studio._cover_graph(studio.ImageOverlay("", 0, 1, kind="pixel", strength=1.0), 1, "[vo0]", 1280, 720)
    assert any("neighbor" in g for g in pix)


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["blur", "pixel"])
def test_a_box_hides_its_area_only_while_it_is_on(tmp_path, kind) -> None:
    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=duration=3", "-shortest", str(src)], check=True)
    out = tmp_path / "o.mp4"
    studio.compose_video([studio.Clip(str(src))], out,
                         images=[studio.ImageOverlay("", 1.0, 2.0, 0.5, 0.5, 0.5, kind=kind, height=0.5,
                                                     strength=0.9)])

    def frame(path, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        return raw

    plain = tmp_path / "plain.mp4"
    studio.compose_video([studio.Clip(str(src))], plain)
    w, h = 320, 180

    def centre(raw):
        rows = [raw[y * w + w // 4: y * w + 3 * w // 4] for y in range(h // 4, 3 * h // 4)]
        return b"".join(rows)

    def gap(t):  # how different the middle of the two renders is (mean per pixel, 0..255)
        a, b = centre(frame(out, t)), centre(frame(plain, t))
        return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)

    assert gap(0.4) < 3 and gap(1.5) > 6  # untouched outside the time range, hidden inside it


@pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")
def test_stickers_draw_and_the_studio_adds_boxes_and_stickers(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from vidgrab.ui import app as m
    from vidgrab.ui import stickers

    qapp = QApplication.instance() or QApplication([])
    paths = stickers.ensure(tmp_path / "st")
    assert set(paths) == set(stickers.NAMES) and all(os.path.getsize(p) > 500 for p in paths.values())
    from PySide6.QtGui import QImage

    assert QImage(paths["star"]).hasAlphaChannel()
    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=6",
                    "-f", "lavfi", "-i", "sine=duration=6", "-shortest", str(clip)], check=True)
    win = m.VidGrabWindow()
    st = win._studio
    try:
        st.add_clips([str(clip)])
        st.render_requested.disconnect()
        st.add_cover("blur")
        cover = st._images[-1]
        assert cover.kind == "blur" and st._sel == ("image", len(st._images) - 1)
        assert not st.image_opacity_lbl.isVisibleTo(st.image_opacity_lbl.parentWidget())  # picture options hide
        assert st.image_height_lbl.isVisibleTo(st.image_height_lbl.parentWidget())
        st._on_image_placed(0, 0.4, 0.4, 0.6)  # drag the corner: it grows with its shape
        assert abs(st._images[0].height - 0.4) < 0.01
        st.add_sticker("heart")
        assert st._images[-1].kind == "image" and st._images[-1].path.endswith("sticker-heart.png")
        n = len(st._images)
        st.undo()
        assert len(st._images) == n - 1
        data = st.project_data()
        assert any(row.get("kind") == "blur" and row["path"] == "" for row in data["images"])
        project = tmp_path / "p.vgproj"
        project.write_text(__import__("json").dumps(data), encoding="utf-8")
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
        st._images.clear()
        st.open_project(str(project))
        assert [i.kind for i in st._images].count("blur") == 1  # and comes back on opening
        assert qapp is not None
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()
