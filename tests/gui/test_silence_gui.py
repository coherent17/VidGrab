import os
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication, QDialog

pytestmark = [
    pytest.mark.skipif(not os.environ.get("SMOKE_GUI"), reason="SMOKE_GUI not set"),
    pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg"),
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def talk(tmp_path):
    """2 s tone, 2 s quiet, 2 s tone, as a video with sound."""
    out = tmp_path / "talk.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=6:r=10",
         "-f", "lavfi", "-i", "sine=f=440:d=2", "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=mono:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
         "-filter_complex", "[1][2][3]concat=n=3:v=0:a=1[a]", "-map", "0:v", "-map", "[a]",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def test_remove_silences_splits_the_clip(qapp, talk, monkeypatch):
    from vidgrab.ui import app as appmod
    monkeypatch.setattr(appmod, "_config_dir", lambda: talk.parent)
    win = appmod.VidGrabWindow()
    st = win._studio
    st.render_requested.disconnect()
    st.host.ffmpeg_ok = lambda: True
    st.add_clips([str(talk)])
    st.select_clip(0)
    monkeypatch.setattr(QDialog, "exec", lambda self: self.accept() or QDialog.Accepted)
    st.remove_silences()
    assert len(st._clips) == 2
    first, second = st._clips
    assert first.start == pytest.approx(0, abs=0.01) and 1.9 < first.end < 2.4
    assert 3.6 < second.start < 4.1 and second.end == pytest.approx(6, abs=0.3)
    st.undo()
    assert len(st._clips) == 1
    st.clear_autosave()
    st.shutdown()
    win.close()
