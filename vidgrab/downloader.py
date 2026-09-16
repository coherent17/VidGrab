"""VidGrab download / processing logic using yt-dlp."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import yt_dlp
from yt_dlp.utils import parse_duration

ProgressCallback = Callable[[str, float | None], None]
LogCallback = Callable[[str], None]
TranslateFn = Callable[..., str]

DEFAULT_MP3_BITRATE = "192"

MIN_SPEED = 0.25
MAX_SPEED = 4.0


def _noop_tr(text: str, **kw: object) -> str:
    return text.format(**kw) if kw else text


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


def find_ffplay() -> str | None:
    """Locate ffplay next to ffmpeg (same folder), then PATH."""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        peer = Path(ffmpeg).parent / ("ffplay.exe" if sys.platform == "win32" else "ffplay")
        if peer.is_file():
            return str(peer)
    return shutil.which("ffplay.exe" if sys.platform == "win32" else "ffplay")


def _ensure_ffmpeg_on_path(ffmpeg: str) -> None:
    """Put the bundled ffmpeg folder on PATH so yt-dlp can find its tools."""
    _ffmpeg_dir = os.path.dirname(ffmpeg)
    if _ffmpeg_dir and _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


# ── output locating ───────────────────────────────────────────────────────

def preview_args(
    path: str | Path,
    start: float,
    end: float,
    video_filter: str | None,
    speed: float | None,
    limit: float = 6.0,
) -> list[str]:
    """ffplay argv that previews the trim with speed/flip applied live.

    Runs without encoding: ffplay decodes and shows the first *limit*
    seconds of the selected section through the same filters used by
    `_trim`, so the preview matches the final output."""
    args = ["-autoexit"]
    if start:
        args += ["-ss", str(start)]
    length = min(limit, (end - start) if end != float("inf") else limit)
    args += ["-t", str(max(length, 0.01))]
    vf_parts = []
    if video_filter:
        vf_parts.append(video_filter)
    if speed is not None:
        vf_parts.append(f"setpts=(PTS-STARTPTS)/{speed}+STARTPTS")
    if vf_parts:
        args += ["-vf", ",".join(vf_parts)]
    if speed is not None:
        args += ["-af", ",".join(_atempo_chain(speed))]
    args.append(str(path))
    return args


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
    output_path: Path, title: str, fmt: str, suffix: str
) -> Path | None:
    ext = ".mp3" if fmt == "mp3" else ".mp4"
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
        is_audio_out = dst.suffix.lower() in (".mp3", ".aac", ".m4a")
        if is_audio_out:
            args += ["-vn", "-c:a", "libmp3lame", "-b:a", audio_bitrate or DEFAULT_MP3_BITRATE]
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
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Extract audio from an already-downloaded video as MP3 (no re-download)."""
    tr = translate or _noop_tr
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(tr("File not found: {src}", src=src))

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(tr("ffmpeg is required to extract MP3 audio."))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    out = output_path / f"{src.stem}.mp3"
    out.unlink(missing_ok=True)

    if on_progress:
        on_progress(tr("Extracting audio…"), None)
    _run_ffmpeg(
        [
            ffmpeg, "-y", "-i", str(src), "-vn", "-map", "0:a:0",
            "-c:a", "libmp3lame", "-b:a", audio_bitrate or DEFAULT_MP3_BITRATE, str(out),
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
) -> dict:
    common: dict = {
        "outtmpl": str(output_path / f"%(title)s{suffix}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "format_sort": ["proto:https"],
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    if progress_hook is not None:
        common["progress_hooks"] = [progress_hook]
    if ffmpeg:
        common["ffmpeg_location"] = ffmpeg
    if download_sections:
        common["download_sections"] = download_sections

    if fmt == "mp3":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality or DEFAULT_MP3_BITRATE,
                }
            ],
        }
    height = None
    if quality:
        try:
            height = int(quality.rstrip("p"))
        except ValueError:
            height = None
    if height:
        fmt_sel = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/best[height<={height}]"
        )
    else:
        fmt_sel = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    return {
        **common,
        "format": fmt_sel,
        "merge_output_format": "mp4",
    }


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
) -> Path:
    """
    Download a YouTube URL as MP4 or MP3.

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
                on_progress(tr("Downloading… {pct:.1f}%", pct=pct), pct)
            else:
                on_progress(tr("Downloading…"), None)
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

    # If trim is requested and ffmpeg is available, download only the wanted
    # section (HTTP range requests) instead of the whole video first.
    section_used = False
    sections = None
    if do_trim and ffmpeg:
        sections = f"*{int(start)}-{int(end) if end != float('inf') else 'inf'}"

    def extract(use_sections: bool) -> dict:
        opts = _ytdl_options(
            url,
            output_path,
            fmt,
            suffix,
            ffmpeg=ffmpeg,
            quality=quality,
            download_sections=sections if use_sections else None,
            progress_hook=progress_hook,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError(tr("Could not fetch video information."))
            return info

    if sections:
        try:
            info = extract(True)
            section_used = True
        except Exception as exc:  # noqa: BLE001 - fall back to full download
            log(tr("Section download unavailable ({exc}); downloading in full.", exc=exc))
            info = extract(False)
    else:
        info = extract(False)

    title = info.get("title", "download")
    out_file = _locate_output(output_path, title, fmt, suffix)
    if out_file is None:
        raise RuntimeError(tr("Download finished but output file was not found."))

    use_ffmpeg = do_trim or (video_filter and fmt == "mp4") or speed is not None

    if not use_ffmpeg:
        base = out_file.stem
        for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
            if base.endswith(tmp_suffix):
                base = base[: -len(tmp_suffix)]
                break
        final_file = output_path / f"{base}{speed_m}.{fmt}"
        if final_file != out_file:
            final_file.unlink(missing_ok=True)
            out_file.replace(final_file)
            out_file = final_file
        log(tr("Saved: {name}", name=out_file.name))
        if on_progress:
            on_progress(tr("Complete"), 100.0)
        return out_file

    ext = "mp3" if fmt == "mp3" else "mp4"
    base = out_file.stem
    for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
        if base.endswith(tmp_suffix):
            base = base[: -len(tmp_suffix)]
            break
    final_file = output_path / f"{base}{speed_m}.{ext}"

    # If the section download already cut the video, don't cut it again.
    trim_start, trim_end = (
        (0.0, float("inf")) if section_used else (start, end)
    )

    final_file.unlink(missing_ok=True)
    _trim(
        ffmpeg or "",
        out_file,
        final_file,
        trim_start,
        trim_end,
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
    )
    mp3_path = derive_mp3(
        mp4_path,
        output_dir,
        on_progress=on_progress,
        on_log=on_log,
        translate=translate,
    )
    return mp4_path, mp3_path