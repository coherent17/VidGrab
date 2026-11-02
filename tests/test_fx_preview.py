import shutil
import subprocess

import pytest

from vidgrab import effects, fx_preview, studio

pytestmark = pytest.mark.skipif(not fx_preview.available(), reason="needs numpy")
np = fx_preview.np


def test_every_look_has_a_grade():
    assert set(effects.LOOK_GRADES) == set(effects.LOOKS)


def test_nothing_to_show_leaves_the_picture_alone():
    img = (np.random.default_rng(1).random((8, 8, 3)) * 255).astype(np.uint8)
    assert not fx_preview.can_show({"stabilize": True, "denoise": 0.5})
    assert fx_preview.can_show({"look": "warm"}) and fx_preview.can_show({"key": "#00FF00"})
    assert np.abs(fx_preview.apply(img, {}).astype(int) - img).max() <= 1


def test_sliders_and_looks_move_the_picture_the_expected_way():
    img = np.full((4, 4, 3), (120, 100, 90), np.uint8)
    bright = fx_preview.apply(img, {"brightness": 0.2})
    assert bright.mean() > img.mean() + 30
    grey = fx_preview.apply(img, {"saturation": 0.0})
    assert np.ptp(grey.reshape(-1, 3)[0]) <= 1
    assert np.ptp(fx_preview.apply(img, {"look": "bw"}).reshape(-1, 3)[0]) <= 1
    dark = np.full((4, 4, 3), 40, np.uint8)  # warmth tints the shadows and highlights
    warm = fx_preview.apply(dark, {"warmth": 1.0})
    assert warm[0, 0, 0] > 40 and warm[0, 0, 2] < 40


def test_green_screen_shows_the_background():
    img = np.zeros((4, 8, 3), np.uint8)
    img[:, :4] = (0, 255, 0)
    img[:, 4:] = (200, 40, 40)
    back = np.full((4, 8, 3), (10, 20, 250), np.uint8)
    out = fx_preview.apply(img, {"key": "#00FF00"}, back)
    assert tuple(out[0, 0]) == (10, 20, 250) and tuple(out[0, 7]) == (200, 40, 40)
    black = fx_preview.apply(img, {"key": "#00FF00"})
    assert tuple(black[0, 0]) == (0, 0, 0)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
@pytest.mark.parametrize("fx", [{"look": "cinematic"}, {"look": "warm"}, {"look": "vivid"},
                                {"contrast": 1.4, "saturation": 1.5}, {"brightness": 0.2, "warmth": 0.6}])
def test_preview_is_close_to_the_render(fx):
    """The imitation stays near what ffmpeg makes from the same frame."""
    src = np.array([[(r, g, b) for r in (40, 120, 220) for g in (30, 140, 230) for b in (50, 150, 240)]],
                   np.uint8)  # 1 x 27 colours
    chain = effects.source_chain(fx).rstrip(",")
    raw = src.tobytes()
    proc = subprocess.run(
        [studio.find_ffmpeg(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "27x1",
         "-i", "-", "-vf", f"{chain},format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"],
        input=raw, capture_output=True, check=True)
    truth = np.frombuffer(proc.stdout, np.uint8).reshape(1, 27, 3).astype(int)
    mine = fx_preview.apply(src, fx).astype(int)
    assert np.abs(mine - truth).mean() < 14, np.abs(mine - truth).mean()
