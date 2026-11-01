"""Picture effects: the filter chains, and real renders with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from vidgrab import effects, studio

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg / ffprobe not on PATH"
)


def test_sanitize_drops_unknown_clamps_and_removes_defaults() -> None:
    assert effects.sanitize(None) == {}
    assert effects.sanitize({"look": "none", "contrast": 1.0, "bogus": 3}) == {}
    fx = effects.sanitize({"look": "nope", "brightness": 9, "saturation": "x", "key": "red",
                           "stabilize": 1, "key_bg": "a.png"})
    assert fx == {"brightness": 0.5, "stabilize": True}  # a bad look / colour is dropped; no key, no background
    keyed = effects.sanitize({"key": "#00ff00", "key_bg": "a.png"})
    assert keyed == {"key": "#00ff00", "key_bg": "a.png"}


def test_edit_tuple_ignores_order_and_defaults() -> None:
    a = effects.edit_tuple({"look": "warm", "sharpen": 0.5})
    b = effects.edit_tuple({"sharpen": 0.5, "look": "warm", "contrast": 1.0})
    assert a == b and hash(a) == hash(b)
    assert dict(a) == {"look": "warm", "sharpen": 0.5}


def test_chains() -> None:
    assert effects.source_chain({}) == ""
    chain = effects.source_chain({"look": "bw", "denoise": 0.5, "sharpen": 0.4, "contrast": 1.2},
                                 trf_name="stab0.trf", lut_name="lut0.cube")
    order = [chain.index(x) for x in ("vidstabtransform", "hqdn3d", "unsharp", "hue=s=0",
                                      "lut3d=file=lut0.cube", "eq=brightness")]
    assert order == sorted(order) and chain.endswith(",")  # stabilise, clean up, then colour
    assert effects.key_filter({}) == ""
    assert effects.key_filter({"key": "#00ff00", "key_similarity": 0.3}).startswith(
        "chromakey=color=0x00FF00:similarity=0.300")
    assert "minterpolate=fps=30" in effects.smooth_filter(30)


def test_every_look_is_a_filter() -> None:
    assert set(effects.LOOKS) == {"none", "cinematic", "warm", "cool", "bw", "vivid", "vintage"}
    assert all(effects.LOOKS[k] for k in effects.LOOKS if k != "none")


def test_kenburns_scale_grows_or_shrinks() -> None:
    zin = effects.kenburns_scale(400, 0, 4, "in")
    zout = effects.kenburns_scale(400, 0, 4, "out")
    assert "eval=frame" in zin and "(1+0.200*clip((t-0.000)/4.000,0,1))" in zin
    assert "(1-clip(" in zout


def test_text_templates_use_known_options() -> None:
    for spec in effects.TEXT_TEMPLATES.values():
        assert spec["animation"] in studio.ANIMATIONS
        assert set(spec["look"]) <= set(studio.LOOK_KEYS)
        assert 1 <= spec["anchor"] <= 9 and 0 <= spec["x"] <= 1 and 0 <= spec["y"] <= 1


def _clip(path: str, **kw) -> studio._ResolvedClip:
    return studio._ResolvedClip(Path(path), 0.0, 2.0, True, True, 320, 180, **kw)


def test_command_puts_effects_before_framing_and_keys_over_a_background() -> None:
    cmd, _ = studio.build_video_command(
        "ffmpeg", [_clip("a.mp4", fx={"look": "warm"}),
                   _clip("g.mp4", fx={"key": "#00FF00", "key_bg": "bg.png"}, speed=0.5)],
        Path("o.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    first = graph.split(";")[0]
    assert first.index("colorbalance") < first.index("scale=")
    assert "chromakey" in graph and "black@0" in graph and "overlay=shortest=1" in graph
    assert "bg.png" in cmd  # the background is its own looped input


def test_smooth_only_applies_to_slow_clips() -> None:
    fast = studio.build_video_command("ffmpeg", [_clip("a.mp4", fx={"smooth": True})], Path("o.mp4"))
    slow = studio.build_video_command(
        "ffmpeg", [_clip("a.mp4", fx={"smooth": True}, speed=0.5)], Path("o.mp4"))
    assert "minterpolate" not in " ".join(fast[0])
    assert "minterpolate" in " ".join(slow[0])


def _make(path: Path, source: str, seconds: int = 2) -> Path:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"{source}{':' if '=' in source else '='}size=320x180:rate=15", "-t", str(seconds), "-pix_fmt", "yuv420p",
                    str(path)], check=True)
    return path


def _frame(video: Path, at: float = 0.5) -> bytes:
    """Raw RGB of one frame."""
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(at), "-i", str(video),
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True)
    return out.stdout


def _chroma(rgb: bytes) -> float:
    """How colourful a frame is: the average gap between a pixel's channels."""
    r, g, b = rgb[0::3], rgb[1::3], rgb[2::3]
    return sum(abs(x - y) + abs(y - z) for x, y, z in zip(r, g, b)) / len(r)


def _mean(rgb: bytes, channel: int) -> float:
    return sum(rgb[channel::3]) / (len(rgb) / 3)


@needs_ffmpeg
def test_black_and_white_look_removes_colour(tmp_path: Path) -> None:
    src = _make(tmp_path / "c.mp4", "testsrc")
    out = studio.compose_video([studio.Clip(str(src), fx={"look": "bw"})], tmp_path / "o.mp4")
    rgb = _frame(out)
    assert _chroma(rgb) < 3
    plain = _frame(studio.compose_video([studio.Clip(str(src))], tmp_path / "p.mp4"))
    assert _chroma(plain) > 40  # the original really is colourful


@needs_ffmpeg
def test_warm_look_moves_red_up_and_blue_down(tmp_path: Path) -> None:
    src = _make(tmp_path / "c.mp4", "testsrc")
    base = _frame(studio.compose_video([studio.Clip(str(src))], tmp_path / "a.mp4"))
    warm = _frame(studio.compose_video([studio.Clip(str(src), fx={"warmth": 1.0})], tmp_path / "b.mp4"))
    assert _mean(warm, 0) > _mean(base, 0) and _mean(warm, 2) < _mean(base, 2)


@needs_ffmpeg
def test_green_screen_shows_the_background_picture(tmp_path: Path) -> None:
    green = tmp_path / "g.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=0x00ff00:s=320x180:r=15,drawbox=x=110:y=40:w=100:h=100:color=red:t=fill",
                    "-t", "2", "-pix_fmt", "yuv420p", str(green)], check=True)
    bg = tmp_path / "bg.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x180", "-frames:v", "1", str(bg)], check=True)
    out = studio.compose_video(
        [studio.Clip(str(green), fx={"key": "#00FF00", "key_bg": str(bg)})], tmp_path / "o.mp4")
    rgb = _frame(out)
    corner = rgb[0:3]  # was green: now the blue picture
    centre = rgb[(90 * 320 + 160) * 3:][:3]  # the red square stays
    assert corner[2] > 150 and corner[1] < 90
    assert centre[0] > 150 and centre[2] < 90
    # no background picture: black behind it
    black = _frame(studio.compose_video(
        [studio.Clip(str(green), fx={"key": "#00FF00"})], tmp_path / "k.mp4"))
    assert max(black[0:3]) < 40


@needs_ffmpeg
def test_stabilise_removes_most_of_the_shake(tmp_path: Path) -> None:
    # a still picture (colour bars have edges to follow) shaken by cropping a moving window
    shaky = tmp_path / "shaky.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "smptebars=s=480x300:r=25",
         "-vf", "crop=320:200:x='80+20*sin(t*11)':y='50+12*cos(t*13)'", "-t", "3",
         "-pix_fmt", "yuv420p", str(shaky)], check=True)

    def jitter(video: Path) -> float:
        """Average change from one frame to the next (the picture itself never moves)."""
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf",
                              "scale=160:100,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        n = 160 * 100
        frames = [raw[i * n:(i + 1) * n] for i in range(len(raw) // n)]
        diffs = [sum(abs(a - b) for a, b in zip(x, y)) / n for x, y in pairwise(frames)]
        return sum(diffs) / len(diffs)

    logs: list[str] = []
    steady = studio.compose_video([studio.Clip(str(shaky), fx={"stabilize": True})],
                                  tmp_path / "steady.mp4", on_log=logs.append)
    plain = studio.compose_video([studio.Clip(str(shaky))], tmp_path / "plain.mp4")
    assert any("vidstabdetect" in line for line in logs)  # the analysis pass ran
    assert jitter(steady) < jitter(plain) * 0.3


@needs_ffmpeg
def test_colour_look_file_is_copied_next_to_the_render(tmp_path: Path) -> None:
    src = _make(tmp_path / "c.mp4", "testsrc")
    cube = tmp_path / "my look.cube"  # a space and no escaping needed: it is copied
    size = 2
    rows = [f"{r / (size - 1):.1f} {g / (size - 1):.1f} {b / (size - 1):.1f}"
            for b in range(size) for g in range(size) for r in range(size)]
    # an inverting look: easy to tell from the original
    inv = [" ".join(f"{1 - float(v):.1f}" for v in row.split()) for row in rows]
    cube.write_text(f"LUT_3D_SIZE {size}\n" + "\n".join(inv) + "\n")
    base = _frame(studio.compose_video([studio.Clip(str(src))], tmp_path / "a.mp4"))
    out = _frame(studio.compose_video([studio.Clip(str(src), fx={"lut": str(cube)})],
                                      tmp_path / "b.mp4"))
    assert abs((_mean(base, 1) + _mean(out, 1)) - 255) < 25  # inverted


@needs_ffmpeg
def test_smooth_slow_motion_renders(tmp_path: Path) -> None:
    src = _make(tmp_path / "c.mp4", "testsrc2")
    out = studio.compose_video([studio.Clip(str(src), speed=0.5, fx={"smooth": True})],
                               tmp_path / "o.mp4")
    assert studio.probe_media(out)["duration"] == pytest.approx(4.0, abs=0.3)


@needs_ffmpeg
def test_ken_burns_picture_grows(tmp_path: Path) -> None:
    src = _make(tmp_path / "c.mp4", "color=c=black", 3)
    pic = tmp_path / "p.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=white:s=200x100", "-frames:v", "1", str(pic)], check=True)

    def white(motion: str, at: float) -> float:
        out = studio.compose_video(
            [studio.Clip(str(src))], tmp_path / f"{motion}{at}.mp4",
            images=[studio.ImageOverlay(str(pic), 0, 3, width=0.4, motion=motion)])
        return _mean(_frame(out, at), 0)

    assert white("zoom_in", 2.8) > white("zoom_in", 0.1) * 1.15
    assert white("zoom_out", 2.8) < white("zoom_out", 0.1) * 0.9
    still = white("none", 0.1)
    assert abs(white("none", 2.8) - still) < 2


@needs_ffmpeg
def test_noise_cleanup_makes_the_picture_smoother(tmp_path: Path) -> None:
    src = tmp_path / "n.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=gray:s=320x180:r=15,noise=alls=40:allf=t+u", "-t", "2",
                    "-pix_fmt", "yuv420p", str(src)], check=True)

    def spread(fx: dict) -> float:
        out = studio.compose_video([studio.Clip(str(src), fx=fx)], tmp_path / f"n{len(fx)}.mp4")
        rgb = _frame(out, 1.8)  # later frames: the filter has had frames to average
        mean = _mean(rgb, 1)
        return sum((v - mean) ** 2 for v in rgb[1::3]) / (len(rgb) / 3)

    assert spread({"denoise": 1.0}) < spread({"look": "none", "contrast": 1.0, "warmth": 0.0}) * 0.6
