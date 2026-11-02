import shutil
import subprocess

import pytest

from vidgrab import effects, reframe, studio
from vidgrab.studio import Clip

np = reframe.np
pytestmark = pytest.mark.skipif(np is None, reason="needs numpy")


def test_decode_keeps_confident_faces_and_merges_overlaps():
    scores = np.array([[[0.9, 0.1], [0.2, 0.8], [0.05, 0.95], [0.9, 0.1]]], np.float32)
    boxes = np.array([[[0.1, 0.1, 0.3, 0.4], [0.1, 0.1, 0.31, 0.41],  # two boxes, one face
                       [0.6, 0.2, 0.8, 0.6], [0.0, 0.0, 1.0, 1.0]]], np.float32)
    faces = reframe.decode(scores, boxes)
    assert len(faces) == 2 and faces[0][4] > 0.9  # the 0.95 face first, then the 0.8 one
    assert reframe.decode(np.zeros((1, 2, 2), np.float32), np.zeros((1, 2, 4), np.float32)) == []


def test_pick_face_prefers_big_and_near():
    small_near = (0.40, 0.4, 0.45, 0.5, 0.9)
    big_far = (0.70, 0.3, 0.90, 0.7, 0.9)
    assert reframe.pick_face([small_near, big_far], None) == big_far
    assert reframe.pick_face([small_near, big_far], (0.42, 0.45)) == small_near  # stay with who we follow
    assert reframe.pick_face([small_near, big_far], (0.8, 0.5)) == big_far
    twins = [(0.1, 0.3, 0.3, 0.7, 0.9), (0.6, 0.3, 0.8, 0.7, 0.9)]
    assert reframe.pick_face(twins, (0.7, 0.5)) == twins[1]  # same size: stay with the one we had
    assert reframe.pick_face([], None) is None


def test_camera_holds_still_for_small_moves_and_follows_big_ones():
    still = [(i / 4, 0.5 + (0.01 if i % 2 else -0.01), 0.4) for i in range(20)]
    keys = reframe.simplify(reframe.smooth_path(still, 4))
    assert len(keys) == 2 and abs(keys[0][1] - keys[-1][1]) < 0.001
    walk = [(i / 4, 0.2 + i * 0.03, 0.4) for i in range(20)]
    path = reframe.smooth_path(walk, 4)
    assert path[-1][1] > 0.7 and path[-1][1] > path[0][1] + 0.4
    # frames without a face keep the camera where it was
    gaps = [(0, 0.3, 0.4), None, None, None, (1, 0.3, 0.4)]
    assert {k[1] for k in reframe.smooth_path(gaps, 4)} == {0.3}
    assert reframe.smooth_path([None, None], 4) == []


def test_simplify_keeps_the_shape_with_few_keys():
    keys = [[i / 4, min(0.2 + i * 0.02, 0.6), 0.4] for i in range(60)]
    small = reframe.simplify(keys)
    assert 3 <= len(small) <= 6
    for k in keys:
        x, _y = effects.focus_at(small, k[0])
        assert abs(x - k[1]) <= 0.011
    many = [[i / 4, (i % 7) / 7, (i % 5) / 5] for i in range(400)]
    assert len(reframe.simplify(many, limit=100)) <= 100


def test_follow_keys_are_cleaned_and_survive_sanitize():
    fx = effects.sanitize({"follow": [[2, 0.5, 0.5], [1, -3, 9], ["x"], [0.5]]})
    assert effects.sanitize({"follow": "nope"}) == {}
    assert effects.sanitize({"follow": []}) == {}
    assert effects.sanitize({"follow": [[2, 0.5, 0.5], [1, -3, 9]]})["follow"] == [[1.0, 0.0, 1.0], [2.0, 0.5, 0.5]]
    assert fx == {}  # a bad row drops the whole path rather than guessing
    assert effects.has_effects({"follow": [[0, 0.5, 0.5]]})


def test_focus_expression_matches_the_path():
    keys = [[10.0, 0.2, 0.4], [12.0, 0.6, 0.4], [15.0, 0.6, 0.5]]
    assert effects.focus_at(keys, 5) == (0.2, 0.4) and effects.focus_at(keys, 20) == (0.6, 0.5)
    x, _y = effects.focus_at(keys, 11)
    assert abs(x - 0.4) < 1e-9
    assert effects.focus_at([], 3) is None
    expr = effects.focus_expr(keys, 10.0, 1)
    assert expr.startswith("if(lt(t,0.000)") and "0.2000+(0.4000)*(t-0.000)/2.000" in expr


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_render_moves_the_crop_with_the_path(tmp_path):
    """A white square slides left to right across a dark wide video; the tall
    crop that follows it keeps it in the middle of the frame."""
    wide = tmp_path / "wide.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=640x360:r=10:d=4",
         "-f", "lavfi", "-i", "color=c=white:s=60x60:r=10:d=4", "-filter_complex",
         "[0][1]overlay=x='20+t*140':y=150,format=yuv420p", "-t", "4", str(wide)], check=True)
    # the square's centre in the source: 50 + 140 t (of 640)
    keys = [[t, (50 + 140 * t) / 640, 0.5] for t in (0.0, 2.0, 4.0)]

    def square_x(video, at):
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-vf",
             "scale=90:160", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True)
        img = np.frombuffer(proc.stdout, np.uint8).reshape(160, 90)
        cols = np.where((img > 200).any(axis=0))[0]
        return float(cols.mean()) / 90 if len(cols) else None

    out = studio.compose_video([Clip(str(wide), fit="fill", fx={"follow": keys})],
                               tmp_path / "tall.mp4", resolution="vertical")
    for at in (0.4, 1.5, 2.6, 3.4):
        x = square_x(out, at)
        assert x is not None and abs(x - 0.5) < 0.12, (at, x)
    still = studio.compose_video([Clip(str(wide), fit="fill")], tmp_path / "centre.mp4",
                                 resolution="vertical")
    assert square_x(still, 0.4) is None or square_x(still, 3.4) is None  # a centre crop loses it
