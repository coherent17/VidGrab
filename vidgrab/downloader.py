"""VidGrab download / processing logic using yt-dlp."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import parse_duration

ProgressCallback = Callable[[str, float | None], None]
LogCallback = Callable[[str], None]
TranslateFn = Callable[..., str]

DEFAULT_MP3_BITRATE = "192"

class DownloadCancelled(yt_dlp.utils.DownloadCancelled):
    """Raised from a progress callback to stop a download the user cancelled.

    Subclasses yt-dlp's own cancellation so yt-dlp lets it propagate."""


# file-name patterns (yt-dlp output templates) offered in Settings
NAME_TEMPLATES: dict[str, str] = {
    "title": "%(title)s",
    "title_id": "%(title)s [%(id)s]",
    "uploader_title": "%(uploader)s - %(title)s",
    "date_title": "%(upload_date>%Y-%m-%d)s %(title)s",
}
DEFAULT_NAME = NAME_TEMPLATES["title"]

MIN_SPEED = 0.25
MAX_SPEED = 4.0

# audio output formats: key -> (yt-dlp codec, file extension, ffmpeg encoder, lossy)
AUDIO_FORMATS: dict[str, tuple[str, str, str, bool]] = {
    "mp3": ("mp3", ".mp3", "libmp3lame", True),
    "m4a": ("m4a", ".m4a", "aac", True),
    "opus": ("opus", ".opus", "libopus", True),
    "flac": ("flac", ".flac", "flac", False),
    "wav": ("wav", ".wav", "pcm_s16le", False),
}
AUDIO_EXTS = tuple(v[1] for v in AUDIO_FORMATS.values())
_CODEC_BY_EXT = {v[1]: (v[2], v[3]) for v in AUDIO_FORMATS.values()}


def _bitrate_arg(value: str | None) -> str:
    """ffmpeg's -b:a takes bits per second: '192' (kbps, as the settings store it) -> '192k'."""
    value = str(value or DEFAULT_MP3_BITRATE)
    return value + "k" if value.isdigit() else value


def audio_format(key: str | None) -> tuple[str, str, str, bool]:
    return AUDIO_FORMATS.get(key or "mp3", AUDIO_FORMATS["mp3"])


@dataclass
class Network:
    """Settings that apply to every download (see `configure_network`)."""

    rate_limit: int | None = None  # bytes per second
    proxy: str = ""
    retries: int = 10
    archive: Path | None = None  # yt-dlp download archive (playlists skip what it lists)


NETWORK = Network()


def configure_network(*, rate_limit: int | None = None, proxy: str = "", retries: int = 10,
                      archive: str | Path | None = None) -> None:
    """Set the speed limit, proxy, retry count and download archive used by
    every later probe / download."""
    NETWORK.rate_limit = rate_limit if rate_limit and rate_limit > 0 else None
    NETWORK.proxy = (proxy or "").strip()
    NETWORK.retries = max(0, int(retries))
    NETWORK.archive = Path(archive) if archive else None


def _net_opts(*, archive: bool = False) -> dict:
    """yt-dlp options for `NETWORK` (the archive only where *archive*)."""
    opts: dict = {
        "retries": NETWORK.retries,
        "fragment_retries": NETWORK.retries,
        "extractor_retries": min(NETWORK.retries, 5),
    }
    if NETWORK.rate_limit:
        opts["ratelimit"] = NETWORK.rate_limit
    if NETWORK.proxy:
        opts["proxy"] = NETWORK.proxy
    if archive and NETWORK.archive:
        opts["download_archive"] = str(NETWORK.archive)
    return opts


def _noop_tr(text: str, **kw: object) -> str:
    return text.format(**kw) if kw else text


def _rate(data: dict) -> str:
    """' · 2.3 MB/s · 0:12' from a yt-dlp progress dict ('' when unknown)."""
    parts = []
    speed = data.get("speed")
    if speed:
        parts.append(f"{_human_size(speed)}/s")
    eta = data.get("eta")
    if eta is not None and eta >= 0:
        m, sec = divmod(int(eta), 60)
        parts.append(f"{m}:{sec:02d}")
    return "".join(f" \u00b7 {p}" for p in parts)


# ── locations ─────────────────────────────────────────────────────────────

def get_app_dir() -> Path:
    """Directory containing the app (or PyInstaller extract folder)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def get_bundle_dir() -> Path:
    """Directory next to the executable when frozen, else project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads" / "VidGrab"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def find_ffmpeg() -> str | None:
    """Locate a native ffmpeg: bundled next to exe, inside app bundle, then PATH."""
    bundle = get_bundle_dir()
    app = get_app_dir()

    if sys.platform == "win32":
        ffmpeg_cmd = "ffmpeg.exe"
        candidates: list[Path] = [
            bundle / "ffmpeg" / "win" / "ffmpeg.exe",
            bundle / "ffmpeg" / "ffmpeg.exe",
            bundle / "ffmpeg.exe",
            app / "ffmpeg" / "win" / "ffmpeg.exe",
            app / "ffmpeg" / "ffmpeg.exe",
        ]
    else:
        ffmpeg_cmd = "ffmpeg"
        candidates = [
            bundle / "ffmpeg" / "linux" / "ffmpeg",
            bundle / "ffmpeg" / "ffmpeg",
            app / "ffmpeg" / "linux" / "ffmpeg",
            app / "ffmpeg" / "ffmpeg",
        ]

    for path in candidates:
        if path.is_file():
            return str(path)

    return shutil.which(ffmpeg_cmd)


def _ensure_ffmpeg_on_path(ffmpeg: str) -> None:
    """Put the bundled ffmpeg folder on PATH so yt-dlp can find its tools."""
    _ffmpeg_dir = os.path.dirname(ffmpeg)
    if _ffmpeg_dir and _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


# ── output locating ───────────────────────────────────────────────────────

def _atempo_chain(speed: float) -> list[str]:
    """ffmpeg filters that change audio tempo to *speed* (0.5x..2.0x each)."""
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0 and len(filters) < 8:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 and len(filters) < 8:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6g}")
    return filters


def _validate_speed(
    speed: float | None,
    *,
    translate: TranslateFn | None = None,
) -> float | None:
    """Normalize a speed factor; returns None for 1.0x (no change)."""
    tr = translate or _noop_tr
    if speed is None or speed == 1.0:
        return None
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise RuntimeError(
            tr(
                "Speed must be between {lo}x and {hi}x.",
                lo=MIN_SPEED,
                hi=MAX_SPEED,
            )
        )
    return speed


def _speed_marker(speed: float | None) -> str:
    """A suffix like '_2x' to tag outputs that were sped up."""
    return f"_{speed:g}x" if speed is not None else ""


def _locate_output(
    output_path: Path, title: str, fmt: str, suffix: str, audio_ext: str = ".mp3"
) -> Path | None:
    ext = audio_ext if fmt == "mp3" else ".mp4"
    patterns = [f"*{suffix}{ext}"] if suffix else [f"*{ext}"]
    for pat in patterns:
        matches = [
            p
            for p in output_path.glob(pat)
            if p.is_file() and p.suffix.lower() not in (".part", ".ytdl")
        ]
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    return None


# ── ffmpeg helpers ────────────────────────────────────────────────────────

def _parse_trim(
    section_start: str | None,
    section_end: str | None,
    *,
    translate: TranslateFn | None = None,
) -> tuple[float, float]:
    """Validate start/end times and return (start, end) in seconds."""
    tr = translate or _noop_tr
    start = parse_duration(section_start) if section_start else 0
    end = parse_duration(section_end) if section_end else float("inf")
    if start is None:
        raise RuntimeError(
            tr(
                'Invalid start time "{t}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
                t=section_start,
            )
        )
    if end is None:
        raise RuntimeError(
            tr(
                'Invalid end time "{t}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
                t=section_end,
            )
        )
    if end <= start:
        raise RuntimeError(
            tr(
                "Trim end time must be after the start time. "
                "Got start {s}s, end {e}s.",
                s=int(start),
                e=int(end),
            )
        )
    return start, end


def _trim(
    ffmpeg: str,
    src: Path,
    dst: Path,
    start: float,
    end: float,
    video_filter: str | None = None,
    speed: float | None = None,
    audio_bitrate: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    *,
    translate: TranslateFn | None = None,
) -> None:
    tr = translate or _noop_tr
    args = [ffmpeg, "-y"]
    if start:
        args += ["-ss", str(start)]
    args += ["-i", str(src)]
    if end != float("inf"):
        args += ["-t", str(end - start)]
    args += ["-map", "0"]

    needs_encode = bool(video_filter) or speed is not None
    if not needs_encode:
        args += ["-c", "copy"]
    else:
        is_audio_out = dst.suffix.lower() in (*AUDIO_EXTS, ".aac")
        if is_audio_out:
            codec, lossy = _CODEC_BY_EXT.get(dst.suffix.lower(), ("libmp3lame", True))
            args += ["-vn", "-c:a", codec]
            if lossy:
                args += ["-b:a", _bitrate_arg(audio_bitrate)]
            if speed is not None:
                args += ["-af", ",".join(_atempo_chain(speed))]
        else:
            vf_parts: list[str] = []
            if video_filter:
                vf_parts.append(video_filter)
            if speed is not None:
                vf_parts.append(f"setpts=(PTS-STARTPTS)/{speed}+STARTPTS")
            args += ["-vf", ",".join(vf_parts)]
            args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
            if speed is not None:
                args += ["-c:a", "aac", "-b:a", "192k", "-af", ",".join(_atempo_chain(speed))]
            else:
                args += ["-c:a", "copy"]
    args.append(str(dst))

    if on_log:
        on_log(" ".join(args))
    if on_progress:
        on_progress(tr("Trimming…"), 96.0)

    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if on_log and proc.stderr:
            for line in proc.stderr.strip().splitlines()[-6:]:
                on_log(line)
        raise RuntimeError(
            tr(
                "ffmpeg failed to process the file (exit code {code}).",
                code=proc.returncode,
            )
        )


def _run_ffmpeg(
    cmd: list[str],
    *,
    on_log: LogCallback | None = None,
    error_prefix: str = "ffmpeg failed",
    translate: TranslateFn | None = None,
) -> None:
    tr = translate or _noop_tr
    if on_log:
        on_log(" ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if on_log and proc.stderr:
            for line in proc.stderr.strip().splitlines()[-6:]:
                on_log(line)
        raise RuntimeError(
            tr("{prefix} (exit code {code}).", prefix=error_prefix, code=proc.returncode)
        )


def derive_mp3(
    source: str | Path,
    output_dir: str | Path,
    *,
    audio_bitrate: str | None = None,
    audio_fmt: str = "mp3",
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Extract audio from an already-downloaded video as MP3 — or another
    audio format, *audio_fmt* (no re-download)."""
    tr = translate or _noop_tr
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(tr("File not found: {src}", src=src))

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(tr("ffmpeg is required to extract MP3 audio."))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _codec, ext, encoder, lossy = audio_format(audio_fmt)
    out = output_path / f"{src.stem}{ext}"
    out.unlink(missing_ok=True)

    if on_progress:
        on_progress(tr("Extracting audio…"), None)
    _run_ffmpeg(
        [
            ffmpeg, "-y", "-i", str(src), "-vn", "-map", "0:a:0",
            "-c:a", encoder, *(["-b:a", _bitrate_arg(audio_bitrate)] if lossy else []),
            str(out),
        ],
        on_log=on_log,
        error_prefix=tr("ffmpeg failed to extract MP3 audio"),
        translate=translate,
    )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out


# ── local file processing ─────────────────────────────────────────────────
#
# Not called by the UI any more (the Edit page became the Studio), but it is
# the tested entry point for the same trim / flip / speed post-processing
# (`_trim`) that downloads run through.

def process_local_file(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    video_filter: str | None = None,
    speed: float | None = None,
    section_start: str | None = None,
    section_end: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """
    Apply trim / flip / speed to a local media file and write the result to
    *output_dir*.

    Returns the path to the processed file.
    """
    tr = translate or _noop_tr
    speed = _validate_speed(speed, translate=translate)
    src = Path(input_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(tr("File not found: {src}", src=src))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ext = src.suffix  # keep original extension
    stem = src.stem
    final_file = output_path / f"{stem}_processed{_speed_marker(speed)}{ext}"

    do_trim = bool(section_start or section_end)
    start, end = 0.0, float("inf")
    if do_trim:
        start, end = _parse_trim(section_start, section_end, translate=translate)

    needs_ffmpeg = do_trim or video_filter or speed is not None
    if not needs_ffmpeg:
        final_file.unlink(missing_ok=True)
        shutil.copy2(src, final_file)
        if on_log:
            on_log(tr("Copied: {name}", name=final_file.name))
        if on_progress:
            on_progress(tr("Complete"), 100.0)
        return final_file

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            tr(
                "ffmpeg is required to process local files. "
                "Install ffmpeg or place it next to the app."
            )
        )
    _ensure_ffmpeg_on_path(ffmpeg)

    final_file.unlink(missing_ok=True)
    _trim(
        ffmpeg,
        src,
        final_file,
        start,
        end,
        video_filter=video_filter,
        speed=speed,
        on_progress=on_progress,
        on_log=on_log,
        translate=translate,
    )

    if on_log:
        on_log(tr("Saved: {name}", name=final_file.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return final_file


# ── YouTube downloads ─────────────────────────────────────────────────────

# Networks (and CI runners) with IPv6 but no route for it: YouTube's media
# hosts resolve to IPv6 first and the download dies with "Network is
# unreachable". Those attempts are retried over IPv4.
_UNREACHABLE = ("network is unreachable", "errno 101", "no route to host", "errno 113")


def _network_unreachable(exc: BaseException) -> bool:
    text = f"{exc}".lower()
    return any(k in text for k in _UNREACHABLE)


def _try_clients(attempt: Callable[[str, bool], object], log: LogCallback, tr: TranslateFn) -> object:
    """Run *attempt(client, ipv4)* with each player client in turn (full
    resolution first, then the reliable low-res one). After an "unreachable"
    error the same client is retried, and every later one runs, over IPv4."""
    queue = [("tv_embedded", False), ("android", False)]
    last_exc: Exception | None = None
    while queue:
        client, ipv4 = queue.pop(0)
        try:
            return attempt(client, ipv4)
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next way
            last_exc = exc
            if not ipv4 and _network_unreachable(exc):
                log(tr("Network unreachable with {client}; retrying over IPv4.", client=client))
                queue = [(client, True)] + [(c, True) for c, _v4 in queue]
                continue
            log(tr("Download failed with {client} ({exc}); retrying.", client=client, exc=exc))
    raise RuntimeError(tr("Download failed: {exc}", exc=last_exc))


def _ytdl_options(
    url: str,
    output_path: Path,
    fmt: str,
    suffix: str = "",
    *,
    ffmpeg: str | None,
    quality: str | None = None,
    download_sections: str | None = None,
    progress_hook: Callable[[dict], None] | None = None,
    noplaylist: bool = True,
    outtmpl: str | None = None,
    player_client: str = "tv_embedded",
    name_template: str = DEFAULT_NAME,
    ipv4: bool = False,
    audio_fmt: str = "mp3",
    format_id: str | None = None,
    archive: bool = False,
    live: bool = False,
) -> dict:
    common: dict = {
        "outtmpl": outtmpl
        or str(output_path / f"{name_template}{suffix}.%(ext)s"),
        "noplaylist": noplaylist,
        "quiet": True,
        "no_warnings": True,
        "format_sort": ["proto:https"],
        # tv_embedded exposes the full height ladder (up to 2160p); the
        # android client caps out at 360p but is far more reliable, so it is
        # used as the fallback in download() when YouTube answers 403.
        "extractor_args": {"youtube": {"player_client": [player_client]}},
    }
    common.update(_net_opts(archive=archive))
    if live:  # record from the first segment; MPEG-TS stays playable if it is stopped early
        common["live_from_start"] = True
        common["hls_use_mpegts"] = True
    if ipv4:  # see _network_unreachable()
        common["source_address"] = "0.0.0.0"
    if progress_hook is not None:
        common["progress_hooks"] = [progress_hook]
    if ffmpeg:
        common["ffmpeg_location"] = ffmpeg
    if download_sections:
        common["download_sections"] = download_sections

    if fmt == "mp3":
        codec, _ext, _encoder, lossy = audio_format(audio_fmt)
        extract: dict = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if lossy:  # FLAC / WAV have no bitrate
            extract["preferredquality"] = quality or DEFAULT_MP3_BITRATE
        return {**common, "format": format_id or "bestaudio/best", "postprocessors": [extract]}
    height = None
    if quality:
        try:
            height = int(quality.rstrip("p"))
        except ValueError:
            height = None
    if height:
        fmt_sel = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            # `<=?` also takes formats of unknown height (a plain file link)
            f"best[height<=?{height}][ext=mp4]/best[height<=?{height}]"
        )
    else:
        fmt_sel = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if format_id:  # an exact format picked from the list; the usual choice if it is gone
        fmt_sel = f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/{format_id}/{fmt_sel}"
    return {
        **common,
        "format": fmt_sel,
        # at a given resolution prefer H.264: YouTube's MP4s are often AV1,
        # which many players (and Qt's preview) can't decode. Resolution
        # still wins, so 1440p / 4K (VP9 / AV1 only) stay available.
        "format_sort": ["proto:https", "res", "vcodec:h264"],
        "merge_output_format": "mp4",
    }


# ── media metadata probe ───────────────────────────────────────────────_

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 VidGrab"
)


def _fetch_thumbnail(url: str | None, dest_dir: Path) -> str | None:
    """Download *url* into *dest_dir* (cached by URL hash); returns local path."""
    if not url or "://" not in url:
        return None
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        target = dest_dir / f"{name}.jpg"
        if not target.is_file():
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = resp.read()
            if len(data) < 50:
                return url
            target.write_bytes(data)
        return str(target)
    except (OSError, ValueError):
        return None


def fetch_dislikes(video_id: str, timeout: float = 8.0) -> int | None:
    """Best-effort dislike count via the public returnyoutubedislike API.

    YouTube removed public dislike counts, so this is an optional extra; any
    failure returns ``None`` and the UI simply skips the dislike line."""
    if not video_id:
        return None
    url = f"https://returnyoutubedislikeapi.com/votes?videoId={video_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        value = data.get("dislikes")
        return int(value) if isinstance(value, (int, float)) else None
    except (OSError, ValueError):
        return None


def _codec_short(codec: str) -> str:
    c = codec.lower()
    if c.startswith("avc"):
        return "H.264"
    if c.startswith(("vp09", "vp9")):
        return "VP9"
    if c.startswith("av01"):
        return "AV1"
    if c.startswith("hev"):
        return "H.265"
    if c.startswith("mp4a"):
        return "AAC"
    if c.startswith("opus"):
        return "Opus"
    if c in ("none", "mp4a"):
        return c
    return codec


def _human_size(size: float) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def _format_label(fmt: dict) -> str:
    """A compact human-readable label for one yt-dlp format dict."""
    parts: list[str] = []
    height = fmt.get("height")
    note = fmt.get("format_note")
    if height:
        parts.append(f"{height}p")
    elif note:
        parts.append(note)
    vcodec = fmt.get("vcodec")
    if vcodec and vcodec != "none":
        parts.append(_codec_short(vcodec))
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        parts.append(_human_size(size))
    return " \u00b7 ".join(parts)


def _height_key(label: str | None) -> int:
    match = re.search(r"(\d+)p", label or "")
    return int(match.group(1)) if match else 0


def _format_options(formats: list[dict]) -> list[dict]:
    """The formats a person can choose between, best first: what `format_id`
    in `download()` takes, plus the details to tell them apart."""
    out: list[dict] = []
    for f in formats:
        fid = f.get("format_id")
        vcodec, acodec = f.get("vcodec") or "none", f.get("acodec") or "none"
        if not fid or f.get("ext") == "mhtml" or "storyboard" in str(f.get("format_note")):
            continue
        if vcodec == "none" and acodec == "none":
            continue
        out.append({
            "id": str(fid),
            "height": f.get("height") or 0,
            "fps": f.get("fps") or 0,
            "vcodec": "" if vcodec == "none" else _codec_short(vcodec),
            "acodec": "" if acodec == "none" else _codec_short(acodec),
            "ext": f.get("ext") or "",
            "size": f.get("filesize") or f.get("filesize_approx") or 0,
            "abr": f.get("abr") or 0,
            "note": f.get("format_note") or "",
        })
    out.sort(key=lambda f: (f["vcodec"] == "", -f["height"], -f["fps"], -f["size"], -f["abr"]))
    return out


def _summarize(info: dict, thumb_dir: Path | None = None) -> dict:
    """Turn a raw yt-dlp extract_info dict into a compact UI summary."""
    entries = info.get("entries")
    is_playlist = info.get("_type") == "playlist" or isinstance(
        entries, (list, tuple)
    )
    result: dict = {
        "is_playlist": bool(is_playlist),
        "id": info.get("id"),
        "title": info.get("title") or info.get("id") or "",
        "uploader": (
            info.get("uploader")
            or info.get("channel")
            or info.get("uploader_id")
            or ""
        ),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "playlist_count": info.get("playlist_count"),
        "formats": [],
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "dislike_count": info.get("dislike_count"),
        "live_status": info.get("live_status"),  # is_live / is_upcoming / was_live / not_live
        "release_timestamp": info.get("release_timestamp"),
        "format_list": [],
    }
    if is_playlist and result["playlist_count"] is None:
        result["playlist_count"] = len(entries) if entries else None
    if not is_playlist:
        seen: set[int] = set()
        for fmt in info.get("formats") or []:
            height = fmt.get("height")
            if not height or height in seen:
                continue
            seen.add(height)
            label = _format_label(fmt)
            if label:
                result["formats"].append(label)
        result["formats"].sort(key=_height_key, reverse=True)
        result["format_list"] = _format_options(info.get("formats") or [])
    if thumb_dir:
        local = _fetch_thumbnail(result.get("thumbnail"), Path(thumb_dir))
        if local:
            result["thumbnail_local"] = local
    return result


def probe(
    url: str,
    *,
    thumb_dir: Path | None = None,
    translate: TranslateFn | None = None,
) -> dict:
    """Fetch (without downloading) metadata for *url* — videos and playlists.

    Playlist URLs are flattened so even huge playlists resolve quickly.
    Returns the :func:`_summarize` dict; the thumbnail is cached locally
    when *thumb_dir* is provided."""
    tr = translate or _noop_tr
    if not url.strip():
        raise RuntimeError(tr("No URL provided."))
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",
        # a stream that has not started has no formats yet: still describe it
        "ignore_no_formats_error": True,
        "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},
        **_net_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # IPv6 without a route: try IPv4
        if not _network_unreachable(exc):
            raise
        with yt_dlp.YoutubeDL({**opts, "source_address": "0.0.0.0"}) as ydl:
            info = ydl.extract_info(url, download=False)
    if info is None:
        raise RuntimeError(tr("Could not fetch video information."))
    return _summarize(info, thumb_dir=thumb_dir)


def search(query: str, count: int = 10, *, translate: TranslateFn | None = None) -> list[dict]:
    """Search YouTube for *query*: [{id, title, uploader, duration, views, url,
    thumbnail}] without opening each video."""
    tr = translate or _noop_tr
    query = query.strip()
    if not query:
        raise RuntimeError(tr("Type something to search for."))
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, **_net_opts()}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{int(count)}:{query}", download=False) or {}
    except Exception as exc:
        raise RuntimeError(tr("Search failed: {exc}", exc=exc)) from exc
    results = []
    for e in info.get("entries") or []:
        vid = e.get("id")
        if not vid:
            continue
        thumbs = e.get("thumbnails") or []
        results.append({
            "id": vid,
            "title": e.get("title") or vid,
            "uploader": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
            "views": e.get("view_count"),
            "url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
            "thumbnail": (thumbs[-1].get("url") if thumbs else e.get("thumbnail")) or "",
        })
    return results


# ── playlist downloads ─────────────────────────────────────────────────


def _new_files(output_path: Path, after: float) -> list[Path]:
    """Media files created in *output_path* on or after time *after*."""
    exts = (".mp4", ".mp3", ".webm", ".mkv", ".m4a")
    files = []
    try:
        entries = list(output_path.iterdir())
    except OSError:
        return files
    for p in entries:
        if (
            not p.is_file()
            or p.suffix.lower() not in exts
            or p.name.endswith((".part", ".ytdl"))
        ):
            continue
        try:
            if p.stat().st_mtime >= after - 1.0:
                files.append(p)
        except OSError:
            continue
    return files


def _playlist_order(path: Path) -> int:
    match = re.match(r"^(\d+) - ", path.name)
    return int(match.group(1)) if match else 10**9


def download_playlist(
    url: str,
    output_dir: str | Path,
    fmt: str,
    *,
    quality: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
    name_template: str = DEFAULT_NAME,
    audio_fmt: str = "mp3",
    skip_downloaded: bool = False,
) -> list[Path]:
    """
    Download every video in a playlist (or channel) as MP4 / MP3.
    With *skip_downloaded*, videos listed in the download archive
    (`configure_network`) are left out, and new ones are added to it.

    Trim, flip and speed are *not* applied — each entry is downloaded in
    the selected format and quality. Returns the list of saved files,
    ordered by playlist position."""
    tr = translate or _noop_tr
    if not url.strip():
        raise RuntimeError(tr("No URL provided."))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        _ensure_ffmpeg_on_path(ffmpeg)
    if fmt == "mp3" and not ffmpeg:
        raise RuntimeError(
            tr(
                "ffmpeg is required for MP3 downloads. "
                "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
                "or install ffmpeg and add it to PATH."
            )
        )

    log = (lambda msg: None) if on_log is None else on_log

    def progress_hook(data: dict) -> None:
        if not on_progress:
            return
        status = data.get("status")
        if status != "downloading":
            if status == "finished":
                on_progress(tr("Processing…"), 95.0)
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        info = data.get("info_dict") or {}
        current = info.get("playlist_index")
        total_n = info.get("playlist_count")
        if total:
            pct = min(100.0, downloaded / total * 100)
            if current and total_n:
                on_progress(
                    tr("Downloading video {n} of {total}…", n=current, total=total_n)
                    + _rate(data),
                    pct,
                )
            else:
                on_progress(tr("Downloading… {pct:.1f}%", pct=pct) + _rate(data), pct)
        else:
            if current and total_n:
                on_progress(
                    tr("Downloading video {n} of {total}…", n=current, total=total_n),
                    0.0,
                )
            else:
                on_progress(tr("Downloading…"), None)

    t0 = time.time()

    def extract(client: str, ipv4: bool) -> None:
        opts = _ytdl_options(
            url,
            output_path,
            fmt,
            ffmpeg=ffmpeg,
            quality=quality,
            progress_hook=progress_hook,
            noplaylist=False,
            outtmpl=str(output_path / f"%(playlist_index)02d - {name_template}.%(ext)s"),
            player_client=client,
            ipv4=ipv4,
            audio_fmt=audio_fmt,
            archive=skip_downloaded,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)

    _try_clients(extract, log, tr)

    files = sorted(_new_files(output_path, t0), key=_playlist_order)
    if not files and skip_downloaded and NETWORK.archive:
        log(tr("Nothing new: every video in this playlist was downloaded before."))
        if on_progress:
            on_progress(tr("Complete"), 100.0)
        return []
    if not files:
        raise RuntimeError(tr("Download finished but output file was not found."))
    for f in files:
        log(tr("Saved: {name}", name=f.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return files


# ── live streams ──────────────────────────────────────────────────────────

_sleep = time.sleep  # replaced in tests
STREAM_POLL_S = 30  # how often a stream that has not started yet is asked again


def _stream_status(url: str) -> tuple[str | None, float | None]:
    """(live_status, scheduled start) of *url*; (None, None) if it can't be told."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "ignore_no_formats_error": True, **_net_opts()}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except Exception:  # noqa: BLE001 - the download itself will report the real problem
        return None, None
    return info.get("live_status"), info.get("release_timestamp")


def _wait_for_stream(
    url: str, on_progress: ProgressCallback | None, log: LogCallback, tr: TranslateFn
) -> None:
    """Block until a scheduled stream / premiere has started. The progress
    callback (called every second) is where a Cancel is noticed."""
    status, when = _stream_status(url)
    if status != "is_upcoming":
        return
    log(tr("The stream has not started yet; waiting for it."))
    while status == "is_upcoming":
        for _ in range(STREAM_POLL_S):
            if on_progress:
                left = max(0, int(when - time.time())) if when else None
                on_progress(tr("Waiting for the stream to start…")
                            + (f" {left // 60}:{left % 60:02d}" if left is not None else ""),
                            None)
            _sleep(1)
        status, when = _stream_status(url)


def _keep_recording(
    output_path: Path, since: float, ffmpeg: str | None, log: LogCallback, tr: TranslateFn
) -> Path | None:
    """After a recording was stopped: turn the partial file into a playable
    MP4 (None if nothing was recorded)."""
    parts = []
    for p in output_path.glob("*.part"):
        try:
            if p.stat().st_mtime >= since - 1 and p.stat().st_size > 0:
                parts.append(p)
        except OSError:
            continue
    if not parts:
        return None
    part = max(parts, key=lambda p: p.stat().st_mtime)
    target = part.with_suffix("")  # drop ".part"
    if ffmpeg:
        out = target.with_suffix(".mp4")
        if out.exists():
            out = out.with_name(f"{out.stem}.recorded.mp4")
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(part), "-c", "copy", "-movflags", "+faststart", str(out)],
            capture_output=True, text=True, check=False)
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            part.unlink(missing_ok=True)
            log(tr("Recording stopped; saved what was recorded: {name}", name=out.name))
            return out
        out.unlink(missing_ok=True)
    kept = target.with_suffix(".ts")
    part.replace(kept)
    log(tr("Recording stopped; saved what was recorded: {name}", name=kept.name))
    return kept


def download(
    url: str,
    output_dir: str | Path,
    fmt: str,
    *,
    video_filter: str | None = None,
    speed: float | None = None,
    quality: str | None = None,
    section_start: str | None = None,
    section_end: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
    name_template: str = DEFAULT_NAME,
    audio_fmt: str = "mp3",
    format_id: str | None = None,
    live: bool = False,
) -> Path:
    """
    Download a URL as MP4 or audio (MP3 unless *audio_fmt* says otherwise).
    *format_id* picks one exact format from `probe()`'s ``format_list``;
    *live* records a live stream from its start (waiting for it to begin).

    Returns the path to the downloaded file.
    """
    tr = translate or _noop_tr
    speed = _validate_speed(speed, translate=translate)
    speed_m = _speed_marker(speed)
    if not url.strip():
        raise RuntimeError(tr("No URL provided."))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        _ensure_ffmpeg_on_path(ffmpeg)

    if fmt == "mp3" and not ffmpeg:
        raise RuntimeError(
            tr(
                "ffmpeg is required for MP3 downloads. "
                "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
                "or install ffmpeg and add it to PATH."
            )
        )

    audio_ext = audio_format(audio_fmt)[1]
    out_ext = audio_ext.lstrip(".") if fmt == "mp3" else "mp4"

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    def progress_hook(data: dict) -> None:
        if not on_progress:
            return
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            if total:
                pct = min(100.0, downloaded / total * 100)
                on_progress(tr("Downloading… {pct:.1f}%", pct=pct) + _rate(data), pct)
            else:
                on_progress(tr("Downloading…") + _rate(data), None)
        elif status == "finished":
            on_progress(tr("Processing…"), 95.0)

    do_trim = bool(section_start or section_end)
    start, end = 0.0, float("inf")
    if do_trim:
        start, end = _parse_trim(section_start, section_end, translate=translate)

    if do_trim and not ffmpeg:
        raise RuntimeError(tr("ffmpeg is required to trim downloads."))

    if do_trim:
        suffix = ".trimtmp"
    elif fmt == "mp4" and (video_filter or speed is not None):
        suffix = ".proctmp"
    elif fmt == "mp3":
        suffix = ".mp3tmp"
    else:
        suffix = ""

    # Always fetch the full video and cut locally with ffmpeg: YouTube's media
    # servers answer ranged (download_sections) requests with HTTP 403 or fall
    # back to the full file, so range-based downloads are unreliable.
    def extract(client: str, ipv4: bool) -> dict:
        opts = _ytdl_options(
            url,
            output_path,
            fmt,
            suffix,
            ffmpeg=ffmpeg,
            quality=quality,
            progress_hook=progress_hook,
            player_client=client,
            name_template=name_template,
            ipv4=ipv4,
            audio_fmt=audio_fmt,
            # format ids belong to one player client: the fallback goes by height
            format_id=format_id if client == "tv_embedded" else None,
            live=live,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError(tr("Could not fetch video information."))
            return info

    started = time.time()
    if live:
        _wait_for_stream(url, on_progress, log, tr)
    # tv_embedded gives the full resolution but YouTube can 403 its media
    # URLs; android is low-res but reliable, so it acts as the last resort.
    try:
        info = _try_clients(extract, log, tr)
    except DownloadCancelled:
        # stopping a recording keeps what was recorded so far
        saved = _keep_recording(output_path, started, ffmpeg, log, tr) if live else None
        if saved is None:
            raise
        if on_progress:
            on_progress(tr("Complete"), 100.0)
        return saved

    title = info.get("title", "download")
    out_file = _locate_output(output_path, title, fmt, suffix, audio_ext)
    if out_file is None:
        raise RuntimeError(tr("Download finished but output file was not found."))

    use_ffmpeg = do_trim or (video_filter and fmt == "mp4") or speed is not None

    if not use_ffmpeg:
        base = out_file.stem
        for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
            if base.endswith(tmp_suffix):
                base = base[: -len(tmp_suffix)]
                break
        final_file = output_path / f"{base}{speed_m}.{out_ext}"
        if final_file != out_file:
            final_file.unlink(missing_ok=True)
            out_file.replace(final_file)
            out_file = final_file
        log(tr("Saved: {name}", name=out_file.name))
        if on_progress:
            on_progress(tr("Complete"), 100.0)
        return out_file

    ext = out_ext
    base = out_file.stem
    for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
        if base.endswith(tmp_suffix):
            base = base[: -len(tmp_suffix)]
            break
    final_file = output_path / f"{base}{speed_m}.{ext}"

    final_file.unlink(missing_ok=True)
    _trim(
        ffmpeg or "",
        out_file,
        final_file,
        start,
        end,
        video_filter=video_filter if fmt == "mp4" else None,
        speed=speed,
        audio_bitrate=quality if fmt == "mp3" else None,
        on_progress=on_progress,
        on_log=on_log,
        translate=translate,
    )

    out_file.unlink(missing_ok=True)

    log(tr("Saved: {name}", name=final_file.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return final_file


def download_both(
    url: str,
    output_dir: str | Path,
    *,
    video_filter: str | None = None,
    speed: float | None = None,
    quality: str | None = None,
    section_start: str | None = None,
    section_end: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
    name_template: str = DEFAULT_NAME,
    audio_fmt: str = "mp3",
    format_id: str | None = None,
) -> tuple[Path, Path]:
    """
    Download a video once as MP4, then derive the MP3 from it locally.

    The MP4 carries the sped-up audio, so the derived MP3 keeps the speed
    without a second encode.

    Returns (mp4_path, mp3_path).
    """
    mp4_path = download(
        url,
        output_dir,
        "mp4",
        video_filter=video_filter,
        speed=speed,
        quality=quality,
        section_start=section_start,
        section_end=section_end,
        on_progress=on_progress,
        on_log=on_log,
        translate=translate,
        name_template=name_template,
        format_id=format_id,
    )
    mp3_path = derive_mp3(
        mp4_path,
        output_dir,
        audio_bitrate=quality if quality and quality.isdigit() else None,
        audio_fmt=audio_fmt,
        on_progress=on_progress,
        on_log=on_log,
        translate=translate,
    )
    return mp4_path, mp3_path


# ── YouTube subtitles ─────────────────────────────────────────────────────

# language key -> exact YouTube caption codes, best first. No wildcards: a
# pattern like "en-.*" also matches YouTube's auto-translated tracks
# ("en-de", …), which multiplies requests and trips HTTP 429.
SUBTITLE_LANGS: dict[str, list[str]] = {
    "zh-Hant": ["zh-TW", "zh-Hant", "zh-HK"],
    "zh-Hans": ["zh-CN", "zh-Hans", "zh"],
    "en": ["en", "en-US", "en-GB"],
    "ja": ["ja"],
    "ko": ["ko"],
    "es": ["es", "es-419", "es-ES"],
    "fr": ["fr"],
    "de": ["de"],
    "pt": ["pt", "pt-BR", "pt-PT"],
    "ru": ["ru"],
    "id": ["id"],
    "vi": ["vi"],
    "th": ["th"],
    "ar": ["ar"],
    "hi": ["hi"],
}
SUBTITLE_RETRY_WAITS = (4, 10)  # seconds to wait before asking again after HTTP 429


class _ErrorLog:
    """yt-dlp logger that only remembers errors (to tell HTTP 429 apart)."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, _msg: str) -> None: ...

    def info(self, _msg: str) -> None: ...

    def warning(self, _msg: str) -> None: ...

    def error(self, msg: str) -> None:
        self.errors.append(str(msg))


def fetch_subtitles(
    url: str,
    output_dir: str | Path,
    lang: str,
    base_name: str,
    *,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path | None:
    """Save the video's captions in *lang* as ``<base_name>.<lang>.srt``.

    Uploaded captions are preferred; YouTube's auto-generated (or
    auto-translated) captions are used when there are none. Returns None
    when the video has no captions in that language."""
    tr = translate or _noop_tr
    output_path = Path(output_dir)
    ffmpeg = find_ffmpeg()
    patterns = SUBTITLE_LANGS.get(lang, [lang])
    before = time.time()
    opts: dict = {
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # one failing track (e.g. HTTP 429) must not discard the others
        "ignoreerrors": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": patterns,
        "subtitlesformat": "srt/vtt/best",
        "outtmpl": {"subtitle": str(output_path / f"{base_name}.%(ext)s"),
                    "default": str(output_path / f"{base_name}.%(ext)s")},
        "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
        **_net_opts(),
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg

    def saved() -> list[Path]:
        return [p for p in output_path.glob(f"{glob_escape(base_name)}.*.srt")
                if p.stat().st_mtime >= before - 1]

    # YouTube's translated tracks answer HTTP 429 when asked too fast: wait and
    # ask again (ignoreerrors hides the error, so it is read from the logger)
    found: list[Path] = []
    for wait in (0, *SUBTITLE_RETRY_WAITS):
        if wait:
            if on_log:
                on_log(tr("Too many requests; trying the subtitles again in {s} s.", s=wait))
            _sleep(wait)
        errors = _ErrorLog()
        try:
            with yt_dlp.YoutubeDL({**opts, "logger": errors}) as ydl:
                ydl.extract_info(url, download=True)
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - captions are optional; keep what was saved
            errors.errors.append(str(exc))
            if on_log:
                on_log(tr("Could not download subtitles: {exc}", exc=exc))
        found = saved()
        if found or not any("429" in e for e in errors.errors):
            break
    if not found:
        if on_log:
            on_log(tr("No subtitles in that language for this video."))
        return None
    # keep the best-ranked language, drop extra matches
    def rank(p: Path) -> int:
        code = p.suffixes[-2].lstrip(".") if len(p.suffixes) >= 2 else ""
        return patterns.index(code) if code in patterns else len(patterns)
    found.sort(key=rank)
    best = found[0]
    for extra in found[1:]:
        extra.unlink(missing_ok=True)
    final = output_path / f"{base_name}.{lang}.srt"
    if best != final:
        final.unlink(missing_ok=True)
        best.rename(final)
    return final


def glob_escape(name: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", name)

