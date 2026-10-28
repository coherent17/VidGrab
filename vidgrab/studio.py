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
from array import array
from dataclasses import dataclass
from pathlib import Path

from yt_dlp.utils import parse_duration

from vidgrab.downloader import (
    DEFAULT_MP3_BITRATE,
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
    _parse_trim,
    find_ffmpeg,
    get_app_dir,
    get_bundle_dir,
)

SAMPLE_RATE = 48000
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


@dataclass
class Clip:
    """One timeline entry: a media file plus an optional in/out range."""

    path: str
    start: str | None = None
    end: str | None = None


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


@dataclass
class _ResolvedClip:
    path: Path
    start: float
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0


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
            "format=duration:stream=codec_type,width,height,duration:stream_disposition=attached_pic",
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
    }


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


def subtitle_scale(height: int) -> float:
    return height / REFERENCE_HEIGHT


def _ass_ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    # braces open override blocks and backslashes start escapes in ASS
    text = text.replace("\\", "\uff3c").replace("{", "(").replace("}", ")")
    return text.strip().replace("\r\n", "\n").replace("\n", "\\N")


def format_ass(
    cues: list[SubtitleCue], width: int, height: int, style: SubtitleStyle | None = None
) -> str:
    """Render cues as an ASS script for a *width* x *height* frame.

    Cues with an x/y are pinned there (``\\an5\\pos``: text centred on the
    point); the rest use the style's top / bottom placement."""
    style = style or SubtitleStyle()
    k = subtitle_scale(height)
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
    align = 8 if style.position == "top" else 2
    margin = round(SUBTITLE_MARGIN * k)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{style.font or SUBTITLE_FONT_NAME},{size},{colour},"
            f"&H000000FF,{outline_colour},&H80000000,{-1 if style.bold else 0},0,0,0,"
            f"100,100,0,0,{border},"
            f"{outline},{shadow},{align},{margin},{margin},{margin},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fade_ms = round(max(0.0, style.fade) * 1000)
    for cue in sorted(cues, key=lambda c: c.start):
        tags = ""
        if cue.x is not None and cue.y is not None:
            px = round(min(max(cue.x, 0.0), 1.0) * width)
            py = round(min(max(cue.y, 0.0), 1.0) * height)
            anchor = cue.anchor if 1 <= cue.anchor <= 9 else 5
            tags += f"\\an{anchor}\\pos({px},{py})"
        if fade_ms:
            # never fade for longer than half the line is on screen
            ms = min(fade_ms, round((cue.end - cue.start) * 500))
            tags += f"\\fad({ms},{ms})"
        tag = f"{{{tags}}}" if tags else ""
        lines.append(
            f"Dialogue: 0,{_ass_ts(cue.start)},{_ass_ts(cue.end)},Default,,0,0,0,,"
            f"{tag}{_ass_text(cue.text)}"
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
    for root in (get_app_dir(), get_bundle_dir()):
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
) -> None:
    """Run ffmpeg, mapping its ``-progress`` output onto a 0..100 percentage."""
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

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_tail.append(line.rstrip())
            del err_tail[:-12]

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
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
    if proc.returncode != 0:
        if on_log:
            for line in err_tail[-6:]:
                on_log(line)
        raise RuntimeError(
            tr("ffmpeg failed to render the project (exit code {code}).", code=proc.returncode)
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


def _audio_norm(label: str) -> str:
    return (
        f"{label}aresample={SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
        "asetpts=PTS-STARTPTS"
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
    for i in range(len(clips)):
        graph.append(f"{_audio_norm(f'[{i}:a:0]')}[a{i}]")

    # a crossfade can't be longer than either neighbour
    fade = 0.0
    if crossfade > 0 and len(clips) > 1:
        shortest = min(c.duration for c in clips)
        fade = max(0.0, min(crossfade, shortest / 2))

    total = sum(c.duration for c in clips)
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


def build_video_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    resolution: str = "auto",
    fps: int = 30,
    subtitles_file: str | None = None,
    fonts_dir: str | None = None,
    music: BackgroundMusic | None = None,
    music_has_audio: bool = True,
) -> tuple[list[str], float]:
    """ffmpeg argv + output length for a video montage.

    *subtitles_file* (an ASS script from `format_ass`) / *fonts_dir* are
    paths relative to the ffmpeg working
    directory — the subtitles filter's own escaping rules make absolute
    Windows paths (``C:\\…``) fragile, so callers run ffmpeg from a temp dir."""
    width, height = _canvas(clips, resolution)
    total = sum(c.duration for c in clips)
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    next_input = len(clips)

    # silent stand-ins for clips that have no audio track
    silence: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not c.has_audio:
            cmd += [
                "-f", "lavfi", "-t", f"{c.duration:.3f}",
                "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
            ]
            silence[i] = next_input
            next_input += 1

    music_idx = None
    if music is not None and music_has_audio:
        if music.loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(music.path)]
        music_idx = next_input
        next_input += 1

    graph: list[str] = []
    for i, _c in enumerate(clips):
        graph.append(
            f"[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
        )
        src = f"[{silence[i]}:a]" if i in silence else f"[{i}:a:0]"
        graph.append(f"{_audio_norm(src)}[a{i}]")
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
    graph.append(f"{pairs}concat=n={len(clips)}:v=1:a=1[vc][ac]")

    vout = "[vc]"
    if subtitles_file:
        opts = f"filename={subtitles_file}"
        if fonts_dir:
            opts += f":fontsdir={fonts_dir}"
        graph.append(f"[vc]subtitles={opts}[vs]")
        vout = "[vs]"

    aout = "[ac]"
    if music is not None and music_idx is not None:
        bed = (
            f"{_audio_norm(f'[{music_idx}:a:0]')},"
            f"atrim=0:{total:.3f},volume={max(0.0, music.volume):.3f}"
        )
        if music.fade_out and total > 4:
            bed += f",afade=t=out:st={total - 3:.3f}:d=3"
        graph.append(f"{bed}[bg]")
        graph.append(f"[ac]volume={max(0.0, music.original_volume):.3f}[orig]")
        graph.append(
            "[orig][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[am]"
        )
        aout = "[am]"

    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", vout, "-map", aout,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd, total


def compose_video(
    clips: list[Clip],
    output_file: str | Path,
    *,
    resolution: str = "auto",
    subtitles: list[SubtitleCue] | None = None,
    subtitle_style: SubtitleStyle | None = None,
    music: BackgroundMusic | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Join video clips, then optionally burn in subtitles and add music."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=True, translate=translate)

    music_has_audio = True
    if music is not None:
        mpath = Path(music.path)
        if not mpath.is_file():
            raise FileNotFoundError(tr("File not found: {src}", src=mpath))
        info = probe_media(mpath, translate=translate)
        music_has_audio = info["has_audio"]
        if not music_has_audio and on_log:
            on_log(tr("Background music has no audio track; skipping it."))
        music = BackgroundMusic(
            path=str(mpath.resolve()),
            volume=music.volume,
            original_volume=music.original_volume,
            loop=music.loop,
            fade_out=music.fade_out,
        )

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
            if subtitle_style and subtitle_style.font != SUBTITLE_FONT_NAME:
                wanted.append(font_file(subtitle_style.font))
            for font in filter(None, wanted):
                (work / "fonts").mkdir(exist_ok=True)
                shutil.copy2(font, work / "fonts" / font.name)
                fonts_name = "fonts"
        cmd, total = build_video_command(
            ffmpeg, resolved, out,
            resolution=resolution,
            subtitles_file=subs_name,
            fonts_dir=fonts_name,
            music=music,
            music_has_audio=music_has_audio,
        )
        _run_with_progress(
            cmd, total, cwd=work, label=tr("Rendering…"),
            on_progress=on_progress, on_log=on_log, translate=translate,
        )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out
