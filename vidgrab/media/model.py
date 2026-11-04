"""Studio data model: clips, cues, styles, constants."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SAMPLE_RATE = 48000
HW_STALL_S = 120.0  # a graphics-card render with no progress for this long is abandoned
SUBTITLE_FONT_FILE = "NotoSansTC-Regular.otf"
SUBTITLE_FONT_NAME = "Noto Sans CJK TC"

# label -> (width, height); None means "match the first clip"
RESOLUTIONS: dict[str, tuple[int, int] | None] = {
    "auto": None,
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}

# render quality presets: libx264 preset, CRF, AAC bitrate
RENDER_QUALITY: dict[str, tuple[str, int, str]] = {
    "fast": ("veryfast", 23, "160k"),
    "balanced": ("medium", 20, "192k"),
    "high": ("slow", 17, "256k"),
}

# named presets (older settings used these names); styles store "#RRGGBB"
SUBTITLE_COLORS: dict[str, str] = {
    "white": "#FFFFFF",
    "yellow": "#FFE500",
    "cyan": "#00FFFF",
    "pink": "#FF69B4",
    "black": "#000000",
}


def color_hex(color: str | None, default: str = "#FFFFFF") -> str:
    """'#rrggbb' / preset name -> '#RRGGBB'."""
    if not color:
        return default
    value = SUBTITLE_COLORS.get(color.lower(), color)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.upper()
    return default


def ass_colour(color: str | None, opacity: float = 1.0) -> str:
    """'#RRGGBB' + opacity -> ASS '&HAABBGGRR' (AA = transparency)."""
    h = color_hex(color)
    alpha = round((1.0 - min(max(opacity, 0.0), 1.0)) * 255)
    return f"&H{alpha:02X}{h[5:7]}{h[3:5]}{h[1:3]}"


# ── data model ────────────────────────────────────────────────────────────


# ffmpeg xfade transitions offered in the Studio, in display order
# ("none" = a plain cut). Keys are xfade transition names.
TRANSITIONS = ("none", "fade", "fadeblack", "fadewhite", "dissolve", "wipeleft",
               "slideleft", "circleopen", "zoomin")
FRAMINGS = ("fit", "fill")  # whole picture with bars / fill the frame, cropping


@dataclass
class Clip:
    """One timeline entry: a media file plus an optional in/out range."""

    path: str
    start: str | None = None
    end: str | None = None
    # how this clip begins after the previous one (ignored on the first clip)
    transition: str = "none"
    transition_duration: float = 0.0
    # framing on the output canvas: "fit" (bars) or "fill" (crop), extra
    # zoom >= 1, and which part stays in view when cropped (0..1, 0.5 = centre)
    fit: str = "fit"
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    volume: float = 1.0  # level of the clip's own sound (0..2)
    muted: bool = False
    speed: float = 1.0  # 0.25 .. 4: the part plays this many times as fast
    denoise: bool = False  # take the steady background hiss / hum out of the clip's sound
    fx: dict = field(default_factory=dict)  # picture effects, see vidgrab.effects

    def gain(self) -> float:
        return 0.0 if self.muted else max(0.0, float(self.volume))


def transition_overlaps(durations: list[float], transitions: list[tuple[str, float]]) -> list[float]:
    """How much each clip overlaps the one before it (0 for the first clip
    and for cuts). A transition can take at most half of either neighbour."""
    out = [0.0] * len(durations)
    for i in range(1, len(durations)):
        kind, length = transitions[i]
        if kind in TRANSITIONS and kind != "none" and length > 0:
            out[i] = round(max(0.0, min(length, durations[i - 1] / 2, durations[i] / 2)), 3)
    return out


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str
    # anchor point as a fraction of the frame (0..1); None = use the style's
    # default top / bottom placement
    x: float | None = None
    y: float | None = None
    # which point of the text sits on (x, y), numpad-style like ASS \\an:
    # 7 8 9 = top-left/centre/right, 4 5 6 = middle, 1 2 3 = bottom
    anchor: int = 5
    # this line's own look, over the shared SubtitleStyle (any of LOOK_KEYS)
    look: dict | None = None
    animation: str = "none"  # one of ANIMATIONS
    # when each word is said (auto captions): [char_from, char_to, t_from, t_to], the
    # times in seconds after the line's start; cleared when the text is edited
    words: list | None = None


# how a line comes on screen (the shared fade still applies on top)
ANIMATIONS = ("none", "pop", "slide", "typewriter", "karaoke", "highlight")
HIGHLIGHT = "#FFD400"  # the word being said, in the "highlight" animation (white text)
LOOK_KEYS = ("color", "background", "bg_opacity", "size", "bold", "font")
ANIM_IN = {"pop": 0.25, "slide": 0.3}  # seconds the entrance takes


def word_spans(cue: SubtitleCue) -> list[tuple[int, int, float, float]]:
    """The cue's timed words if they still fit its text, else none."""
    out: list[tuple[int, int, float, float]] = []
    last = 0
    for w in cue.words or []:
        try:
            a, b, t0, t1 = int(w[0]), int(w[1]), float(w[2]), float(w[3])
        except (TypeError, ValueError, IndexError):
            return []
        if not (last <= a < b <= len(cue.text)) or t1 < t0:
            return []
        out.append((a, b, t0, t1))
        last = b
    return out


def source_index(text: str, lines: list[str]) -> list[int]:
    """For every character of the wrapped *lines*, where it sits in *text*
    (wrapping drops the space it broke at)."""
    out, p = [], 0
    for line in lines:
        for ch in line:
            while p < len(text) and text[p] != ch:
                p += 1
            out.append(min(p, len(text) - 1))
            p += 1
    return out


def typewriter_time(cue_length: float) -> float:
    """How long the typewriter takes to write out a whole line."""
    return min(1.5, max(0.2, cue_length * 0.6))


@dataclass
class SubtitleStyle:
    size: int = 24
    color: str = "#FFFFFF"  # text colour ('#RRGGBB' or a preset name)
    position: str = "bottom"  # bottom | top
    outline: bool = True  # black outline (used when there is no background)
    background: str | None = None  # box colour behind the text; None = transparent
    bg_opacity: float = 0.6  # 0..1
    font: str = SUBTITLE_FONT_NAME
    bold: bool = False
    fade: float = 0.0  # seconds each line takes to fade in and out


@dataclass
class BackgroundMusic:
    path: str
    volume: float = 0.35  # music level, 0..1
    original_volume: float = 1.0  # level of the clips' own audio, 0..1
    loop: bool = True
    fade_out: bool = True
    # the part of the song that plays (seconds in the song; end None = to its
    # end) and when it comes in on the video timeline; looping repeats that part
    start: float = 0.0
    end: float | None = None
    offset: float = 0.0
    length: float = 0.0  # the song's full length (filled in by compose_video)
    fade: float = 0.0  # fade in / out at this song's own edges (s), e.g. for crossfades
    duck: bool = False  # lower the music while the clips' own sound is loud (speech)

    def trimmed(self) -> bool:
        return self.start > 0 or self.end is not None

    def part(self) -> float | None:
        """Length of the part of the song that plays (None if unknown)."""
        end = self.end or self.length or None
        return end - self.start if end else None


Music = BackgroundMusic | list[BackgroundMusic] | None

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


@dataclass
class ImageOverlay:
    """A picture shown over the video from *start* to *end* (montage time).

    Placed by its centre (x, y as fractions of the frame) and sized by its
    width as a fraction of the frame width (height follows the picture)."""

    path: str
    start: float
    end: float
    x: float = 0.5
    y: float = 0.5
    width: float = 0.3
    opacity: float = 1.0
    fade: float = 0.0  # fade in / out (s)
    rotation: float = 0.0  # degrees, clockwise, around the centre
    motion: str = "none"  # slow zoom while shown: none | zoom_in | zoom_out (Ken Burns)
    # a "blur" / "pixel" box hides what is under it (a plate, a face, a name): there is
    # no picture then (path is ""), the box is `width` x `height` of the frame, centred
    # on (x, y), and `strength` (0..1) says how hard it is hidden
    kind: str = "image"  # image | blur | pixel
    height: float = 0.2
    strength: float = 0.6

    def is_picture(self) -> bool:
        return self.kind == "image"


COVER_KINDS = ("blur", "pixel")  # the overlay kinds that cover part of the video


def _songs(music: Music) -> list[BackgroundMusic]:
    if music is None:
        return []
    return [music] if isinstance(music, BackgroundMusic) else list(music)


@dataclass
class _ResolvedClip:
    path: Path
    start: float
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    transition: str = "none"
    transition_duration: float = 0.0
    fit: str = "fit"
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    gain: float = 1.0  # 0 = muted
    speed: float = 1.0
    denoise: bool = False
    fx: dict = field(default_factory=dict)
    trf: str | None = None  # stabilising data file in the render's work folder
    lut: str | None = None  # .cube file in the render's work folder
    matte: str | None = None  # grey matte video in the render's work folder (remove background)

    @property
    def out_duration(self) -> float:
        """How long the clip lasts in the output (its source part / speed)."""
        return self.duration / self.speed


SPEED_RANGE = (0.25, 4.0)


def _atempo(speed: float) -> str:
    """atempo for *speed*: one filter handles 0.5..2, chain more outside that."""
    parts, rest = [], speed
    while rest < 0.5:
        parts.append(0.5)
        rest /= 0.5
    while rest > 2.0:
        parts.append(2.0)
        rest /= 2.0
    parts.append(rest)
    return ",".join(f"atempo={p:.6g}" for p in parts)
