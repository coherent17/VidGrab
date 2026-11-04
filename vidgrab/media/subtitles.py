"""Subtitle files (SRT / VTT / ASS), wrapping and fonts."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from yt_dlp.utils import parse_duration

from vidgrab.core.downloader import (
    asset_roots,
)
from vidgrab.media.model import (
    ANIM_IN,
    ANIMATIONS,
    HIGHLIGHT,
    LOOK_KEYS,
    SUBTITLE_FONT_FILE,
    SUBTITLE_FONT_NAME,
    SubtitleCue,
    SubtitleStyle,
    ass_colour,
    color_hex,
    source_index,
    typewriter_time,
    word_spans,
)

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


def format_vtt(cues: list[SubtitleCue]) -> str:
    """Render cues as WebVTT (what web video players and many editors read)."""
    body = "\n".join(
        f"{_srt_ts(c.start).replace(',', '.')} --> {_srt_ts(c.end).replace(',', '.')}\n"
        f"{c.text.strip()}\n"
        for c in sorted(cues, key=lambda c: c.start))
    return "WEBVTT\n\n" + body


def format_transcript(cues: list[SubtitleCue], timestamps: bool = False) -> str:
    """The words only, one line per subtitle (optionally with the time each begins),
    for notes, articles or pasting into another tool."""
    lines = []
    for c in sorted(cues, key=lambda c: c.start):
        text = " ".join(c.text.split())
        if text:
            lines.append(f"[{_srt_ts(c.start)[:-4]}] {text}" if timestamps else text)
    return "\n".join(lines) + ("\n" if lines else "")


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


def _visible(chars: list[str]) -> list[str]:
    return [c for c in chars if c != "\\N"]


def _span_of(spans: list[tuple[int, int, float, float]], i: int) -> int | None:
    return next((k for k, (a, b, _t0, _t1) in enumerate(spans) if a <= i < b), None)


def char_end_times(src: list[int], spans: list[tuple[int, int, float, float]]) -> list[float]:
    """When each character of the wrapped text has been said (a word's time is
    shared by its characters; others, like spaces, go with the word before)."""
    out, clock = [], 0.0
    for i in src:
        k = _span_of(spans, i)
        if k is not None:
            a, b, t0, t1 = spans[k]
            clock = max(clock, t0 + (i - a + 1) * (t1 - t0) / (b - a))
        out.append(clock)
    return out


def active_word(spans: list[tuple[int, int, float, float]], el: float) -> int | None:
    """The word being said *el* seconds into the line."""
    return next((k for k, (_a, _b, t0, t1) in enumerate(spans) if t0 <= el < t1), None)


def _timed_karaoke(chars: list[str], src: list[int],
                   spans: list[tuple[int, int, float, float]]) -> str:
    """Karaoke tags that sweep each word while it is said (\\kf per character)."""
    ends = char_end_times(src, spans)
    out, clock, n = [], 0.0, 0
    for c in chars:
        if c == "\\N":
            out.append(c)
            continue
        end = ends[n]
        n += 1
        cs = max(0, round((end - clock) * 100))
        clock = max(clock, end)
        out.append(f"{{\\kf{cs}}}{c}")
    return "".join(out)


def _bgr(color: str) -> str:
    h = color_hex(color)
    return f"&H{h[5:7]}{h[3:5]}{h[1:3]}&"


def _highlight_events(cue: SubtitleCue, name: str, tags: str, chars: list[str], src: list[int],
                      spans: list[tuple[int, int, float, float]], eff: SubtitleStyle,
                      fade_ms: int) -> list[str]:
    """One event per word: the whole line, with the word being said in the
    highlight colour (and a touch bigger)."""
    base = color_hex(eff.color)
    hot = "#FFFFFF" if base.upper() == HIGHLIGHT else HIGHLIGHT
    owner = []  # the span of every visible character
    for i in src:
        owner.append(_span_of(spans, i))
    length = cue.end - cue.start
    marks = [0.0] + [min(t0, length) for _a, _b, t0, _t1 in spans] + [length]
    events = []
    for k in range(len(spans) + 1):  # k == 0: nothing is said yet
        t0, t1 = marks[k], marks[k + 1]
        if t1 - t0 <= 0.01:
            continue
        body, n, on = [], 0, False
        for c in chars:
            if c == "\\N":
                body.append(c)
                continue
            hit = owner[n] is not None and owner[n] == k - 1
            n += 1
            if hit != on:
                body.append(f"{{\\1c{_bgr(hot if hit else base)}\\fscx110\\fscy110}}" if hit else
                            f"{{\\1c{_bgr(base)}\\fscx100\\fscy100}}")
                on = hit
            body.append(c)
        if on:
            body.append(f"{{\\1c{_bgr(base)}\\fscx100\\fscy100}}")
        events.append((cue.start + t0, cue.start + t1, "".join(body)))
    out = []
    for j, (a, b, body) in enumerate(events):
        fad = f"\\fad({fade_ms if j == 0 else 0},{fade_ms if j == len(events) - 1 else 0})" \
            if fade_ms and (j == 0 or j == len(events) - 1) else ""
        tag = f"{{{tags}{fad}}}" if tags or fad else ""
        out.append(f"Dialogue: 0,{_ass_ts(a)},{_ass_ts(b)},{name},,0,0,0,,{tag}{body}")
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
        wrapped = wrap_cue_text(cue.text, size, width - 2 * margin)
        text = _ass_text("\n".join(wrapped))
        spans = word_spans(cue)
        src = source_index(cue.text, wrapped)
        if anim == "highlight" and spans and len(src) == len(_visible(_ass_chars(text))):
            lines.extend(_highlight_events(cue, name, re.sub(r"\\fad\([^)]*\)", "", tags),
                                           _ass_chars(text), src, spans,
                                           cue_style(cue, style), min(fade_ms, length_ms // 2)))
            continue
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
        elif anim in ("karaoke", "highlight"):  # the colour sweeps across the line
            chars = _ass_chars(text)
            visible = _visible(chars)
            if spans and len(src) == len(visible):  # at the pace the words are said
                text = _timed_karaoke(chars, src, spans)
            else:
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
