"""VidGrab download / processing logic using yt-dlp."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import parse_duration


ProgressCallback = Callable[[str, float | None], None]
LogCallback = Callable[[str], None]


def get_app_dir() -> Path:
    """Directory containing the app (or PyInstaller extract folder)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def get_bundle_dir() -> Path:
    """Directory next to the executable when frozen, else project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    """Locate a native ffmpeg: bundled next to exe, inside app bundle, then PATH."""
    bundle = get_bundle_dir()
    app = get_app_dir()

    if sys.platform == "win32":
        candidates: list[Path] = [
            bundle / "ffmpeg" / "ffmpeg.exe",
            bundle / "ffmpeg.exe",
            app / "ffmpeg" / "ffmpeg.exe",
        ]
    else:
        candidates = [
            bundle / "ffmpeg" / "ffmpeg",
            app / "ffmpeg" / "ffmpeg",
        ]

    import shutil

    if sys.platform == "win32":
        ffmpeg_cmd = "ffmpeg.exe"
    else:
        ffmpeg_cmd = "ffmpeg"

    for path in candidates:
        if path.is_file():
            return str(path)

    found = shutil.which(ffmpeg_cmd)
    return found


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads" / "VidGrab"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def _locate_output(
    output_path: Path, title: str, fmt: str, suffix: str
) -> Path | None:
    ext = ".mp3" if fmt == "mp3" else ".mp4"
    if suffix:
        patterns = [f"*{suffix}{ext}"]
    else:
        patterns = [f"*{ext}"]
    for pat in patterns:
        matches = [
            p
            for p in output_path.glob(pat)
            if p.is_file() and p.suffix.lower() not in (".part", ".ytdl")
        ]
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    return None


def _trim(
    ffmpeg: str,
    src: Path,
    dst: Path,
    start: float,
    end: float,
    video_filter: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
) -> None:
    args = [ffmpeg, "-y"]
    if start:
        args += ["-ss", str(start)]
    args += ["-i", str(src)]
    if end != float("inf"):
        args += ["-t", str(end - start)]
    args += ["-map", "0"]
    if video_filter:
        args += ["-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
        if dst.suffix.lower() == ".mp4":
            args += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    else:
        args += ["-c", "copy"]
    args.append(str(dst))

    if on_log:
        on_log(" ".join(args))
    if on_progress:
        on_progress("Trimming…", 96.0)

    import subprocess

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        if on_log and proc.stderr:
            for line in proc.stderr.strip().splitlines()[-6:]:
                on_log(line)
        raise RuntimeError(
            f"ffmpeg failed to trim the file (exit code {proc.returncode})."
        )


def process_local_file(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    video_filter: str | None = None,
    section_start: str | None = None,
    section_end: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
) -> Path:
    """
    Apply trim / flip to a local media file and write the result to *output_dir*.

    Returns the path to the processed file.
    """
    src = Path(input_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required to process local files. "
            "Install ffmpeg or place it next to the app."
        )
    _ffmpeg_dir = os.path.dirname(ffmpeg)
    if _ffmpeg_dir and _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ext = src.suffix  # keep original extension
    stem = src.stem
    final_file = output_path / f"{stem}_processed{ext}"

    do_trim = bool(section_start or section_end)
    start = end = None
    if do_trim:
        start = parse_duration(section_start) if section_start else 0
        end = parse_duration(section_end) if section_end else float("inf")
        if start is None:
            raise RuntimeError(
                f'Invalid start time "{section_start}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03)."
            )
        if end is None:
            raise RuntimeError(
                f'Invalid end time "{section_end}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03)."
            )
        if end <= start:
            raise RuntimeError(
                "Trim end time must be after the start time. "
                f"Got start {start:.0f}s, end {end:.0f}s."
            )

    needs_ffmpeg = do_trim or video_filter
    if not needs_ffmpeg:
        final_file.unlink(missing_ok=True)
        import shutil
        shutil.copy2(src, final_file)
        if on_log:
            on_log(f"Copied: {final_file.name}")
        if on_progress:
            on_progress("Complete", 100.0)
        return final_file

    final_file.unlink(missing_ok=True)
    _trim(
        ffmpeg,
        src,
        final_file,
        start or 0,
        end or float("inf"),
        video_filter=video_filter,
        on_progress=on_progress,
        on_log=on_log,
    )

    if on_log:
        on_log(f"Saved: {final_file.name}")
    if on_progress:
        on_progress("Complete", 100.0)
    return final_file


def download(
    url: str,
    output_dir: str | Path,
    fmt: str,
    *,
    video_filter: str | None = None,
    section_start: str | None = None,
    section_end: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
) -> Path:
    """
    Download a YouTube URL as MP4 or MP3.

    Returns the path to the downloaded file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        _ffmpeg_dir = os.path.dirname(ffmpeg)
        if _ffmpeg_dir and _ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    if fmt == "mp3" and not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required for MP3 downloads. "
            "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
            "or install ffmpeg and add it to PATH."
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
                on_progress(f"Downloading… {pct:.1f}%", pct)
            else:
                on_progress("Downloading…", None)
        elif status == "finished":
            on_progress("Processing…", 95.0)

    do_trim = bool(section_start or section_end)
    start = end = None
    if do_trim:
        start = parse_duration(section_start) if section_start else 0
        end = parse_duration(section_end) if section_end else float("inf")
        if start is None:
            raise RuntimeError(
                f'Invalid start time "{section_start}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03)."
            )
        if end is None:
            raise RuntimeError(
                f'Invalid end time "{section_end}". '
                "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03)."
            )
        if end <= start:
            raise RuntimeError(
                "Trim end time must be after the start time. "
                f"Got start {start:.0f}s, end {end:.0f}s."
            )

    if do_trim:
        suffix = ".trimtmp"
    elif fmt == "mp3":
        suffix = ".mp3tmp"
    elif video_filter:
        suffix = ".proctmp"
    else:
        suffix = ""
    common: dict = {
        "outtmpl": str(output_path / f"%(title)s{suffix}.%(ext)s"),
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "format_sort": ["proto:https"],
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    if ffmpeg:
        common["ffmpeg_location"] = ffmpeg

    if fmt == "mp3":
        ydl_opts = {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    else:
        ydl_opts = {
            **common,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        }

    log(f"Output folder: {output_path}")
    if ffmpeg:
        log(f"Using ffmpeg: {ffmpeg}")
    if do_trim:
        log(f"Trimming to {start:.0f}s - {end}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("Could not fetch video information.")

        title = info.get("title", "download")
        out_file = _locate_output(output_path, title, fmt, suffix)
        if out_file is None:
            raise RuntimeError("Download finished but output file was not found.")

    use_ffmpeg = do_trim or (video_filter and fmt == "mp4")

    if not use_ffmpeg:
        base = out_file.stem
        for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
            if base.endswith(tmp_suffix):
                base = base[: -len(tmp_suffix)]
                break
        final_file = output_path / f"{base}.{fmt}"
        if final_file != out_file:
            final_file.unlink(missing_ok=True)
            out_file.replace(final_file)
            out_file = final_file
        log(f"Saved: {out_file.name}")
        if on_progress:
            on_progress("Complete", 100.0)
        return out_file

    ext = "mp3" if fmt == "mp3" else "mp4"
    base = out_file.stem
    for tmp_suffix in (".trimtmp", ".proctmp", ".mp3tmp"):
        if base.endswith(tmp_suffix):
            base = base[: -len(tmp_suffix)]
            break
    final_file = output_path / f"{base}.{ext}"

    final_file.unlink(missing_ok=True)
    _trim(
        ffmpeg,
        out_file,
        final_file,
        start or 0,
        end or float("inf"),
        video_filter=video_filter if fmt == "mp4" else None,
        on_progress=on_progress,
        on_log=on_log,
    )

    out_file.unlink(missing_ok=True)

    log(f"Saved: {final_file.name}")
    if on_progress:
        on_progress("Complete", 100.0)
    return final_file
