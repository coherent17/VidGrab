"""Music tab → Cut clips to the beat."""
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


def _wait(qapp, cond, seconds=20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.03)
    return cond()


def test_cuts_land_on_the_beat_and_undo_restores_them(qapp, tmp_path, monkeypatch) -> None:
    from vidgrab import app as m
    from vidgrab import beats

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg / ffprobe not on PATH")
    pytest.importorskip("numpy")
    monkeypatch.setattr(m, "_config_dir", lambda: tmp_path)
    clips = []
    for n in (1, 2):
        p = tmp_path / f"c{n}.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=10:d=12",
                        "-f", "lavfi", "-i", "sine=duration=12", "-shortest", str(p)], check=True)
        clips.append(str(p))
    song = tmp_path / "song.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30", str(song)], check=True)
    # a steady beat every 0.8 s, whatever the song really is
    monkeypatch.setattr(beats, "detect", lambda *a, **k: beats.Beats(75.0, [round(0.8 * k, 3) for k in range(40)]))
    win = m.VidGrabWindow()
    st = win._studio
    try:
        st.add_clips(clips)
        st.render_requested.disconnect()
        st.add_song(str(song))
        st._clips[0].end = 5.0  # the cut at 5.0 s: nearest beats are 4.8 and 5.6
        st._project_changed()
        st._record("trim")
        st.cut_to_beat()
        assert _wait(qapp, lambda: st.beat_btn.isEnabled())
        first = st._clips[0].span()[1] - st._clips[0].span()[0]
        assert abs(first / 0.8 - round(first / 0.8)) < 1e-3 and abs(first - 4.8) < 1e-3
        assert "BPM" in st.status.text()
        st.undo()
        assert st._clips[0].span()[1] == 5.0
        st._clips[1].transition = "fade"  # transitions: refuse politely
        st.cut_to_beat()
        assert "plain cuts" in st.status.text()
    finally:
        st.clear_autosave()
        st.shutdown()
        win.close()
