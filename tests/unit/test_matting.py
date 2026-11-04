"""Remove background: the matte maker and how the render uses it."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidgrab.ai import matting
from vidgrab.media import effects, studio

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def test_the_cutout_switch_is_a_normal_effect() -> None:
    assert effects.sanitize({"cutout": True}) == {"cutout": True}
    assert effects.sanitize({"cutout": False}) == {}
    assert effects.sanitize({"cutout": True, "key_bg": "bg.png"}).get("key_bg") == "bg.png"  # the picture behind stays
    assert "key_bg" not in effects.sanitize({"key_bg": "bg.png"})  # (as before, without any cut-out)


def test_the_render_graph_uses_the_matte_as_the_clips_alpha(tmp_path) -> None:
    clip = studio._ResolvedClip(Path("a.mp4"), 0.0, 3.0, True, True, 640, 360, fx={"cutout": True}, matte="matte0.mkv")
    cmd, _total = studio.build_video_command("ffmpeg", [clip], tmp_path / "o.mp4")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "alphamerge" in graph and "matte0.mkv" in cmd and "overlay=shortest=1" in graph
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    assert inputs[0].endswith("a.mp4") and "matte0.mkv" in inputs  # picture first, then its background and matte


def test_matter_output_is_blended_over_time() -> None:
    np = pytest.importorskip("numpy")
    a, b = np.zeros((4, 4)), np.ones((4, 4))
    assert matting.steady(None, b) is b
    mixed = matting.steady(a, b)
    assert abs(float(mixed[0, 0]) - matting.SMOOTH) < 1e-9  # the new frame only partly replaces the last one


@needs_ffmpeg
def test_a_real_matte_and_render_when_the_model_can_be_had(tmp_path) -> None:
    if not matting.available():
        pytest.skip("numpy / onnxruntime not installed")
    try:
        matting.ensure_model(Path.home() / ".cache" / "vidgrab" / "models")
    except RuntimeError:
        pytest.skip("the background model cannot be downloaded here")
    models = Path.home() / ".cache" / "vidgrab" / "models"
    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=duration=3", "-shortest", str(src)], check=True)
    matte = matting.make_matte(src, 0, 3, tmp_path / "m.mkv", models)
    info = studio.probe_media(matte)
    assert info["has_video"] and 1.5 < info["duration"] < 3.5
    out = tmp_path / "o.mp4"
    studio.compose_video([studio.Clip(str(src), fx={"cutout": True})], out, models_dir=models)
    assert studio.probe_media(out)["duration"] > 2.5
    with pytest.raises(Exception, match=r"ancel"):
        matting.make_matte(src, 0, 3, tmp_path / "c.mkv", models, on_progress=lambda *a: (_ for _ in ()).throw(
            matting.DownloadCancelled("Cancelled")))
    assert not (tmp_path / "c.mkv").exists()  # a cancelled matte leaves no file


def test_the_effects_tab_switch_turns_the_cutout_on_and_the_green_key_off(tmp_path, monkeypatch) -> None:
    import os

    if os.environ.get("SMOKE_GUI") != "1" or not shutil.which("ffmpeg"):
        pytest.skip("set SMOKE_GUI=1 (and have ffmpeg) to enable")
    from PySide6.QtWidgets import QApplication

    from vidgrab.ui import app as m

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=duration=3", "-shortest", str(clip)], check=True)
    win = m.VidGrabWindow()
    st = win._studio
    try:
        st.add_clips([str(clip)])
        st.render_requested.disconnect()
        st.select_clip(0)
        st.fx_key.setChecked(True)
        assert st._clips[0].fx.get("key") == effects.GREEN
        st.fx_cutout.setChecked(True)
        fx = st._clips[0].fx
        assert fx.get("cutout") is True and "key" not in fx  # one way of cutting out at a time
        assert st.fx_bg_btn.isEnabled() and not st.fx_key_box.isEnabled()  # the picture behind still applies
        st.undo()
        assert "cutout" not in st._clips[0].fx
        got = []
        st.render_requested.connect(lambda task, kw: got.append(kw))
        st.host.ffmpeg_ok = lambda: True
        st.host.models_dir = lambda: tmp_path
        st.render()
        assert got and got[0]["models_dir"] == tmp_path
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()
