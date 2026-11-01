"""VidGrab Studio — join clips into a montage or medley with ffmpeg.

* ``compose_audio`` joins songs / song sections into one track (optional
  crossfade between consecutive clips).
* ``compose_video`` joins video clips (normalized to one resolution / fps),
  optionally burns in subtitles and mixes a background-music bed.

Everything renders in a single ffmpeg pass built from one filter graph, so
there is no generational quality loss from intermediate files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from array import array
from dataclasses import dataclass, replace
from pathlib import Path

from yt_dlp.utils import parse_duration

from vidgrab.downloader import (
    DEFAULT_MP3_BITRATE,
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
    _parse_trim,
    asset_roots,
    find_ffmpeg,
)
from vidgrab.gpu import HwEncoder, detect_encoder, video_args

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


# how a line comes on screen (the shared fade still applies on top)
ANIMATIONS = ("none", "pop", "slide", "typewriter", "karaoke")
LOOK_KEYS = ("color", "background", "bg_opacity", "size", "bold", "font")
ANIM_IN = {"pop": 0.25, "slide": 0.3}  # seconds the entrance takes


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


# ── ffprobe ───────────────────────────────────────────────────────────────


def find_ffprobe() -> str | None:
    """Locate ffprobe beside ffmpeg (bundled or not), then PATH."""
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        peer = Path(ffmpeg).parent / name
        if peer.is_file():
            return str(peer)
    return shutil.which(name)


def probe_media(path: str | Path, *, translate: TranslateFn | None = None) -> dict:
    """Return duration and stream facts for a local media file."""
    tr = translate or _noop_tr
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise RuntimeError(tr("ffprobe is required to read media files."))
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            ("format=duration:stream=codec_type,width,height,duration,avg_frame_rate"
             ":stream_disposition=attached_pic"),
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=False, timeout=30,
        **_no_window(),
    )
    if proc.returncode != 0:
        raise RuntimeError(tr("Could not read media file: {name}", name=Path(path).name))
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    # cover art in MP3/M4A shows up as a 1-frame "video" stream — ignore it
    video = [
        s for s in streams
        if s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
    ]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = _to_float((data.get("format") or {}).get("duration"))
    if duration is None:
        for s in video + audio:
            duration = _to_float(s.get("duration"))
            if duration:
                break
    return {
        "duration": duration or 0.0,
        "has_video": bool(video),
        "has_audio": bool(audio),
        "width": int(video[0].get("width") or 0) if video else 0,
        "height": int(video[0].get("height") or 0) if video else 0,
        "fps": _frame_rate(video[0].get("avg_frame_rate")) if video else 0.0,
    }


def _frame_rate(value: object) -> float:
    """ffprobe's "30000/1001" → 29.97 (0.0 if unknown)."""
    num, _, den = str(value or "").partition("/")
    try:
        rate = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return rate if 1 <= rate <= 240 else 0.0


def thumbnail_png(path: str | Path, at: float = 0.0, height: int = 72) -> bytes | None:
    """One video frame at *at* seconds as PNG bytes (None if it can't be read)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    proc = subprocess.run(
        [
            ffmpeg, "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale=-2:{height}", "-f", "image2pipe",
            "-vcodec", "png", "-",
        ],
        capture_output=True, check=False, timeout=30, **_no_window(),
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def waveform(path: str | Path, buckets: int = 600, rate: int = 2000) -> list[float]:
    """Peak level (0..1) of the audio in *buckets* equal slices of the file."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
         "-f", "s16le", "-"],
        capture_output=True, check=False, timeout=120, **_no_window(),
    )
    if proc.returncode != 0 or not proc.stdout:
        return []
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    n = len(samples)
    if not n:
        return []
    buckets = max(1, min(buckets, n))
    step = n / buckets
    peaks = [
        max(abs(v) for v in samples[int(i * step): max(int((i + 1) * step), int(i * step) + 1)])
        / 32768
        for i in range(buckets)
    ]
    top = max(peaks) or 1.0
    return [p / top for p in peaks]


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _no_window() -> dict:
    """subprocess kwargs that keep a console window from flashing on Windows."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def _resolve(
    clips: list[Clip],
    *,
    need_video: bool,
    translate: TranslateFn | None,
) -> list[_ResolvedClip]:
    tr = translate or _noop_tr
    if not clips:
        raise RuntimeError(tr("Add at least one clip first."))
    resolved: list[_ResolvedClip] = []
    for clip in clips:
        src = Path(clip.path)
        if not src.is_file():
            raise FileNotFoundError(tr("File not found: {src}", src=src))
        info = probe_media(src, translate=translate)
        start, end = _parse_trim(clip.start, clip.end, translate=translate)
        total = info["duration"]
        if total and start >= total:
            raise RuntimeError(
                tr(
                    "Clip start is past the end of {name}.",
                    name=src.name,
                )
            )
        stop = min(end, total) if total else end
        if stop == float("inf"):
            raise RuntimeError(
                tr("Could not determine the length of {name}.", name=src.name)
            )
        if need_video and not info["has_video"]:
            raise RuntimeError(
                tr("{name} has no video stream.", name=src.name)
            )
        if not need_video and not info["has_audio"]:
            raise RuntimeError(
                tr("{name} has no audio stream.", name=src.name)
            )
        resolved.append(
            _ResolvedClip(
                path=src,
                start=start,
                duration=stop - start,
                has_video=info["has_video"],
                has_audio=info["has_audio"],
                width=info["width"],
                height=info["height"],
                transition=clip.transition,
                transition_duration=clip.transition_duration,
                fit=clip.fit if clip.fit in FRAMINGS else "fit",
                zoom=max(1.0, float(clip.zoom or 1.0)),
                pan_x=min(max(float(clip.pan_x), 0.0), 1.0),
                pan_y=min(max(float(clip.pan_y), 0.0), 1.0),
                gain=min(clip.gain(), 2.0),
                speed=min(max(float(clip.speed or 1.0), SPEED_RANGE[0]), SPEED_RANGE[1]),
                denoise=bool(clip.denoise),
            )
        )
    return resolved


# ── subtitles ─────────────────────────────────────────────────────────────

_SRT_TIME = re.compile(
    r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)


def parse_srt(text: str) -> list[SubtitleCue]:
    """Parse SubRip text into cues (lenient about numbering / blank lines)."""
    cues: list[SubtitleCue] = []
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + int(m.group(4).ljust(3, "0")) / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + int(m.group(8).ljust(3, "0")) / 1000
            body = "\n".join(lines[i + 1:]).strip()
            if body and end > start:
                cues.append(SubtitleCue(start, end, body))
            break
    return cues


def retime_cues(
    cues: list[SubtitleCue], start: float = 0.0, end: float | None = None,
    speed: float | None = None,
) -> list[SubtitleCue]:
    """Map cues onto a trimmed (*start*..*end*) and sped-up copy of a video."""
    rate = speed or 1.0
    out = []
    for c in cues:
        s, e = max(c.start, start), min(c.end, end) if end is not None else c.end
        if e - s <= 0.05:
            continue
        out.append(SubtitleCue((s - start) / rate, (e - start) / rate, c.text,
                               c.x, c.y, c.anchor))
    return out


def _srt_ts(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt(cues: list[SubtitleCue]) -> str:
    """Render cues as SubRip text (sorted by start time)."""
    out = []
    for n, cue in enumerate(sorted(cues, key=lambda c: c.start), 1):
        out.append(f"{n}\n{_srt_ts(cue.start)} --> {_srt_ts(cue.end)}\n{cue.text.strip()}\n")
    return "\n".join(out)


def parse_timecode(value: str) -> float | None:
    """'90', '1:30', '1:02:03.5' -> seconds (None if invalid)."""
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    secs = parse_duration(value)
    return float(secs) if secs is not None else None


# Style sizes are expressed against libass' classic 288-line reference
# frame (what SRT renders against); scale them to the real output height.
REFERENCE_HEIGHT = 288
SUBTITLE_MARGIN = 28  # vertical margin for default placement, reference units


def box_padding(font_px: float) -> int:
    """Space between the text and the edge of its background box."""
    return max(2, round(font_px * 0.18))


def subtitle_scale(width: int, height: int) -> float:
    """Size factor of a *width* x *height* frame. The shorter side counts: a
    9:16 video is as wide as a 16:9 one is tall, and text sized from its height
    would be twice too big for its width."""
    return min(width, height) / REFERENCE_HEIGHT


def _ass_ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ── wrapping ─────────────────────────────────────────────────────────────
# libass only breaks lines at spaces, so a long Chinese line (no spaces) runs off
# the frame, and its "smart" wrapping differs from any simple rule. We break the
# lines ourselves, with one function used by both the ASS file and the preview,
# so they agree on where. Widths are estimated (not measured) for the same reason.

_CJK = "\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef"
_WRAP_TOKEN = re.compile(rf"[{_CJK}]|[^\s{_CJK}]+\s*|\s+")
_NO_BREAK_BEFORE = tuple("，。！？、；：）」』》〉】,.!?;:)]}%")
_LINE_RATIO = 1.45  # libass font size is the line height; a CJK em is that / 1.45


def text_advance(text: str, size: float) -> float:
    """Estimated width of *text* at ASS font size *size* (the line height)."""
    em = size / _LINE_RATIO
    return sum(em if "\u2e80" <= ch <= "\uffef" and ch not in " " else em * (0.3 if ch.isspace() else 0.58)
               for ch in text)


def wrap_line(text: str, width, max_w: float) -> list[str]:
    """*text* broken into lines no wider than *max_w* (*width* measures a
    string): between CJK characters, or after the spaces between other words,
    never before a closing mark."""
    if max_w <= 0 or width(text) <= max_w:
        return [text]
    lines: list[str] = []
    cur = ""
    for token in _WRAP_TOKEN.findall(text):
        trial = cur + token
        if cur and width(trial.rstrip()) > max_w and not token.startswith(_NO_BREAK_BEFORE):
            lines.append(cur.rstrip())
            cur = token.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [text]


def wrap_cue_text(text: str, size: float, max_w: float) -> list[str]:
    """The lines a subtitle is shown on: its own line breaks, each wrapped to
    *max_w* at font size *size*."""
    return [seg for line in text.split("\n")
            for seg in wrap_line(line, lambda part: text_advance(part, size), max_w)]


def _ass_text(text: str) -> str:
    # braces open override blocks and backslashes start escapes in ASS
    text = text.replace("\\", "\uff3c").replace("{", "(").replace("}", ")")
    return text.strip().replace("\r\n", "\n").replace("\n", "\\N")


def cue_style(cue: SubtitleCue, style: SubtitleStyle) -> SubtitleStyle:
    """The shared style with this line's own look on top."""
    look = {k: v for k, v in (cue.look or {}).items() if k in LOOK_KEYS}
    return replace(style, **look) if look else style


def _ass_style_line(name: str, style: SubtitleStyle, k: float, align: int, margin: int) -> str:
    colour = ass_colour(style.color)
    size = round(style.size * k)
    if style.background:
        # BorderStyle 3 = opaque box; libass paints it in OutlineColour and
        # uses Outline as the padding around the text
        border, outline, shadow = 3, box_padding(size), 0
        outline_colour = ass_colour(style.background, style.bg_opacity)
    else:
        border = 1
        outline = max(1, round(2 * k)) if style.outline else 0
        shadow = max(1, round(k))
        outline_colour = "&H00000000"
    # karaoke: the part not yet sung is light grey (or white under a white line)
    unsung = "&H00AAAAAA" if colour.upper() == "&H00FFFFFF" else "&H00FFFFFF"
    return (
        f"Style: {name},{style.font or SUBTITLE_FONT_NAME},{size},{colour},"
        f"{unsung},{outline_colour},&H80000000,{-1 if style.bold else 0},0,0,0,"
        f"100,100,0,0,{border},{outline},{shadow},{align},{margin},{margin},{margin},1"
    )


def _ass_chars(text: str) -> list[str]:
    """ASS text split into characters, keeping \\N line breaks whole."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("\\N", i):
            out.append("\\N")
            i += 2
        else:
            out.append(text[i])
            i += 1
    return out


def format_ass(
    cues: list[SubtitleCue], width: int, height: int, style: SubtitleStyle | None = None
) -> str:
    """Render cues as an ASS script for a *width* x *height* frame.

    Cues with an x/y are pinned there (``\\an5\\pos``: text centred on the
    point); the rest use the style's top / bottom placement. Each distinct
    look (a line's own colours / size over the shared style) is one ASS
    style; animations are override tags."""
    style = style or SubtitleStyle()
    k = subtitle_scale(width, height)
    align = 8 if style.position == "top" else 2
    margin = round(SUBTITLE_MARGIN * k)
    looks: dict[tuple, str] = {}
    names: list[str] = []
    styles_text: list[str] = []
    for cue in [SubtitleCue(0, 0, ""), *cues]:  # the shared style is always "Default"
        eff = cue_style(cue, style)
        key = tuple(getattr(eff, f) for f in ("color", "background", "bg_opacity", "size",
                                              "bold", "font", "outline"))
        if key not in looks:
            looks[key] = "Default" if not looks else f"Look{len(looks)}"
            styles_text.append(_ass_style_line(looks[key], eff, k, align, margin))
        names.append(looks[key])
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",  # no automatic wrapping: wrap_cue_text already broke the lines
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        *styles_text,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fade_ms = round(max(0.0, style.fade) * 1000)
    order = sorted(range(len(cues)), key=lambda n: cues[n].start)
    for n in order:
        cue, name = cues[n], names[n + 1]
        anim = cue.animation if cue.animation in ANIMATIONS else "none"
        length_ms = round((cue.end - cue.start) * 1000)
        tags = ""
        if cue.x is not None and cue.y is not None:
            px = round(min(max(cue.x, 0.0), 1.0) * width)
            py = round(min(max(cue.y, 0.0), 1.0) * height)
            anchor = cue.anchor if 1 <= cue.anchor <= 9 else 5
        else:  # where the style would put it, so it can be moved / animated
            anchor, px = align, round(width / 2)
            py = margin if align == 8 else height - margin
        if cue.x is not None or anim == "slide":
            if anim == "slide":
                rise = round(height * 0.05)
                tags += (f"\\an{anchor}\\move({px},{py + rise},{px},{py},0,"
                         f"{round(ANIM_IN['slide'] * 1000)})")
            else:
                tags += f"\\an{anchor}\\pos({px},{py})"
        if fade_ms:
            # never fade for longer than half the line is on screen
            ms = min(fade_ms, length_ms // 2)
            tags += f"\\fad({ms},{ms})"
        if anim == "pop":
            ms = round(ANIM_IN["pop"] * 1000)
            tags += f"\\fscx40\\fscy40\\t(0,{ms},\\fscx100\\fscy100)"
        elif anim == "slide" and not fade_ms:
            tags += f"\\fad({round(ANIM_IN['slide'] * 700)},0)"
        size = round(cue_style(cue, style).size * k)
        text = _ass_text("\n".join(wrap_cue_text(cue.text, size, width - 2 * margin)))
        if anim == "typewriter":
            chars = _ass_chars(text)
            visible = [c for c in chars if c != "\\N"]
            step = typewriter_time(cue.end - cue.start) * 1000 / max(1, len(visible))
            # reveal each channel back to the style's own alpha: a plain
            # \\alpha&H00& would turn a see-through box or shadow opaque
            eff = cue_style(cue, style)
            box = ass_colour(eff.background, eff.bg_opacity)[2:4] if eff.background else "00"
            shown_tags = f"\\1a&H00&\\3a&H{box}&\\4a&H80&"
            out, shown = [], 0
            for c in chars:
                if c == "\\N":
                    out.append(c)
                    continue
                t = round(shown * step)
                out.append(f"{{\\alpha&HFF&\\t({t},{t + 1},{shown_tags})}}{c}")
                shown += 1
            text = "".join(out)
        elif anim == "karaoke":  # the colour sweeps across over the whole line
            chars = _ass_chars(text)
            visible = [c for c in chars if c != "\\N"]
            cs = max(1, round(length_ms / 10 * 0.9 / max(1, len(visible))))
            text = "".join(c if c == "\\N" else f"{{\\kf{cs}}}{c}" for c in chars)
        tag = f"{{{tags}}}" if tags else ""
        lines.append(
            f"Dialogue: 0,{_ass_ts(cue.start)},{_ass_ts(cue.end)},{name},,0,0,0,,"
            f"{tag}{text}"
        )
    return "\n".join(lines) + "\n"


def system_fonts() -> dict[str, Path]:
    """Installed font families -> a regular-weight font file for each.

    libass in a bundled ffmpeg can't always see system fonts, so the file is
    copied next to the subtitles at render time."""
    found: dict[str, Path] = {}
    if sys.platform == "win32":
        try:
            import winreg
        except ImportError:  # pragma: no cover - non-Windows
            return found
        windir = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts"
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts"),
        ]
        for root, sub in keys:
            try:
                key = winreg.OpenKey(root, sub)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                family = re.sub(r"\s*\(.*?\)\s*$", "", name).split(" & ")[0].strip()
                if re.search(r"\b(Bold|Italic|Light|Black|Thin|Medium|Semibold)\b", family):
                    continue
                path = Path(value) if Path(value).is_absolute() else windir / value
                if path.suffix.lower() in (".ttf", ".otf", ".ttc") and path.is_file():
                    found.setdefault(family, path)
        return found
    if sys.platform == "darwin":  # no fontconfig: read the font folders (file name = family)
        for folder in (Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
                       Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"):
            try:
                files = sorted(folder.iterdir())
            except OSError:
                continue
            for path in files:
                family = path.stem
                if path.suffix.lower() not in (".ttf", ".otf") or re.search(
                        r"\b(Bold|Italic|Light|Black|Thin|Medium|Semibold|Oblique)\b", family, re.IGNORECASE):
                    continue
                found.setdefault(family, path)
        return found
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return found
    try:
        out = subprocess.run(
            [fc_list, "--format", "%{family[0]}\t%{style[0]}\t%{file}\n"],
            capture_output=True, text=True, check=False, timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return found

    def rank(style: str) -> int:  # lower = closer to the plain weight
        st = style.lower()
        if st in ("regular", "book", "normal", "roman", "medium"):
            return 0
        return 2 if re.search(r"bold|italic|oblique|black|heavy", st) else 1

    best: dict[str, tuple[int, Path]] = {}
    for line in out.splitlines():
        family, _, rest = line.partition("\t")
        style, _, file = rest.partition("\t")
        path = Path(file)
        family = family.strip()
        if not family or path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        r = rank(style)
        if family not in best or r < best[family][0]:
            best[family] = (r, path)
    return {fam: path for fam, (_r, path) in sorted(best.items()) if path.is_file()}


def font_file(family: str) -> Path | None:
    if family == SUBTITLE_FONT_NAME:
        return _subtitle_font()
    return system_fonts().get(family)


def _subtitle_font() -> Path | None:
    for root in asset_roots():
        p = root / "assets" / SUBTITLE_FONT_FILE
        if p.is_file():
            return p
    return None


# ── ffmpeg runner with live progress ──────────────────────────────────────


def _run_with_progress(
    cmd: list[str],
    total: float,
    *,
    cwd: Path | None = None,
    label: str,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    translate: TranslateFn | None,
    stall_s: float | None = None,
) -> None:
    """Run ffmpeg, mapping its ``-progress`` output onto a 0..100 percentage.
    With *stall_s*, ffmpeg is killed (and RuntimeError raised) if it prints no
    progress for that long, so a graphics driver that stops answering can't
    hang the render."""
    tr = translate or _noop_tr
    if on_log:
        on_log(" ".join(cmd))
    full = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1", *cmd[1:]]
    proc = subprocess.Popen(
        full,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_window(),
    )
    err_tail: list[str] = []
    err_first: list[str] = []  # the first error lines usually name the cause

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_tail.append(line.rstrip())
            del err_tail[:-12]
            low = line.lower()
            if len(err_first) < 6 and any(k in low for k in (
                    "error", "invalid", "not match", "mismatch", "failed", "cannot",
                    "unable", "no such")):
                err_first.append(line.rstrip())

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    last_seen = [time.monotonic()]
    stalled = threading.Event()

    def watch() -> None:
        while proc.poll() is None:
            time.sleep(1.0)
            if stall_s and time.monotonic() - last_seen[0] > stall_s:
                stalled.set()
                proc.kill()
                return

    if stall_s:
        threading.Thread(target=watch, daemon=True).start()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            last_seen[0] = time.monotonic()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and total > 0 and on_progress:
                secs = (_to_float(value) or 0) / 1_000_000
                on_progress(label, max(0.0, min(99.0, secs / total * 100)))
    except BaseException:
        # the callback raised (e.g. the user cancelled): don't leave ffmpeg running
        proc.kill()
        proc.wait()
        raise
    proc.wait()
    t.join(timeout=2)
    if stalled.is_set():
        raise RuntimeError(tr("ffmpeg stopped responding (no progress for {s} s).", s=round(stall_s or 0)))
    if proc.returncode != 0:
        if on_log:
            for line in err_tail[-6:]:
                on_log(line)
        # ffmpeg's own last words say *why* (shown in the error dialog too)
        lines = err_first + [x for x in err_tail[-6:] if x not in err_first]
        detail = "\n".join(line for line in lines if line.strip())
        raise RuntimeError(
            tr("ffmpeg failed to render the project (exit code {code}).", code=proc.returncode)
            + (f"\n\n{detail}" if detail else "")
        )


def unique_path(path: Path) -> Path:
    """*path*, or *path* with ' (2)', ' (3)', … appended if it already exists."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _require_ffmpeg(translate: TranslateFn | None) -> str:
    tr = translate or _noop_tr
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            tr("ffmpeg is required for the Studio. Install ffmpeg or place it next to the app.")
        )
    return ffmpeg


def _input_args(clip: _ResolvedClip) -> list[str]:
    args: list[str] = []
    if clip.start:
        args += ["-ss", f"{clip.start:.3f}"]
    args += ["-t", f"{clip.duration:.3f}", "-i", str(clip.path)]
    return args


# every audio join restates the format, so the encoder never sees it change
# mid-stream (some ffmpeg builds' AAC encoder stops with EINVAL if it does)
_AUDIO_FMT = (f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo")


# a gentle hum / hiss remover: rumble below 70 Hz out, then a spectral denoiser that
# learns the steady noise floor (it leaves speech and music alone)
DENOISE = "highpass=f=70,afftdn=nr=14:nf=-35"
# the loudness YouTube, Shorts and most players aim for (integrated LUFS, true peak dB)
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"


def _audio_norm(label: str, gain: float = 1.0, denoise: bool = False) -> str:
    return (
        f"{label}aresample={SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
        + (f"{DENOISE}," if denoise else "")
        + "asetpts=PTS-STARTPTS"
        + ("" if gain == 1.0 else f",volume={gain:.3f}")  # clip level / mute
    )


# ── music medley ──────────────────────────────────────────────────────────


def build_audio_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    crossfade: float = 0.0,
    bitrate: str | None = None,
) -> tuple[list[str], float]:
    """ffmpeg argv + expected output length for an audio join."""
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    graph: list[str] = []
    for i, c in enumerate(clips):
        tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
        graph.append(f"{_audio_norm(f'[{i}:a:0]', c.gain)}{tempo}[a{i}]")

    # a crossfade can't be longer than either neighbour
    fade = 0.0
    if crossfade > 0 and len(clips) > 1:
        shortest = min(c.out_duration for c in clips)
        fade = max(0.0, min(crossfade, shortest / 2))

    total = sum(c.out_duration for c in clips)
    if len(clips) == 1:
        out = "[a0]"
    elif fade > 0:
        prev = "[a0]"
        for i in range(1, len(clips)):
            nxt = f"[x{i}]"
            graph.append(f"{prev}[a{i}]acrossfade=d={fade:.3f}:c1=tri:c2=tri{nxt}")
            prev = nxt
        out = prev
        total -= fade * (len(clips) - 1)
    else:
        ins = "".join(f"[a{i}]" for i in range(len(clips)))
        graph.append(f"{ins}concat=n={len(clips)}:v=0:a=1[aout]")
        out = "[aout]"

    if output.suffix.lower() == ".m4a":  # AAC: whole 1024-sample frames (see video)
        graph.append(f"{out}{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
        out = "[aenc]"
    cmd += ["-filter_complex", ";".join(graph), "-map", out, "-vn"]
    if output.suffix.lower() == ".m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{bitrate or DEFAULT_MP3_BITRATE}k"]
    elif output.suffix.lower() == ".wav":
        cmd += ["-c:a", "pcm_s16le"]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{bitrate or DEFAULT_MP3_BITRATE}k"]
    cmd.append(str(output))
    return cmd, total


def compose_audio(
    clips: list[Clip],
    output_file: str | Path,
    *,
    crossfade: float = 0.0,
    bitrate: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Join songs / song sections into one audio file."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=False, translate=translate)
    out = unique_path(Path(output_file))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd, total = build_audio_command(
        ffmpeg, resolved, out, crossfade=crossfade, bitrate=bitrate
    )
    _run_with_progress(
        cmd, total, label=tr("Rendering…"),
        on_progress=on_progress, on_log=on_log, translate=translate,
    )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out


# ── video montage ─────────────────────────────────────────────────────────


def _even(n: float) -> int:
    return max(2, round(n / 2) * 2)


def canvas_size(resolution: str, first_width: int, first_height: int) -> tuple[int, int]:
    """Output frame size for *resolution* ("auto" follows the first clip)."""
    preset = RESOLUTIONS.get(resolution)
    if preset:
        return preset
    w, h = first_width or 1280, first_height or 720
    # cap "auto" at 1080 on the short side to keep renders reasonable
    short = min(w, h)
    if short > 1080:
        scale = 1080 / short
        w, h = w * scale, h * scale
    return _even(w), _even(h)


def _canvas(clips: list[_ResolvedClip], resolution: str) -> tuple[int, int]:
    return canvas_size(resolution, clips[0].width, clips[0].height)


def _frame_filter(c: _ResolvedClip, width: int, height: int) -> str:
    """Scale (+ crop) one clip onto the output canvas."""
    if c.fit == "fit" and c.zoom == 1.0:  # the whole picture, centred, with bars
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    # cover (fill) or contain (fit) a box `zoom` times the canvas, then cut the
    # canvas out of it at the pan point and pad whatever is still missing
    mode = "increase" if c.fit == "fill" else "decrease"
    zw, zh = _even(width * c.zoom), _even(height * c.zoom)
    return (f"scale={zw}:{zh}:force_original_aspect_ratio={mode}:force_divisible_by=2,"
            f"crop=w='min(iw,{width})':h='min(ih,{height})':"
            f"x='(iw-ow)*{c.pan_x:.4f}':y='(ih-oh)*{c.pan_y:.4f}',"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")


def _music_bed(label: str, m: BackgroundMusic, total: float) -> str:
    """One song as the montage hears it: its part, looped or not, coming in
    at its offset, with its own fades, volume and the end-of-video fade."""
    bed = _audio_norm(label)
    if m.trimmed():
        end = m.end or m.length or None
        bed += f",atrim=start={m.start:.3f}" + (f":end={end:.3f}" if end else "")
        bed += ",asetpts=PTS-STARTPTS"
        if m.loop and end and end > m.start:
            bed += f",aloop=loop=-1:size={int((end - m.start) * SAMPLE_RATE)}"
    if m.offset > 0:  # comes in later on the timeline
        # cut to the length still needed and restart the timestamps first
        # (adelay misreads aloop's output), then rebuild them from the
        # sample count (atrim / afade misread adelay's)
        bed += (f",atrim=0:{max(total - m.offset, 0.01):.3f},asetpts=PTS-STARTPTS"
                f",adelay={int(m.offset * 1000)}:all=1,asetpts=N/SR/TB")
    bed += f",atrim=0:{total:.3f}"
    part = m.part()
    if m.fade > 0:
        bed += f",afade=t=in:st={m.offset:.3f}:d={m.fade:.3f}"
        if not m.loop and part:
            stop = min(m.offset + part, total)
            bed += f",afade=t=out:st={max(m.offset, stop - m.fade):.3f}:d={m.fade:.3f}"
    bed += f",volume={max(0.0, m.volume):.3f}"
    if m.fade_out and total > 4:
        bed += f",afade=t=out:st={total - 3:.3f}:d=3"
    return bed


def _image_filter(img: ImageOverlay, frame_width: int) -> str:
    """Scale a picture to its width on the frame, with opacity and fades."""
    w = _even(frame_width * min(max(img.width, 0.01), 4.0))
    chain = f"format=rgba,scale={w}:-2"
    if img.opacity < 1.0:
        chain += f",colorchannelmixer=aa={max(img.opacity, 0.0):.3f}"
    if img.fade > 0:
        fade = min(img.fade, (img.end - img.start) / 2)
        chain += (f",fade=t=in:st={img.start:.3f}:d={fade:.3f}:alpha=1"
                  f",fade=t=out:st={img.end - fade:.3f}:d={fade:.3f}:alpha=1")
    angle = img.rotation % 360
    if angle:  # turn around the centre; the corners it uncovers stay transparent
        rad = f"{angle:.3f}*PI/180"
        chain += f",rotate=a={rad}:c=none:ow=rotw({rad}):oh=roth({rad})"
    return chain


def build_video_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    resolution: str = "auto",
    fps: int = 30,
    subtitles_file: str | None = None,
    fonts_dir: str | None = None,
    music: Music = None,
    music_has_audio: bool = True,
    quality: str = "balanced",
    images: list[ImageOverlay] | None = None,
    encoder: HwEncoder | None = None,
    normalize_loudness: bool = False,
) -> tuple[list[str], float]:
    """ffmpeg argv + output length for a video montage. With *normalize_loudness*
    the finished mix is brought to `LOUDNESS` (and clips with `denoise` are cleaned).

    *subtitles_file* (an ASS script from `format_ass`) / *fonts_dir* are
    paths relative to the ffmpeg working
    directory — the subtitles filter's own escaping rules make absolute
    Windows paths (``C:\\…``) fragile, so callers run ffmpeg from a temp dir."""
    width, height = _canvas(clips, resolution)
    preset, crf, abr = RENDER_QUALITY.get(quality, RENDER_QUALITY["balanced"])
    overlaps = transition_overlaps([c.out_duration for c in clips],
                                   [(c.transition, c.transition_duration) for c in clips])
    total = sum(c.out_duration for c in clips) - sum(overlaps)
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    next_input = len(clips)

    # silent stand-ins for clips that have no audio track
    silence: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not c.has_audio:
            cmd += [
                "-f", "lavfi", "-t", f"{c.out_duration:.3f}",
                "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
            ]
            silence[i] = next_input
            next_input += 1

    # pictures: one looped still per overlay, only as long as it is needed
    image_inputs: list[int] = []
    for img in images or []:
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{min(img.end, total):.3f}",
                "-i", str(img.path)]
        image_inputs.append(next_input)
        next_input += 1

    songs = _songs(music) if music_has_audio else []
    song_inputs: list[int] = []
    for m in songs:
        if m.loop and not m.trimmed():  # a trimmed part loops in the graph
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(m.path)]
        song_inputs.append(next_input)
        next_input += 1

    graph: list[str] = []
    for i, c in enumerate(clips):
        graph.append(
            f"[{i}:v:0]{_frame_filter(c, width, height)},setsar=1,"
            # speed before fps, so the output still has a steady frame rate
            + (f"setpts=(PTS-STARTPTS)/{c.speed:.6g}," if c.speed != 1.0 else "")
            + f"fps={fps},format=yuv420p,setpts=PTS-STARTPTS"
            # xfade needs both inputs on one timebase, and concat changes it
            # ffmpeg 7.0's setpts forgets the frame rate, which xfade requires:
            # restate it, then put every input on one timebase
            f"{f',fps={fps},settb=AVTB' if any(overlaps) else ''}[v{i}]"
        )
        if i in silence:
            graph.append(f"{_audio_norm(f'[{silence[i]}:a]')}[a{i}]")
        else:
            tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
            graph.append(f"{_audio_norm(f'[{i}:a:0]', c.gain, c.denoise)}{tempo}[a{i}]")
    if not any(overlaps):
        pairs = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
        graph.append(f"{pairs}concat=n={len(clips)}:v=1:a=1[vc][ac]")
    else:
        # join pairwise: xfade / acrossfade where a transition overlaps the
        # clips, a plain concat at cuts; `at` = where clip i starts in the output
        vprev, aprev, at = "[v0]", "[a0]", clips[0].out_duration
        for i in range(1, len(clips)):
            d = overlaps[i]
            vnext, anext = ("[vc]", "[ac]") if i == len(clips) - 1 else (f"[vx{i}]", f"[ax{i}]")
            if d > 0:
                at -= d
                graph.append(f"{vprev}[v{i}]xfade=transition={clips[i].transition}:"
                             f"duration={d:.3f}:offset={at:.3f}{vnext}")
                graph.append(f"{aprev}[a{i}]acrossfade=d={d:.3f}:c1=tri:c2=tri,{_AUDIO_FMT}{anext}")
            else:
                # concat drops the frame rate / timebase that the next xfade
                # checks (some ffmpeg builds refuse the mismatch): restate them
                graph.append(f"{vprev}[v{i}]concat=n=2:v=1:a=0,fps={fps},settb=AVTB{vnext}")
                graph.append(f"{aprev}[a{i}]concat=n=2:v=0:a=1,{_AUDIO_FMT}{anext}")
            at += clips[i].out_duration
            vprev, aprev = vnext, anext

    vout = "[vc]"
    # pictures go under the subtitles, each only between its start and end
    for k, (img, idx) in enumerate(zip(images or [], image_inputs)):
        graph.append(f"[{idx}:v]{_image_filter(img, width)}[im{k}]")
        graph.append(
            f"{vout}[im{k}]overlay=x='main_w*{img.x:.4f}-overlay_w/2'"
            f":y='main_h*{img.y:.4f}-overlay_h/2'"
            f":enable='between(t,{img.start:.3f},{img.end:.3f})':eof_action=pass[vo{k}]")
        vout = f"[vo{k}]"
    if subtitles_file:
        opts = f"filename={subtitles_file}"
        if fonts_dir:
            opts += f":fontsdir={fonts_dir}"
        graph.append(f"{vout}subtitles={opts}[vs]")
        vout = "[vs]"

    aout = "[ac]"
    if songs:
        for k, (m, idx) in enumerate(zip(songs, song_inputs)):
            graph.append(f"{_music_bed(f'[{idx}:a:0]', m, total)}[bg{k}]")
        graph.append(f"[ac]volume={max(0.0, songs[0].original_volume):.3f}[orig]")
        beds = "".join(f"[bg{k}]" for k in range(len(songs)))
        graph.append(f"[orig]{beds}amix=inputs={len(songs) + 1}:duration=first"
                     ":dropout_transition=0:normalize=0[am]")
        aout = "[am]"

    # hand AAC whole 1024-sample frames (crossfades emit bigger ones, which some
    # ffmpeg builds pass straight to the encoder and it rejects)
    loud = f"{LOUDNESS}," if normalize_loudness else ""
    graph.append(f"{aout}{loud}{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
    aout = "[aenc]"
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", vout, "-map", aout,
        *video_args(encoder, preset, crf),
        "-c:a", "aac", "-b:a", abr,
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd, total


# ── two videos at once (split screen) ─────────────────────────────────────

# layout -> how two videos share the frame; the first is drawn first, so in
# "pip" the second sits on top of it
SPLIT_LAYOUTS = ("side", "stack", "wide", "pip")
SPLIT_AUDIO = ("both", "first", "second", "none")
SPLIT_LENGTHS = ("longest", "shortest")


def _down(n: float) -> int:  # rounded down to even, so a gap is never squeezed
    return max(2, int(n) // 2 * 2)


def split_panels(layout: str, width: int, height: int, gap: int = 0) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) of the two videos on a *width* x *height* frame; *gap*
    pixels of background stay between side-by-side panels. The preview in the
    window calls this too, so both show the same picture."""
    gap = max(0, int(gap))
    if layout == "stack":
        h = _down((height - gap) / 2)
        return [(0, 0, width, h), (0, height - h, width, h)]
    if layout == "wide":  # a big picture and a narrow one beside it
        a = _down((width - gap) * 0.66)
        b = _down(width - gap - a)
        return [(0, 0, a, height), (width - b, 0, b, height)]
    if layout == "pip":  # the second video as a small window in the corner
        w, h = _even(width * 0.32), _even(height * 0.32)
        margin = _even(min(width, height) * 0.03)
        return [(0, 0, width, height), (width - w - margin, height - h - margin, w, h)]
    w = _down((width - gap) / 2)
    return [(0, 0, w, height), (width - w, 0, w, height)]


def split_canvas(resolution: str) -> tuple[int, int]:
    return RESOLUTIONS.get(resolution) or (1920, 1080)


def build_split_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    layout: str = "side",
    resolution: str = "1080p",
    fps: int = 30,
    gap: int = 0,
    audio: str = "both",
    length: str = "longest",
    quality: str = "balanced",
    encoder: HwEncoder | None = None,
) -> tuple[list[str], float]:
    """ffmpeg argv + output length for two videos playing at the same time.
    With *length* "longest" the shorter video holds its last picture."""
    if len(clips) != 2:
        raise ValueError("a split screen needs exactly two videos")
    width, height = split_canvas(resolution)
    preset, crf, abr = RENDER_QUALITY.get(quality, RENDER_QUALITY["balanced"])
    durations = [c.out_duration for c in clips]
    total = min(durations) if length == "shortest" else max(durations)
    keep = {"both": (1.0, 1.0), "first": (1.0, 0.0), "second": (0.0, 1.0)}.get(audio, (0.0, 0.0))
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    silence: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not c.has_audio:
            cmd += ["-f", "lavfi", "-t", f"{c.out_duration:.3f}",
                    "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo"]
            silence[i] = len(clips) + len(silence)

    panels = split_panels(layout, width, height, gap)
    graph = [f"color=c=black:s={width}x{height}:r={fps}:d={total:.3f},format=yuv420p[base]"]
    vprev = "[base]"
    for i, (c, (x, y, w, h)) in enumerate(zip(clips, panels)):
        hold = total - durations[i]
        graph.append(
            f"[{i}:v:0]{_frame_filter(c, w, h)},setsar=1,"
            + (f"setpts=(PTS-STARTPTS)/{c.speed:.6g}," if c.speed != 1.0 else "")
            + f"fps={fps},format=yuv420p,setpts=PTS-STARTPTS"
            + (f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.04 else "")
            + f"[p{i}]")
        graph.append(f"{vprev}[p{i}]overlay=x={x}:y={y}[o{i}]")
        vprev = f"[o{i}]"
        label = f"[{silence[i]}:a]" if i in silence else f"[{i}:a:0]"
        tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
        graph.append(f"{_audio_norm(label, keep[i] * c.gain)}{tempo}[a{i}]")
    graph.append("[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                 f"alimiter=limit=0.95,{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", vprev, "-map", "[aenc]", "-t", f"{total:.3f}",
        *video_args(encoder, preset, crf),
        "-c:a", "aac", "-b:a", abr,
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd, total


def compose_split(
    clips: list[Clip],
    output_file: str | Path,
    *,
    layout: str = "side",
    resolution: str = "1080p",
    gap: int = 0,
    audio: str = "both",
    length: str = "longest",
    quality: str = "balanced",
    hardware: bool = False,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Play two videos at the same time in one frame (see `split_panels`)
    and save the result as an MP4 that can be used like any other clip."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if len(clips) != 2:
        raise RuntimeError(tr("Choose two videos first."))
    if layout not in SPLIT_LAYOUTS:
        layout = "side"
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=True, translate=translate)
    out = unique_path(Path(output_file).resolve())
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vidgrab-split-") as tmp:
        _encode(
            lambda enc: build_split_command(
                ffmpeg, resolved, out, layout=layout, resolution=resolution, gap=gap,
                audio=audio, length=length, quality=quality, encoder=enc),
            ffmpeg, Path(tmp), hardware=hardware, on_progress=on_progress,
            on_log=on_log, translate=translate)
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out


EXPORT_FORMATS = (".mp4", ".gif", ".mp3", ".m4a", ".wav")


def _export_args(kind: str, gif_width: int, gif_fps: int) -> list[str]:
    """ffmpeg arguments that turn the rendered MP4 into *kind*."""
    if kind == ".gif":  # two-pass palette: GIF has 256 colours, pick the right ones
        graph = (f"[0:v]fps={gif_fps},scale={_even(gif_width)}:-2:flags=lanczos,split[a][b];"
                 "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
        return ["-filter_complex", graph, "-an", "-loop", "0"]
    if kind == ".mp3":
        return ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
    if kind == ".m4a":
        return ["-vn", "-c:a", "aac", "-b:a", "192k"]
    if kind == ".wav":
        return ["-vn", "-c:a", "pcm_s16le"]
    raise ValueError(f"unsupported export format {kind}")


def _encode(
    build,
    ffmpeg: str,
    work: Path,
    *,
    hardware: bool,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    translate: TranslateFn | None,
) -> float:
    """Run `build(encoder)` -> (argv, length): on the graphics card first when
    *hardware* and one works, and again on the CPU if that render fails or
    stalls. Returns the output length."""
    tr = translate or _noop_tr
    encoder = detect_encoder(ffmpeg) if hardware else None
    for attempt in (encoder, None) if encoder else (None,):
        cmd, total = build(attempt)
        if attempt and on_log:
            on_log(tr("Encoding on the graphics card ({name})", name=attempt.label))
        try:
            _run_with_progress(
                cmd, total, cwd=work, label=tr("Rendering…"),
                on_progress=on_progress, on_log=on_log, translate=translate,
                stall_s=HW_STALL_S if attempt else None,
            )
            return total
        except RuntimeError as exc:
            if attempt is None:
                raise
            if on_log:  # a driver problem in the middle of the render: do it on the CPU
                on_log(tr("The graphics card could not encode this ({err}); "
                          "rendering on the CPU instead", err=str(exc).splitlines()[-1]))
    raise RuntimeError("unreachable")  # pragma: no cover


def compose_video(
    clips: list[Clip],
    output_file: str | Path,
    *,
    resolution: str = "auto",
    subtitles: list[SubtitleCue] | None = None,
    subtitle_style: SubtitleStyle | None = None,
    music: Music = None,
    quality: str = "balanced",
    images: list[ImageOverlay] | None = None,
    gif_width: int = 480,
    gif_fps: int = 15,
    hardware: bool = False,
    normalize_loudness: bool = False,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Join video clips, then optionally burn in subtitles and add music.
    The output's suffix picks the format: .mp4, or .gif / .mp3 / .m4a / .wav
    (rendered as MP4 first, then converted). With *hardware*, the video is
    encoded on the graphics card when one works (see `gpu.detect_encoder`),
    and again on the CPU if that render fails."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=True, translate=translate)

    songs: list[BackgroundMusic] = []
    for m in _songs(music):
        mpath = Path(m.path)
        if not mpath.is_file():
            raise FileNotFoundError(tr("File not found: {src}", src=mpath))
        info = probe_media(mpath, translate=translate)
        if not info["has_audio"]:
            if on_log:
                on_log(tr("Background music has no audio track; skipping it."))
            continue
        songs.append(replace(m, path=str(mpath.resolve()), start=max(0.0, m.start),
                             offset=max(0.0, m.offset), length=info["duration"]))

    out = unique_path(Path(output_file).resolve())
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vidgrab-studio-") as tmp:
        work = Path(tmp)
        subs_name = fonts_name = None
        if subtitles:
            width, height = _canvas(resolved, resolution)
            (work / "subs.ass").write_text(
                format_ass(subtitles, width, height, subtitle_style), encoding="utf-8"
            )
            subs_name = "subs.ass"
            # hand libass the font files themselves: the bundled CJK font (also
            # the fallback for Chinese glyphs) plus the chosen font, if another
            wanted = [_subtitle_font()]
            fonts = {subtitle_style.font} if subtitle_style else set()
            fonts |= {c.look["font"] for c in subtitles if c.look and c.look.get("font")}
            wanted += [font_file(f) for f in fonts if f and f != SUBTITLE_FONT_NAME]
            for font in filter(None, wanted):
                (work / "fonts").mkdir(exist_ok=True)
                shutil.copy2(font, work / "fonts" / font.name)
                fonts_name = "fonts"
        # GIF / audio-only exports: render the video first, then convert it
        kind = out.suffix.lower()
        render_to = out if kind == ".mp4" else work / "render.mp4"
        total = _encode(
            lambda enc: build_video_command(
                ffmpeg, resolved, render_to,
                resolution=resolution,
                subtitles_file=subs_name,
                fonts_dir=fonts_name,
                music=songs,
                images=[img for img in images or [] if img.end > img.start],
                quality=quality,
                encoder=enc,
                normalize_loudness=normalize_loudness,
            ),
            ffmpeg, work, hardware=hardware, on_progress=on_progress, on_log=on_log,
            translate=translate)
        if render_to != out:
            if on_progress:
                on_progress(tr("Converting…"), None)
            _run_with_progress(
                [ffmpeg, "-y", "-i", str(render_to), *_export_args(kind, gif_width, gif_fps),
                 str(out)],
                total, cwd=work, label=tr("Converting…"),
                on_progress=on_progress, on_log=on_log, translate=translate,
            )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out
