"""Qt-free clip effects: colour looks, clean-up, stabilising, green screen,
smooth slow motion, and ready-made text styles.

A clip's effects are one small dict (`fx`) so they can be saved in a project,
compared for undo, and handed to the renderer unchanged. Only the keys in
`DEFAULT_FX` exist; `sanitize()` drops unknown keys, clamps numbers and removes
values equal to the default, so ``{}`` always means "no effects"."""
from __future__ import annotations

import re

# one-click looks: name -> ffmpeg filters (applied before the sliders)
LOOKS: dict[str, str] = {
    "none": "",
    "cinematic": "colorbalance=rs=-0.08:bs=0.1:rh=0.1:bh=-0.08,eq=contrast=1.12:saturation=1.08",
    "warm": "colorbalance=rs=0.08:rm=0.05:bs=-0.1:bm=-0.05,eq=saturation=1.05",
    "cool": "colorbalance=rs=-0.08:bs=0.1:bm=0.05,eq=saturation=0.97",
    "bw": "hue=s=0,eq=contrast=1.1",
    "vivid": "eq=contrast=1.1:saturation=1.45",
    "vintage": "curves=preset=vintage,eq=saturation=0.9",
}

# slider ranges: (default, low, high)
RANGES: dict[str, tuple[float, float, float]] = {
    "brightness": (0.0, -0.5, 0.5),
    "contrast": (1.0, 0.5, 1.8),
    "saturation": (1.0, 0.0, 2.0),
    "warmth": (0.0, -1.0, 1.0),
    "sharpen": (0.0, 0.0, 1.0),
    "denoise": (0.0, 0.0, 1.0),
    "key_similarity": (0.15, 0.02, 0.5),
}

DEFAULT_FX: dict = {
    "look": "none",
    **{k: v[0] for k, v in RANGES.items()},
    "lut": "",  # a .cube file
    "stabilize": False,
    "smooth": False,  # fill in frames when the clip plays slower than normal
    "key": "",  # '#RRGGBB' colour to make see-through (green screen)
    "key_bg": "",  # picture shown behind it (empty = black)
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
GREEN = "#00FF00"


def sanitize(fx: dict | None) -> dict:
    """Known keys only, numbers clamped, defaults removed."""
    out: dict = {}
    for key, value in (fx or {}).items():
        if key not in DEFAULT_FX:
            continue
        if key == "look":
            value = value if value in LOOKS else "none"
        elif key in RANGES:
            _, lo, hi = RANGES[key]
            try:
                value = round(min(max(float(value), lo), hi), 3)
            except (TypeError, ValueError):
                continue
        elif key in ("stabilize", "smooth"):
            value = bool(value)
        elif key == "key":
            value = value if isinstance(value, str) and _HEX.match(value) else ""
        else:
            value = value if isinstance(value, str) else ""
        if value != DEFAULT_FX[key]:
            out[key] = value
    if "key_bg" in out and "key" not in out:
        del out["key_bg"]
    return out


def edit_tuple(fx: dict | None) -> tuple:
    """A hashable, order-free form for undo snapshots."""
    return tuple(sorted(sanitize(fx).items()))


def needs_lut(fx: dict) -> bool:
    return bool(fx.get("lut"))


def color_chain(fx: dict, lut_name: str | None = None) -> list[str]:
    """Filters for the look, the optional LUT and the sliders."""
    fx = sanitize(fx)
    chain: list[str] = []
    if LOOKS.get(fx.get("look", "none")):
        chain.append(LOOKS[fx["look"]])
    if lut_name:  # the .cube file sits in the render's working folder
        chain.append(f"lut3d=file={lut_name}")
    b, c, s = (fx.get(k, DEFAULT_FX[k]) for k in ("brightness", "contrast", "saturation"))
    if (b, c, s) != (0.0, 1.0, 1.0):
        chain.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}")
    w = fx.get("warmth", 0.0)
    if w:  # warm = more red, less blue (shadows and highlights alike)
        chain.append(f"colorbalance=rs={0.15 * w:.3f}:rh={0.1 * w:.3f}:bs={-0.15 * w:.3f}:bh={-0.1 * w:.3f}")
    return chain


def clean_chain(fx: dict) -> list[str]:
    """Noise clean-up, then sharpening (in that order: sharpening first would
    sharpen the noise)."""
    fx = sanitize(fx)
    chain: list[str] = []
    n = fx.get("denoise", 0.0)
    if n:
        luma = 2 + 12 * n
        chain.append(f"hqdn3d={luma:.2f}:{luma * 0.75:.2f}:{luma * 1.5:.2f}:{luma * 1.2:.2f}")
    s = fx.get("sharpen", 0.0)
    if s:
        chain.append(f"unsharp=5:5:{1.6 * s:.2f}:5:5:0")
    return chain


def stabilize_chain(trf_name: str) -> str:
    return f"vidstabtransform=input={trf_name}:smoothing=30:zoom=0:optzoom=1"


def detect_filter(trf_name: str) -> str:
    return f"vidstabdetect=shakiness=6:accuracy=9:result={trf_name}"


def source_chain(fx: dict, *, trf_name: str | None = None, lut_name: str | None = None) -> str:
    """Everything done on the clip's own picture before it is framed, as a
    comma-joined chain with a trailing comma (or '' when there is nothing)."""
    parts: list[str] = []
    if trf_name:
        parts.append(stabilize_chain(trf_name))
    parts += clean_chain(fx)
    parts += color_chain(fx, lut_name)
    return "".join(p + "," for p in parts)


def smooth_filter(fps: int) -> str:
    """Motion-interpolate to *fps*: makes slow motion look like real slow motion
    instead of repeated frames."""
    return f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"


def key_filter(fx: dict) -> str:
    """Turn the key colour see-through ('' when no key is set)."""
    fx = sanitize(fx)
    if not fx.get("key"):
        return ""
    sim = fx.get("key_similarity", DEFAULT_FX["key_similarity"])
    return f"chromakey=color=0x{fx['key'][1:].upper()}:similarity={sim:.3f}:blend=0.08"


def has_effects(fx: dict | None) -> bool:
    return bool(sanitize(fx))


# ── text templates ────────────────────────────────────────────────────────

# name -> (default text, look, animation, anchor, x, y); anchor / x / y place it
TEXT_TEMPLATES: dict[str, dict] = {
    "title": {
        "text": "Your title",
        "look": {"size": 80, "bold": True, "color": "#FFFFFF"},
        "animation": "pop", "anchor": 5, "x": 0.5, "y": 0.45,
    },
    "lower_third": {
        "text": "Name Surname",
        "look": {"size": 40, "bold": True, "color": "#FFFFFF",
                 "background": "#1E3A8A", "bg_opacity": 0.85},
        "animation": "slide", "anchor": 1, "x": 0.06, "y": 0.86,
    },
    "quote": {
        "text": "A line worth remembering",
        "look": {"size": 46, "bold": False, "color": "#FFE9A8"},
        "animation": "typewriter", "anchor": 5, "x": 0.5, "y": 0.5,
    },
    "caption_box": {
        "text": "Caption",
        "look": {"size": 34, "bold": True, "color": "#FFFFFF",
                 "background": "#000000", "bg_opacity": 0.6},
        "animation": "none", "anchor": 2, "x": 0.5, "y": 0.9,
    },
}


def kenburns_scale(base_width: float, start: float, end: float,
                   direction: str = "in", amount: float = 0.2) -> str:
    """The `scale` width expression for a slow zoom on a picture that is on
    screen from *start* to *end* (montage seconds). 'out' starts zoomed in."""
    span = max(end - start, 0.1)
    prog = f"clip((t-{start:.3f})/{span:.3f},0,1)"
    k = prog if direction == "in" else f"(1-{prog})"
    return f"w='trunc({base_width:.1f}*(1+{amount:.3f}*{k})/2)*2':h=-2:eval=frame"
