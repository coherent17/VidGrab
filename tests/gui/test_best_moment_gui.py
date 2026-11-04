"""Trim tab → Best moment."""
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


def test_best_moment_keeps_the_loud_part(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab.ui import app as m

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    clip = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=10:d=30",
                    "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,18,28),0.5*sin(2*PI*300*t),0.002*sin(2*PI*50*t))':s=16000:d=30",
                    "-shortest", str(clip)], check=True)
    win = m.VidGrabWindow()
    st = win._studio
    try:
        st.add_clips([str(clip)])
        st.render_requested.disconnect()
        st.host.ffmpeg_ok = lambda: True
        st.select_clip(0)
        st.find_best_moment(8)
        end = time.time() + 30
        while time.time() < end and st._clips[0].span() == (0.0, 30.0):
            qapp.processEvents()
            time.sleep(0.05)
        a, b = st._clips[0].span()
        assert abs((b - a) - 8) < 1e-6 and 17 <= a <= 21
        st.undo()
        assert st._clips[0].span() == (0.0, 30.0)
        st.find_best_moment(40)  # longer than the clip: nothing to cut
        assert "already" in st.status.text()
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()
