"""Live preview of the picture effects that can be drawn without ffmpeg: colour
looks, the colour sliders and green screen. A numpy imitation of the ffmpeg
filters in `effects` (close, not identical — the render is the truth); stabilise,
clean-up, sharpen, LUTs and slow motion are left out. Qt-free; `available()` is
False when numpy is not installed (it comes with the captions packages)."""
from __future__ import annotations

from vidgrab import effects

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with faster-whisper
    np = None

_LUMA = (0.299, 0.587, 0.114)


def available() -> bool:
    return np is not None


def can_show(fx: dict | None) -> bool:
    """Is there anything in *fx* the preview can draw?"""
    fx = effects.sanitize(fx)
    return any(k in fx for k in ("look", "brightness", "contrast", "saturation", "warmth", "key"))


def _luma(x):
    return x @ np.array(_LUMA, dtype=np.float32)


def _balance(x, shadows, mids, highs):
    """colorbalance: each channel is moved by an amount that depends on its own
    value (weights and the 0.7 scale as in ffmpeg's filter)."""
    a, b, scale = 4.0, 1 / 3, 0.7
    ws = np.clip((b - x) * a + 0.5, 0, 1) * scale
    wm = np.clip((x - b) * a + 0.5, 0, 1) * np.clip((x + b - 1) * -a + 0.5, 0, 1) * scale
    wh = np.clip((x + b - 1) * a + 0.5, 0, 1) * scale
    return x + ws * np.array(shadows, np.float32) + wm * np.array(mids, np.float32) \
        + wh * np.array(highs, np.float32)


def _eq(x, brightness=0.0, contrast=1.0, sat=1.0):
    """eq: contrast and brightness change the brightness (Y) only, saturation
    scales the colour (U / V) only — scaling RGB would mix the two."""
    lum = _luma(x)[..., None]
    chroma = (x - lum) * sat
    return (lum - 0.5) * contrast + 0.5 + brightness + chroma


def grade(x, fx: dict):
    """*x*: float32 RGB in 0..1 -> the same with the look and sliders applied."""
    g = effects.LOOK_GRADES.get(fx.get("look", "none"), {})
    if g:
        if "curves" in g:  # per channel (x, y) points
            x = np.stack([np.interp(x[..., c], *zip(*g["curves"][c], strict=True))
                          for c in range(3)], axis=-1).astype(np.float32)
        if any(k in g for k in ("shadows", "mids", "highs")):
            x = _balance(x, g.get("shadows", (0, 0, 0)), g.get("mids", (0, 0, 0)),
                         g.get("highs", (0, 0, 0)))
        x = _eq(x, 0.0, g.get("contrast", 1.0), g.get("sat", 1.0))
    b, c, s = (fx.get(k, effects.DEFAULT_FX[k]) for k in ("brightness", "contrast", "saturation"))
    if (b, c, s) != (0.0, 1.0, 1.0):
        x = _eq(x, b, c, s)
    w = fx.get("warmth", 0.0)
    if w:
        x = _balance(x, (0.15 * w, 0, -0.15 * w), (0, 0, 0), (0.1 * w, 0, -0.1 * w))
    return x


def _uv(rgb):
    y = rgb @ np.array(_LUMA, dtype=np.float32)
    return (rgb[..., 2] - y) * 0.564, (rgb[..., 0] - y) * 0.713


def key_alpha(x, fx: dict):
    """0 where the picture is the key colour, 1 elsewhere (fitted to ffmpeg's chromakey)."""
    key = fx["key"]
    kc = np.array([int(key[i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)
    ku, kv = _uv(kc)
    u, v = _uv(x)
    d = np.sqrt((u - ku) ** 2 + (v - kv) ** 2)
    sim = fx.get("key_similarity", effects.DEFAULT_FX["key_similarity"])
    return np.clip((0.68 * d - sim) / 0.08, 0, 1)


def apply(rgb, fx: dict | None, background=None):
    """*rgb*: uint8 array (h, w, 3). *background*: uint8 array of the same size
    shown through a keyed colour (black when None). Returns uint8 (h, w, 3)."""
    fx = effects.sanitize(fx)
    x = rgb.astype(np.float32) / 255.0
    x = np.clip(grade(x, fx), 0, 1)
    if fx.get("key"):
        a = key_alpha(x, fx)[..., None]
        back = (background.astype(np.float32) / 255.0) if background is not None else 0.0
        x = x * a + back * (1 - a)
    return (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)
